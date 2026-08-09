use std::io::{BufWriter, Read, Write};
use std::net::ToSocketAddrs;
use std::path::Path;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use suppaftp::list::File as RemoteFile;
use suppaftp::types::FileType as TransferFileType;
use suppaftp::{FtpError, FtpStream};

use super::{FileEntry, Storage, hash_reader, validate_relative_path};

#[derive(Debug, Clone)]
pub struct FtpStorage {
    host: String,
    port: u16,
    username: String,
    password_env: String,
    root: String,
    timeout: Duration,
}

impl FtpStorage {
    pub fn new(
        host: String,
        port: u16,
        username: String,
        password_env: String,
        root: String,
        timeout_seconds: u64,
        allow_plaintext: bool,
    ) -> Result<Self> {
        if host.trim().is_empty() || username.trim().is_empty() || password_env.trim().is_empty() {
            bail!("FTP host, username, and password environment variable are required");
        }
        if root.contains('\0') || root.contains('\\') {
            bail!("FTP root contains an invalid separator or NUL");
        }
        if timeout_seconds == 0 {
            bail!("FTP timeout must be positive");
        }
        if !allow_plaintext {
            bail!(
                "plaintext FTP is disabled; use a mounted NAS path or explicitly allow it on a trusted network"
            );
        }
        let root = if root.trim().is_empty() || root == "/" {
            "/".to_owned()
        } else {
            let relative_root = root.trim_matches('/');
            validate_relative_path(relative_root).context("FTP root is unsafe")?;
            format!("/{relative_root}")
        };
        Ok(Self {
            host,
            port,
            username,
            password_env,
            root,
            timeout: Duration::from_secs(timeout_seconds),
        })
    }

    fn connect(&self) -> Result<FtpStream> {
        let password = std::env::var(&self.password_env).with_context(|| {
            format!(
                "missing FTP password environment variable {}",
                self.password_env
            )
        })?;
        let address = (self.host.as_str(), self.port)
            .to_socket_addrs()
            .with_context(|| format!("failed to resolve FTP host {}", self.host))?
            .next()
            .with_context(|| format!("FTP host {} resolved to no addresses", self.host))?;
        let mut ftp = FtpStream::connect_timeout(address, self.timeout)
            .with_context(|| format!("failed to connect to FTP {}:{}", self.host, self.port))?;
        ftp.get_ref().set_read_timeout(Some(self.timeout))?;
        ftp.get_ref().set_write_timeout(Some(self.timeout))?;
        ftp.login(&self.username, &password)
            .with_context(|| format!("failed to log in to FTP {}:{}", self.host, self.port))?;
        ftp.transfer_type(TransferFileType::Binary)
            .context("failed to enable binary FTP transfers")?;
        Ok(ftp)
    }

    pub fn check_connection(&self) -> Result<()> {
        let mut ftp = self.connect()?;
        // CWD is widely supported and avoids requiring MLST support merely to
        // validate credentials and root accessibility.
        ftp.cwd(&self.root)
            .with_context(|| format!("FTP root is not accessible: {}", self.root))?;
        ftp.quit()
            .context("failed to close FTP doctor connection")?;
        Ok(())
    }

    fn remote_path(&self, relative: &str) -> Result<String> {
        let relative = validate_relative_path(relative)?;
        if relative.is_empty() {
            Ok(self.root.clone())
        } else if self.root == "/" {
            Ok(format!("/{relative}"))
        } else {
            Ok(format!("{}/{relative}", self.root))
        }
    }

    fn parse_listing(&self, ftp: &mut FtpStream, remote: &str) -> Result<Vec<RemoteFile>> {
        match ftp.mlsd(Some(remote)) {
            Ok(lines) => lines
                .into_iter()
                .map(|line| RemoteFile::try_from(line).map_err(anyhow::Error::from))
                .collect(),
            Err(_) => ftp
                .list(Some(remote))
                .with_context(|| format!("failed to list FTP directory {remote}"))?
                .into_iter()
                .map(|line| RemoteFile::try_from(line).map_err(anyhow::Error::from))
                .collect(),
        }
    }

    fn list_directory(
        &self,
        ftp: &mut FtpStream,
        relative: &str,
        output: &mut Vec<FileEntry>,
    ) -> Result<()> {
        let remote = self.remote_path(relative)?;
        let listing = self.parse_listing(ftp, &remote)?;
        for item in listing {
            let name = item.name();
            if name == "." || name == ".." {
                continue;
            }
            // An FTP server controls listing text; validate it before using it
            // as part of another command.
            if name.contains('/') {
                bail!("FTP server returned an entry name containing '/': {name:?}");
            }
            validate_relative_path(name)
                .with_context(|| format!("FTP server returned unsafe entry name {name:?}"))?;
            if item.is_symlink() {
                bail!("FTP symbolic links are not supported: {name:?}");
            }
            let path = if relative.is_empty() {
                name.to_owned()
            } else {
                format!("{relative}/{name}")
            };
            let entry = FileEntry {
                path: path.clone(),
                size: item.size() as u64,
                is_dir: item.is_directory(),
                modified: Some(item.modified()),
            };
            output.push(entry);
            if item.is_directory() {
                self.list_directory(ftp, &path, output)?;
            }
        }
        Ok(())
    }

    fn create_remote_parents(&self, ftp: &mut FtpStream, relative: &str) -> Result<()> {
        let normalized = validate_relative_path(relative)?;
        let mut parts: Vec<&str> = normalized.split('/').collect();
        parts.pop();
        let mut current = String::new();
        for part in parts {
            if !current.is_empty() {
                current.push('/');
            }
            current.push_str(part);
            let remote = self.remote_path(&current)?;
            if let Err(error) = ftp.mkdir(&remote) {
                // MKD commonly reports an error for an existing directory;
                // CWD is more broadly supported than MLST and proves that
                // ignoring the error is safe.
                if ftp.cwd(&remote).is_err() {
                    return Err(error)
                        .with_context(|| format!("failed to create FTP directory {remote}"));
                }
                ftp.cwd(&self.root)
                    .with_context(|| format!("failed to restore FTP root {}", self.root))?;
            }
        }
        Ok(())
    }

    fn metadata_from_listing(
        &self,
        ftp: &mut FtpStream,
        relative: &str,
    ) -> Result<Option<FileEntry>> {
        if relative.is_empty() {
            ftp.cwd(&self.root)
                .with_context(|| format!("FTP root is not accessible: {}", self.root))?;
            return Ok(Some(FileEntry {
                path: String::new(),
                size: 0,
                is_dir: true,
                modified: None,
            }));
        }
        let (parent, requested_name) = relative.rsplit_once('/').unwrap_or(("", relative));
        let parent_remote = self.remote_path(parent)?;
        let listing = self.parse_listing(ftp, &parent_remote)?;
        let mut case_insensitive_match = None;
        for item in listing {
            let name = item.name();
            if name.contains('/') || item.is_symlink() {
                continue;
            }
            let entry = FileEntry {
                path: relative.to_owned(),
                size: item.size() as u64,
                is_dir: item.is_directory(),
                modified: Some(item.modified()),
            };
            if name == requested_name {
                return Ok(Some(entry));
            }
            if name.eq_ignore_ascii_case(requested_name) {
                if case_insensitive_match.is_some() {
                    bail!(
                        "FTP directory contains ambiguous case-insensitive matches for {relative}"
                    );
                }
                case_insensitive_match = Some(entry);
            }
        }
        Ok(case_insensitive_match)
    }

    fn is_not_found(error: &FtpError) -> bool {
        matches!(error, FtpError::UnexpectedResponse(response) if response.status.code() == 550)
    }
}

impl Storage for FtpStorage {
    fn list_recursive(&self, relative: &str) -> Result<Vec<FileEntry>> {
        let normalized = validate_relative_path(relative)?;
        let mut ftp = self.connect()?;
        let mut output = Vec::new();
        self.list_directory(&mut ftp, &normalized, &mut output)?;
        output.sort_by(|a, b| a.path.cmp(&b.path));
        let _ = ftp.quit();
        Ok(output)
    }

    fn exists(&self, relative: &str) -> Result<bool> {
        Ok(self.metadata(relative)?.is_some())
    }

    fn metadata(&self, relative: &str) -> Result<Option<FileEntry>> {
        let normalized = validate_relative_path(relative)?;
        let remote = self.remote_path(&normalized)?;
        let mut ftp = self.connect()?;
        let result = ftp.mlst(Some(&remote));
        let parsed = match result {
            Ok(line) => {
                let file = RemoteFile::try_from(line)
                    .with_context(|| format!("failed to parse FTP metadata for {remote}"))?;
                if file.is_symlink() {
                    bail!("FTP symbolic links are not supported: {remote}");
                }
                Some(FileEntry {
                    path: normalized,
                    size: file.size() as u64,
                    is_dir: file.is_directory(),
                    modified: Some(file.modified()),
                })
            }
            Err(error) => match self.metadata_from_listing(&mut ftp, &normalized) {
                Ok(value) => value,
                Err(_) if Self::is_not_found(&error) => None,
                Err(list_error) => {
                    return Err(error).with_context(|| {
                        format!(
                            "failed to inspect FTP path {remote}; directory-list fallback also failed: {list_error:#}"
                        )
                    });
                }
            },
        };
        let _ = ftp.quit();
        Ok(parsed)
    }

    fn read(&self, relative: &str) -> Result<Vec<u8>> {
        let remote = self.remote_path(relative)?;
        let mut ftp = self.connect()?;
        let cursor = ftp
            .retr_as_buffer(&remote)
            .with_context(|| format!("failed to read FTP file {remote}"))?;
        let _ = ftp.quit();
        Ok(cursor.into_inner())
    }

    fn download(&self, relative: &str, destination: &Path) -> Result<()> {
        let remote = self.remote_path(relative)?;
        let mut ftp = self.connect()?;
        let file = std::fs::File::create(destination)
            .with_context(|| format!("failed to create {}", destination.display()))?;
        let mut writer = BufWriter::new(file);
        ftp.retr(&remote, |reader| {
            std::io::copy(reader, &mut writer)
                .map(|_| ())
                .map_err(FtpError::ConnectionError)
        })
        .with_context(|| format!("failed to download FTP file {remote}"))?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        let _ = ftp.quit();
        Ok(())
    }

    fn upload_atomic(&self, relative: &str, source: &mut dyn Read) -> Result<()> {
        let normalized = validate_relative_path(relative)?;
        if normalized.is_empty() {
            bail!("operation requires a non-root FTP path");
        }
        let final_path = self.remote_path(&normalized)?;
        let temporary_path = format!(
            "{final_path}.subtrans-part-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        );
        let mut ftp = self.connect()?;
        self.create_remote_parents(&mut ftp, &normalized)?;
        let result = (|| -> Result<()> {
            let mut stream = ftp
                .put_with_stream(&temporary_path)
                .with_context(|| format!("failed to start FTP upload {temporary_path}"))?;
            let uploaded = std::io::copy(source, &mut stream)
                .with_context(|| format!("failed while uploading FTP file {temporary_path}"))?;
            ftp.finalize_put_stream(stream)
                .with_context(|| format!("failed to finalize FTP upload {temporary_path}"))?;
            let remote_size = ftp
                .size(&temporary_path)
                .with_context(|| format!("failed to verify FTP upload size {temporary_path}"))?;
            if remote_size as u64 != uploaded {
                bail!(
                    "FTP upload size mismatch for {temporary_path}: sent {uploaded}, server reports {remote_size}"
                );
            }
            let backup_path = format!(
                "{final_path}.subtrans-backup-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_nanos()
            );
            let final_exists = ftp.size(&final_path).is_ok() || ftp.mlst(Some(&final_path)).is_ok();
            if final_exists {
                ftp.rename(&final_path, &backup_path).with_context(|| {
                    format!("failed to protect existing FTP destination {final_path}")
                })?;
            }
            if let Err(error) = ftp.rename(&temporary_path, &final_path) {
                if final_exists {
                    let _ = ftp.rename(&backup_path, &final_path);
                }
                return Err(error).with_context(|| {
                    format!(
                        "failed to atomically promote FTP file {temporary_path} to {final_path}"
                    )
                });
            }
            if final_exists && let Err(error) = ftp.rm(&backup_path) {
                eprintln!(
                    "FTP publish succeeded but backup cleanup failed path={backup_path} error={error}"
                );
            }
            Ok(())
        })();
        if result.is_err() {
            let _ = ftp.rm(&temporary_path);
        }
        let _ = ftp.quit();
        result
    }

    fn create_dir_all(&self, relative: &str) -> Result<()> {
        let normalized = validate_relative_path(relative)?;
        let mut ftp = self.connect()?;
        let fake_leaf = if normalized.is_empty() {
            String::new()
        } else {
            format!("{normalized}/.subtrans-directory-leaf")
        };
        self.create_remote_parents(&mut ftp, &fake_leaf)?;
        let _ = ftp.quit();
        Ok(())
    }

    fn rename(&self, from: &str, to: &str) -> Result<()> {
        let from_relative = validate_relative_path(from)?;
        let to_relative = validate_relative_path(to)?;
        if from_relative.is_empty() || to_relative.is_empty() {
            bail!("refusing to rename the FTP storage root");
        }
        if self.metadata(&to_relative)?.is_some() {
            bail!("refusing to overwrite existing FTP destination {to_relative}");
        }
        let from = self.remote_path(&from_relative)?;
        let to = self.remote_path(&to_relative)?;
        let mut ftp = self.connect()?;
        self.create_remote_parents(&mut ftp, &to_relative)?;
        ftp.rename(&from, &to)
            .with_context(|| format!("failed to rename FTP path {from} to {to}"))?;
        let _ = ftp.quit();
        Ok(())
    }

    fn remove(&self, relative: &str) -> Result<()> {
        let normalized = validate_relative_path(relative)?;
        if normalized.is_empty() {
            bail!("refusing to remove FTP storage root");
        }
        let remote = self.remote_path(&normalized)?;
        let mut ftp = self.connect()?;
        match ftp.rm(&remote) {
            Ok(()) => {}
            Err(file_error) => ftp
                .rmdir(&remote)
                .map_err(|_| file_error)
                .with_context(|| format!("failed to remove FTP path {remote}"))?,
        }
        let _ = ftp.quit();
        Ok(())
    }

    fn sha256(&self, relative: &str) -> Result<String> {
        let remote = self.remote_path(relative)?;
        let mut ftp = self.connect()?;
        let hash = ftp
            .retr(&remote, |reader| {
                hash_reader(reader).map_err(|error| {
                    FtpError::ConnectionError(std::io::Error::other(error.to_string()))
                })
            })
            .with_context(|| format!("failed to hash FTP file {remote}"))?;
        let _ = ftp.quit();
        Ok(hash)
    }

    fn local_path(&self, _relative: &str) -> Result<Option<std::path::PathBuf>> {
        Ok(None)
    }

    fn local_path_for_write(&self, _relative: &str) -> Result<Option<std::path::PathBuf>> {
        Ok(None)
    }
}
