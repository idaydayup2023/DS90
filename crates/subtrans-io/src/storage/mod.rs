mod ftp;
mod local;

use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use anyhow::Result;
use sha2::{Digest, Sha256};

pub use ftp::FtpStorage;
pub use local::LocalStorage;
pub use subtrans_core::path::validate_relative_path;

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

pub fn join_ftp_root(root: &str, relative: &str) -> Result<String> {
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

/// Report directories that exist but contain no entries at all.
///
/// A directory entry in `entries` counts as empty when no other entry lives
/// underneath it. Distinguishing three states matters operationally:
///
/// - **empty_dir**: the directory exists but holds nothing (a leftover
///   shell). It must not be read as "the download never finished" — during
///   the 2026-10-27 华语十佳 reconciliation an empty shell nearly caused a
///   duplicate 8.2 GB re-download.
/// - **missing**: the directory does not exist at all; listing it fails
///   loudly (the FTP backend errors on `CWD`), never silently returns
///   nothing.
/// - **partial**: the directory has entries but is missing expected files
///   (for example a release folder without the main video); that judgement
///   belongs to the scan that knows what to expect.
///
/// The whole-tree case (no entries at all) is reported as `(root)`.
///
/// Returns the number of empty directories found; each is printed once as
/// `scan empty_dir path=...` so scans leave an auditable trail instead of
/// silently ignoring empty shells.
pub fn report_empty_dirs(entries: &[FileEntry]) -> usize {
    if entries.is_empty() {
        subtrans_core::report_line!(
            out,
            "scan.empty_dir",
            serde_json::json!({"path": "(root)"}),
            "scan empty_dir path=(root)"
        );
        return 1;
    }
    let mut empty: Vec<&str> = Vec::new();
    for dir in entries.iter().filter(|entry| entry.is_dir) {
        let prefix = format!("{}/", dir.path);
        let has_children = entries.iter().any(|entry| entry.path.starts_with(&prefix));
        if !has_children {
            empty.push(dir.path.as_str());
        }
    }
    for path in &empty {
        subtrans_core::report_line!(
            out,
            "scan.empty_dir",
            serde_json::json!({"path": path}),
            "scan empty_dir path={path}"
        );
    }
    empty.len()
}

#[cfg(test)]
mod tests {
    use super::{FileEntry, report_empty_dirs};

    fn dir(path: &str) -> FileEntry {
        FileEntry {
            path: path.to_string(),
            size: 4096,
            is_dir: true,
            modified: None,
        }
    }

    fn file(path: &str, size: u64) -> FileEntry {
        FileEntry {
            path: path.to_string(),
            size,
            is_dir: false,
            modified: None,
        }
    }

    #[test]
    fn empty_shells_are_reported_once_each() {
        let entries = vec![
            dir("钢的琴 2011"),
            dir("钢的琴 2011/Gang De Qin (2010) [1080p]"),
            file("钢的琴 2011/Gang De Qin (2010) [1080p]/movie.mp4", 10),
            dir("PTU 2003"),
        ];
        assert_eq!(report_empty_dirs(&entries), 1);
    }

    #[test]
    fn directories_holding_an_empty_directory_are_not_empty() {
        let entries = vec![dir("show"), dir("show/inner")];
        assert_eq!(report_empty_dirs(&entries), 1);
    }

    #[test]
    fn a_completely_empty_listing_is_reported_as_root() {
        let entries: Vec<FileEntry> = Vec::new();
        assert_eq!(report_empty_dirs(&entries), 1);
    }

    #[test]
    fn empty_dir_sentence_and_json_event_use_the_same_path() {
        let _human = subtrans_core::report::capture(false);
        assert_eq!(report_empty_dirs(&[]), 1);
        assert_eq!(
            subtrans_core::report::captured(),
            vec![(
                subtrans_core::report::Stream::Stdout,
                "scan empty_dir path=(root)".to_owned()
            )]
        );
        drop(_human);

        let _json = subtrans_core::report::capture(true);
        assert_eq!(report_empty_dirs(&[dir("incoming/show")]), 1);
        let line = &subtrans_core::report::captured()[0].1;
        let value: serde_json::Value = serde_json::from_str(line).unwrap();
        assert_eq!(value["event"], "scan.empty_dir");
        assert_eq!(value["path"], "incoming/show");
        assert!(!line.contains("scan empty_dir path="));
    }

    #[test]
    fn a_fully_populated_tree_reports_nothing() {
        let entries = vec![
            dir("show"),
            dir("show/S01"),
            file("show/S01/e01.mkv", 10),
            file("top.mkv", 10),
        ];
        assert_eq!(report_empty_dirs(&entries), 0);
    }
}
