mod ftp;
mod local;

use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use anyhow::{Result, bail};
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
            username,
            password_env,
            root,
            timeout_seconds,
            allow_plaintext,
        } => Ok(Box::new(FtpStorage::new(
            host.clone(),
            *port,
            username.clone(),
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
            username,
            password_env,
            root,
            timeout_seconds,
            allow_plaintext,
        } => FtpStorage::new(
            host.clone(),
            *port,
            username.clone(),
            password_env.clone(),
            root.clone(),
            *timeout_seconds,
            *allow_plaintext,
        )?
        .check_connection(),
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
            username: source_username,
            password_env: source_password_env,
            root: source_root,
            timeout_seconds: source_timeout,
            allow_plaintext: source_plaintext,
        },
        StorageConfig::Ftp {
            host: destination_host,
            port: destination_port,
            username: destination_username,
            password_env: destination_password_env,
            root: destination_root,
            timeout_seconds: destination_timeout,
            allow_plaintext: destination_plaintext,
        },
    ) = (source, destination)
    else {
        return Ok(false);
    };
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
    FtpStorage::new(
        source_host.clone(),
        *source_port,
        source_username.clone(),
        source_password_env.clone(),
        "/".to_owned(),
        *source_timeout,
        *source_plaintext,
    )?
    .rename(&from, &to)?;
    Ok(true)
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
