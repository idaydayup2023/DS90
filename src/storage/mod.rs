mod ftp;
mod local;

use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use anyhow::{Context, Result, bail};
use sha2::{Digest, Sha256};

use crate::config::StorageConfig;

pub use ftp::FtpStorage;
pub use local::LocalStorage;

/// Metadata returned by every storage backend. Paths are always normalized,
/// relative POSIX paths (never host paths or FTP URLs).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileEntry {
    pub path: String,
    pub size: u64,
    pub is_dir: bool,
    pub modified: Option<SystemTime>,
}

/// Storage boundary shared by subtitle and migration workflows.
///
/// `read` is intentionally for small control files such as subtitles and
/// sidecars. Media files must use `download`, `upload_atomic`, or `sha256`, all
/// of which stream data without buffering the whole file in memory.
pub trait Storage: Send + Sync {
    fn list_recursive(&self, relative: &str) -> Result<Vec<FileEntry>>;
    fn exists(&self, relative: &str) -> Result<bool>;
    fn metadata(&self, relative: &str) -> Result<Option<FileEntry>>;
    fn read(&self, relative: &str) -> Result<Vec<u8>>;
    fn download(&self, relative: &str, destination: &Path) -> Result<()>;
    fn upload_atomic(&self, relative: &str, source: &mut dyn Read) -> Result<()>;
    fn create_dir_all(&self, relative: &str) -> Result<()>;
    fn rename(&self, from: &str, to: &str) -> Result<()>;
    fn remove(&self, relative: &str) -> Result<()>;
    fn sha256(&self, relative: &str) -> Result<String>;
    /// Returns a safe native path only for local storage. Callers must treat it
    /// as read-only and must not retain it beyond the current operation.
    fn local_path(&self, relative: &str) -> Result<Option<PathBuf>>;
    fn local_path_for_write(&self, relative: &str) -> Result<Option<PathBuf>>;
}

pub fn open_storage(config: &StorageConfig) -> Result<Box<dyn Storage>> {
    match config {
        StorageConfig::Local { root } => Ok(Box::new(LocalStorage::new(root)?)),
        StorageConfig::Ftp {
            host,
            port,
            username_env,
            password_env,
            root,
            timeout_seconds,
            allow_plaintext,
        } => Ok(Box::new(FtpStorage::new(
            host.clone(),
            *port,
            resolve_ftp_username(username_env)?,
            password_env.clone(),
            root.clone(),
            *timeout_seconds,
            *allow_plaintext,
        )?)),
    }
}

/// Opens the configured backend and checks credentials/root accessibility.
pub fn doctor(config: &StorageConfig) -> Result<()> {
    match config {
        StorageConfig::Local { root } => {
            let storage = LocalStorage::new(root)?;
            storage.metadata("")?;
            Ok(())
        }
        StorageConfig::Ftp {
            host,
            port,
            username_env,
            password_env,
            root,
            timeout_seconds,
            allow_plaintext,
        } => FtpStorage::new(
            host.clone(),
            *port,
            resolve_ftp_username(username_env)?,
            password_env.clone(),
            root.clone(),
            *timeout_seconds,
            *allow_plaintext,
        )?
        .check_connection(),
    }
}

/// Checks write permission. Local targets use `access(W_OK)`; FTP targets use
/// a unique empty file that is immediately removed, proving both write and
/// delete permission without touching media files.
pub fn doctor_writable(config: &StorageConfig, relative: &str, label: &str) -> Result<()> {
    let relative = validate_relative_path(relative)?;
    match config {
        StorageConfig::Local { root } => {
            let path = relative
                .split('/')
                .filter(|component| !component.is_empty())
                .fold(root.clone(), |path, component| path.join(component));
            if !path.is_dir() {
                bail!(
                    "{label} does not exist or is not a directory: {}",
                    path.display()
                );
            }
            #[cfg(unix)]
            {
                use std::ffi::CString;
                use std::os::unix::ffi::OsStrExt;

                let native = CString::new(path.as_os_str().as_bytes())
                    .context("storage path contains a NUL byte")?;
                // SAFETY: `native` is a live NUL-terminated path and `access`
                // does not retain the pointer or mutate the filesystem.
                if unsafe { libc::access(native.as_ptr(), libc::W_OK) } != 0 {
                    return Err(std::io::Error::last_os_error()).with_context(|| {
                        format!(
                            "{label} is not writable by the current user: {}",
                            path.display()
                        )
                    });
                }
            }
            Ok(())
        }
        StorageConfig::Ftp {
            host,
            port,
            username_env,
            password_env,
            root,
            timeout_seconds,
            allow_plaintext,
        } => FtpStorage::new(
            host.clone(),
            *port,
            resolve_ftp_username(username_env)?,
            password_env.clone(),
            root.clone(),
            *timeout_seconds,
            *allow_plaintext,
        )?
        .check_writable(&relative, label),
    }
}

/// Uses one FTP session to rename between two configured roots on the same
/// server. This avoids downloading media through the executor when the NAS can
/// perform the move atomically itself. Returns `false` when the endpoints are
/// not the same FTP account and the caller must use verified copy mode.
pub fn try_server_side_rename(
    source: &StorageConfig,
    destination: &StorageConfig,
    from: &str,
    to: &str,
) -> Result<bool> {
    let (
        StorageConfig::Ftp {
            host: source_host,
            port: source_port,
            username_env: source_username_env,
            password_env: source_password_env,
            root: source_root,
            timeout_seconds: source_timeout,
            allow_plaintext: source_plaintext,
        },
        StorageConfig::Ftp {
            host: destination_host,
            port: destination_port,
            username_env: destination_username_env,
            password_env: destination_password_env,
            root: destination_root,
            timeout_seconds: destination_timeout,
            allow_plaintext: destination_plaintext,
        },
    ) = (source, destination)
    else {
        return Ok(false);
    };
    let source_username = resolve_ftp_username(source_username_env)?;
    let destination_username = resolve_ftp_username(destination_username_env)?;
    if source_host != destination_host
        || source_port != destination_port
        || source_username != destination_username
        || source_password_env != destination_password_env
        || source_timeout != destination_timeout
        || source_plaintext != destination_plaintext
    {
        return Ok(false);
    }
    let from = join_ftp_root(source_root, from)?;
    let to = join_ftp_root(destination_root, to)?;
    let storage = FtpStorage::new(
        source_host.clone(),
        *source_port,
        source_username,
        source_password_env.clone(),
        "/".to_owned(),
        *source_timeout,
        *source_plaintext,
    )?;
    match storage.rename(&from, &to) {
        Ok(()) => Ok(true),
        Err(rename_error) => {
            // Synology commonly rejects RNFR/RNTO across shared folders that
            // live on different volumes. Re-check both ends before falling
            // back: a lost final FTP reply must not cause a completed rename
            // to be copied a second time.
            let source_exists = storage.exists(&from)?;
            let destination_exists = storage.exists(&to)?;
            match (source_exists, destination_exists) {
                (true, false) => {
                    eprintln!(
                        "FTP server-side rename is unavailable for {from} -> {to}; using verified streaming copy"
                    );
                    Ok(false)
                }
                (false, true) => Ok(true),
                _ => Err(rename_error).with_context(|| {
                    format!(
                        "FTP rename left an ambiguous state for {from} -> {to}: source_exists={source_exists} destination_exists={destination_exists}"
                    )
                }),
            }
        }
    }
}

/// Streams an FTP source into the configured destination without a full local
/// staging file. Returns `false` for non-FTP sources.
pub fn try_ftp_streaming_copy(
    source: &StorageConfig,
    destination: &dyn Storage,
    from: &str,
    to: &str,
) -> Result<bool> {
    let StorageConfig::Ftp {
        host,
        port,
        username_env,
        password_env,
        root,
        timeout_seconds,
        allow_plaintext,
    } = source
    else {
        return Ok(false);
    };
    FtpStorage::new(
        host.clone(),
        *port,
        resolve_ftp_username(username_env)?,
        password_env.clone(),
        root.clone(),
        *timeout_seconds,
        *allow_plaintext,
    )?
    .stream_to(from, destination, to)?;
    Ok(true)
}

pub(crate) fn resolve_ftp_username(environment_name: &str) -> Result<String> {
    let username = std::env::var(environment_name)
        .with_context(|| format!("missing FTP username environment variable {environment_name}"))?;
    if username.trim().is_empty() {
        bail!("FTP username environment variable {environment_name} is empty");
    }
    Ok(username)
}

fn join_ftp_root(root: &str, relative: &str) -> Result<String> {
    let relative = validate_relative_path(relative)?;
    let root = root.trim_matches('/');
    if root.is_empty() {
        Ok(relative)
    } else if relative.is_empty() {
        validate_relative_path(root)
    } else {
        validate_relative_path(&format!("{root}/{relative}"))
    }
}

/// Validate and normalize a path at the trust boundary.
///
/// Empty string and `.` mean the storage root. All other paths must use POSIX
/// separators and may not contain empty, dot, parent, NUL, or absolute
/// components.
pub fn validate_relative_path(relative: &str) -> Result<String> {
    if relative.is_empty() || relative == "." {
        return Ok(String::new());
    }
    if relative.starts_with('/') {
        bail!("storage path must be relative: {relative:?}");
    }
    if relative.contains('\0') || relative.contains('\\') {
        bail!("storage path contains an invalid separator or NUL: {relative:?}");
    }

    let mut normalized = Vec::new();
    for component in relative.split('/') {
        if component.is_empty() || component == "." || component == ".." {
            bail!("storage path contains an unsafe component: {relative:?}");
        }
        normalized.push(component);
    }
    Ok(normalized.join("/"))
}

pub(crate) fn hash_reader(reader: &mut dyn Read) -> Result<String> {
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 128 * 1024];
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hex::encode(hasher.finalize()))
}
