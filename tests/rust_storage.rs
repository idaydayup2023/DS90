use std::io::{Cursor, Read};

use subtrans::storage::{LocalStorage, Storage, validate_relative_path};
use tempfile::tempdir;

#[test]
fn rejects_unsafe_posix_paths() {
    for path in [
        "/absolute",
        "../escape",
        "a/../escape",
        "a//b",
        "a/./b",
        "a\\b",
    ] {
        assert!(validate_relative_path(path).is_err(), "accepted {path:?}");
    }
    assert_eq!(validate_relative_path("").unwrap(), "");
    assert_eq!(validate_relative_path(".").unwrap(), "");
    assert_eq!(
        validate_relative_path("folder/file.srt").unwrap(),
        "folder/file.srt"
    );
}

#[cfg(unix)]
#[test]
fn rejects_symbolic_link_escape() {
    use std::os::unix::fs::symlink;

    let root = tempdir().unwrap();
    let outside = tempdir().unwrap();
    std::fs::write(outside.path().join("secret"), b"secret").unwrap();
    symlink(outside.path(), root.path().join("link")).unwrap();
    let storage = LocalStorage::new(root.path()).unwrap();

    assert!(storage.read("link/secret").is_err());
    assert!(storage.list_recursive("").is_err());
    assert!(storage.create_dir_all("link/new").is_err());
}

#[test]
fn atomic_upload_replaces_file_without_leaving_part_file() {
    let root = tempdir().unwrap();
    let storage = LocalStorage::new(root.path()).unwrap();
    storage.create_dir_all("subs").unwrap();
    std::fs::write(root.path().join("subs/movie.srt"), b"old").unwrap();

    storage
        .upload_atomic("subs/movie.srt", &mut Cursor::new(b"new subtitle"))
        .unwrap();

    assert_eq!(storage.read("subs/movie.srt").unwrap(), b"new subtitle");
    let names: Vec<_> = std::fs::read_dir(root.path().join("subs"))
        .unwrap()
        .map(|entry| entry.unwrap().file_name())
        .collect();
    assert_eq!(names.len(), 1);
}

#[test]
fn failed_atomic_upload_preserves_old_file() {
    struct BrokenReader(bool);
    impl Read for BrokenReader {
        fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
            if self.0 {
                return Err(std::io::Error::other("injected read failure"));
            }
            self.0 = true;
            buffer[..4].copy_from_slice(b"new ");
            Ok(4)
        }
    }

    let root = tempdir().unwrap();
    let storage = LocalStorage::new(root.path()).unwrap();
    std::fs::write(root.path().join("movie.srt"), b"old subtitle").unwrap();

    assert!(
        storage
            .upload_atomic("movie.srt", &mut BrokenReader(false))
            .is_err()
    );
    assert_eq!(storage.read("movie.srt").unwrap(), b"old subtitle");
    assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 1);
}

#[test]
fn recursively_scans_and_reports_metadata() {
    let root = tempdir().unwrap();
    let storage = LocalStorage::new(root.path()).unwrap();
    storage.create_dir_all("show/Season 01").unwrap();
    std::fs::write(root.path().join("show/Season 01/Episode 01.mkv"), b"video").unwrap();
    std::fs::write(
        root.path().join("show/Season 01/Episode 01.srt"),
        b"subtitle",
    )
    .unwrap();

    let entries = storage.list_recursive("show").unwrap();
    let paths: Vec<_> = entries.iter().map(|entry| entry.path.as_str()).collect();
    assert_eq!(
        paths,
        [
            "show/Season 01",
            "show/Season 01/Episode 01.mkv",
            "show/Season 01/Episode 01.srt"
        ]
    );
    assert_eq!(
        storage
            .metadata("show/Season 01/Episode 01.mkv")
            .unwrap()
            .unwrap()
            .size,
        5
    );
    assert!(!storage.exists("missing").unwrap());
}

#[test]
fn hashes_files_as_a_stream() {
    let root = tempdir().unwrap();
    let storage = LocalStorage::new(root.path()).unwrap();
    std::fs::write(root.path().join("data.bin"), b"abc").unwrap();

    assert_eq!(
        storage.sha256("data.bin").unwrap(),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
}
