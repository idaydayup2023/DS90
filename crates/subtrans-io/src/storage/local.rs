use std::fs::{self, File, OpenOptions};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use anyhow::{Context, Result, bail};
use walkdir::WalkDir;

use super::{FileEntry, Storage, hash_reader, validate_relative_path};

static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[derive(Debug)]
pub struct LocalStorage {
    root: PathBuf,
}

impl LocalStorage {
    pub fn new(root: impl AsRef<Path>) -> Result<Self> {
        let requested = root.as_ref();
        if !requested.is_dir() {
            bail!(
                "storage root does not exist or is not a directory: {}",
                requested.display()
            );
        }
        let root = requested
            .canonicalize()
            .with_context(|| format!("failed to resolve storage root {}", requested.display()))?;
        if !root.is_dir() {
            bail!("storage root is not a directory: {}", root.display());
        }
        Ok(Self { root })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Resolve without following a symlink below the configured root. Rejecting
    /// every symlink is deliberate: it makes containment independent of whether
    /// the link target changes between validation and use.
    fn resolve(&self, relative: &str, allow_missing_leaf: bool) -> Result<PathBuf> {
        let normalized = validate_relative_path(relative)?;
        if normalized.is_empty() {
            return Ok(self.root.clone());
        }

        let mut current = self.root.clone();
        let component_count = normalized.split('/').count();
        for (index, component) in normalized.split('/').enumerate() {
            current.push(component);
            match fs::symlink_metadata(&current) {
                Ok(metadata) => {
                    if metadata.file_type().is_symlink() {
                        bail!("storage path traverses a symbolic link: {relative:?}");
                    }
                    if index + 1 < component_count && !metadata.is_dir() {
                        bail!("storage path has a non-directory parent: {relative:?}");
                    }
                }
                Err(error)
                    if error.kind() == std::io::ErrorKind::NotFound
                        && allow_missing_leaf
                        && index + 1 == component_count => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    return Err(error)
                        .with_context(|| format!("storage path does not exist: {relative:?}"));
                }
                Err(error) => {
                    return Err(error).with_context(|| {
                        format!("failed to inspect storage path {}", current.display())
                    });
                }
            }
        }
        Ok(current)
    }

    fn ensure_safe_parent(&self, relative: &str) -> Result<PathBuf> {
        let normalized = validate_relative_path(relative)?;
        if normalized.is_empty() {
            bail!("operation requires a non-root storage path");
        }
        let mut components: Vec<&str> = normalized.split('/').collect();
        components.pop();
        let parent = components.join("/");
        if parent.is_empty() {
            Ok(self.root.clone())
        } else {
            self.resolve(&parent, false)
        }
    }

    fn entry(&self, relative: String, path: &Path) -> Result<FileEntry> {
        let metadata = fs::symlink_metadata(path)
            .with_context(|| format!("failed to inspect {}", path.display()))?;
        if metadata.file_type().is_symlink() {
            bail!(
                "symbolic links are not allowed in storage: {}",
                path.display()
            );
        }
        Ok(FileEntry {
            path: relative,
            size: metadata.len(),
            is_dir: metadata.is_dir(),
            modified: metadata.modified().ok(),
        })
    }

    fn sync_directory(path: &Path) -> Result<()> {
        File::open(path)
            .and_then(|directory| directory.sync_all())
            .with_context(|| format!("failed to sync directory {}", path.display()))
    }
}

impl Storage for LocalStorage {
    fn list_recursive(&self, relative: &str) -> Result<Vec<FileEntry>> {
        let normalized = validate_relative_path(relative)?;
        let base = self.resolve(&normalized, false)?;
        if !base.is_dir() {
            bail!("cannot recursively list a file: {relative:?}");
        }

        let mut entries = Vec::new();
        for result in WalkDir::new(&base).follow_links(false).min_depth(1) {
            let item = result.with_context(|| format!("failed to scan {}", base.display()))?;
            if item.file_type().is_symlink() {
                bail!(
                    "symbolic links are not allowed in storage: {}",
                    item.path().display()
                );
            }
            let relative_path = item
                .path()
                .strip_prefix(&self.root)
                .context("scanner returned a path outside the storage root")?;
            let rel = relative_path
                .iter()
                .map(|part| part.to_str())
                .collect::<Option<Vec<_>>>()
                .with_context(|| {
                    format!(
                        "storage path is not valid UTF-8 and cannot be represented as POSIX: {}",
                        relative_path.display()
                    )
                })?
                .join("/");
            entries.push(self.entry(rel, item.path())?);
        }
        entries.sort_by(|a, b| a.path.cmp(&b.path));
        Ok(entries)
    }

    fn exists(&self, relative: &str) -> Result<bool> {
        let normalized = validate_relative_path(relative)?;
        match self.resolve(&normalized, false) {
            Ok(_) => Ok(true),
            Err(error) if is_not_found(&error) => Ok(false),
            Err(error) => Err(error),
        }
    }

    fn metadata(&self, relative: &str) -> Result<Option<FileEntry>> {
        let normalized = validate_relative_path(relative)?;
        match self.resolve(&normalized, false) {
            Ok(path) => Ok(Some(self.entry(normalized, &path)?)),
            Err(error) if is_not_found(&error) => Ok(None),
            Err(error) => Err(error),
        }
    }

    fn read(&self, relative: &str) -> Result<Vec<u8>> {
        let path = self.resolve(relative, false)?;
        fs::read(&path).with_context(|| format!("failed to read {}", path.display()))
    }

    fn download(&self, relative: &str, destination: &Path) -> Result<()> {
        let source = self.resolve(relative, false)?;
        let mut reader = BufReader::new(
            File::open(&source).with_context(|| format!("failed to open {}", source.display()))?,
        );
        let mut writer = BufWriter::new(
            File::create(destination)
                .with_context(|| format!("failed to create {}", destination.display()))?,
        );
        std::io::copy(&mut reader, &mut writer)?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }

    fn upload_atomic(&self, relative: &str, source: &mut dyn Read) -> Result<()> {
        let normalized = validate_relative_path(relative)?;
        let destination = self.resolve(&normalized, true)?;
        let parent = self.ensure_safe_parent(&normalized)?;
        let file_name = destination
            .file_name()
            .and_then(|name| name.to_str())
            .context("destination file name is not valid UTF-8")?;
        let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let temporary = parent.join(format!(
            ".{file_name}.subtrans-part-{}-{sequence}",
            std::process::id()
        ));

        let result = (|| -> Result<()> {
            let file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temporary)
                .with_context(|| format!("failed to create {}", temporary.display()))?;
            let mut writer = BufWriter::new(file);
            std::io::copy(source, &mut writer)?;
            writer.flush()?;
            writer.get_ref().sync_all()?;
            drop(writer);
            fs::rename(&temporary, &destination).with_context(|| {
                format!(
                    "failed to atomically promote {} to {}",
                    temporary.display(),
                    destination.display()
                )
            })?;
            Self::sync_directory(&parent)?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        result
    }

    fn create_dir_all(&self, relative: &str) -> Result<()> {
        let normalized = validate_relative_path(relative)?;
        let mut current = self.root.clone();
        for component in normalized.split('/').filter(|part| !part.is_empty()) {
            current.push(component);
            match fs::symlink_metadata(&current) {
                Ok(metadata) if metadata.file_type().is_symlink() => {
                    bail!("storage path traverses a symbolic link: {relative:?}")
                }
                Ok(metadata) if !metadata.is_dir() => {
                    bail!("storage directory path contains a file: {relative:?}")
                }
                Ok(_) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    fs::create_dir(&current).with_context(|| {
                        format!("failed to create storage directory {}", current.display())
                    })?;
                    Self::sync_directory(current.parent().unwrap_or(&self.root))?;
                }
                Err(error) => return Err(error.into()),
            }
        }
        Ok(())
    }

    fn rename(&self, from: &str, to: &str) -> Result<()> {
        if validate_relative_path(from)?.is_empty() || validate_relative_path(to)?.is_empty() {
            bail!("refusing to rename the storage root");
        }
        let source = self.resolve(from, false)?;
        let destination = self.resolve(to, true)?;
        let destination_parent = self.ensure_safe_parent(to)?;
        fs::rename(&source, &destination).with_context(|| {
            format!(
                "failed to rename {} to {}",
                source.display(),
                destination.display()
            )
        })?;
        Self::sync_directory(&destination_parent)?;
        if let Some(source_parent) = source.parent()
            && source_parent != destination_parent
        {
            Self::sync_directory(source_parent)?;
        }
        Ok(())
    }

    fn remove(&self, relative: &str) -> Result<()> {
        let normalized = validate_relative_path(relative)?;
        if normalized.is_empty() {
            bail!("refusing to remove storage root");
        }
        let path = self.resolve(&normalized, false)?;
        let metadata = fs::symlink_metadata(&path)?;
        if metadata.is_dir() {
            fs::remove_dir(&path).with_context(|| {
                format!(
                    "failed to remove empty storage directory {}",
                    path.display()
                )
            })?;
        } else {
            fs::remove_file(&path)
                .with_context(|| format!("failed to remove storage file {}", path.display()))?;
        }
        if let Some(parent) = path.parent() {
            Self::sync_directory(parent)?;
        }
        Ok(())
    }

    fn sha256(&self, relative: &str) -> Result<String> {
        let path = self.resolve(relative, false)?;
        let mut reader = BufReader::new(
            File::open(&path).with_context(|| format!("failed to open {}", path.display()))?,
        );
        hash_reader(&mut reader)
    }

    fn local_path(&self, relative: &str) -> Result<Option<PathBuf>> {
        Ok(Some(self.resolve(relative, false)?))
    }

    fn local_path_for_write(&self, relative: &str) -> Result<Option<PathBuf>> {
        let normalized = validate_relative_path(relative)?;
        self.ensure_safe_parent(&normalized)?;
        Ok(Some(self.resolve(&normalized, true)?))
    }
}

fn is_not_found(error: &anyhow::Error) -> bool {
    error
        .chain()
        .filter_map(|cause| cause.downcast_ref::<std::io::Error>())
        .any(|error| error.kind() == std::io::ErrorKind::NotFound)
}
