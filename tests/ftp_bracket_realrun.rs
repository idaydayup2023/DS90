//! Real-NAS regression tests for the square-bracket listing defect.
//!
//! Background (measured 2026-10-27 on the production NAS): passing a path
//! that contains `[` or `]` as an `MLSD` argument makes the server answer
//! with a *successful but empty* listing for a directory that exists and
//! has content, so callers mistake it for missing or empty. Listing the
//! same directory from the inside (`CWD` + `MLSD` without an argument)
//! returns the real entries.
//!
//! These tests need the live NAS, so they are `#[ignore]`d and never run in
//! CI. Run them manually:
//!
//! ```sh
//! SUBTRANS_FTP_USERNAME=... SUBTRANS_FTP_PASSWORD=... \
//!   cargo test --test ftp_bracket_realrun -- --ignored --nocapture
//! ```
//!
//! `DS90_FTP_HOST` / `DS90_FTP_PORT` may override the server address.

use subtrans::storage::{FtpStorage, Storage};
use suppaftp::FtpStream;

const HOST: &str = "172.19.60.90";
const PORT: u16 = 10021;

/// Directory, and the number of entries a correct listing returns for it.
/// Pinned from the 2026-10-27 probe and re-probed on 2026-11-17 (`/TV/[A.B.C]`
/// had since lost one entry to library housekeeping; the other two are stable).
/// They grow and shrink with the library, so a failure here means "re-probe the
/// NAS and refresh the pin", not "the defect is back" — the defect itself is
/// pinned by the two tests above it.
const SAMPLES: &[(&str, usize)] = &[
    ("/TV/[ChineseTVs]", 21),
    ("/TV/[A.B.C]", 79),
    ("/TV/[G.H.I.J.K]", 52),
];

fn host() -> String {
    std::env::var("DS90_FTP_HOST").unwrap_or_else(|_| HOST.to_string())
}

fn port() -> u16 {
    std::env::var("DS90_FTP_PORT")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(PORT)
}

fn connect() -> FtpStream {
    let user = std::env::var("SUBTRANS_FTP_USERNAME").expect("SUBTRANS_FTP_USERNAME");
    let password = std::env::var("SUBTRANS_FTP_PASSWORD").expect("SUBTRANS_FTP_PASSWORD");
    let mut ftp = FtpStream::connect(format!("{}:{}", host(), port())).expect("ftp connect");
    ftp.login(&user, &password).expect("ftp login");
    ftp
}

fn storage(root: &str) -> FtpStorage {
    let user = std::env::var("SUBTRANS_FTP_USERNAME").expect("SUBTRANS_FTP_USERNAME");
    FtpStorage::new(
        host(),
        port(),
        user,
        "SUBTRANS_FTP_PASSWORD".to_string(),
        root.to_string(),
        300,
        true,
    )
    .expect("ftp storage")
}

/// The defect itself: a bracketed path passed as an `MLSD` argument comes
/// back empty even though the directory exists and has content.
#[test]
#[ignore = "needs the real NAS"]
fn bracketed_path_as_mlsd_argument_returns_an_empty_listing() {
    for (path, expected) in SAMPLES {
        let mut ftp = connect();
        let listing = ftp.mlsd(Some(path)).expect("mlsd");
        let _ = ftp.quit();
        println!("mlsd(path) {path} -> {} entries", listing.len());
        assert!(
            listing.is_empty(),
            "{path}: expected the known empty-listing defect, got {} entries",
            listing.len()
        );
        assert!(*expected > 0, "{path}: pin must be positive");
    }
}

/// The workaround: entering the directory first returns the real entries.
#[test]
#[ignore = "needs the real NAS"]
fn bracketed_path_listed_from_inside_returns_the_real_entries() {
    for (path, expected) in SAMPLES {
        let mut ftp = connect();
        ftp.cwd(path).expect("cwd into bracketed directory");
        let listing = ftp.mlsd(None).expect("mlsd");
        let _ = ftp.quit();
        println!(
            "cwd+mlsd {path} -> {} entries (pin {expected})",
            listing.len()
        );
        assert_eq!(
            listing.len(),
            *expected,
            "{path}: entry count changed; re-probe the NAS before updating the pin"
        );
    }
}

/// End-to-end: the storage layer the scans use must see these directories.
#[test]
#[ignore = "needs the real NAS"]
fn storage_lists_every_bracketed_sample_non_empty() {
    for (path, _) in SAMPLES {
        let entries = storage(path).list_recursive("").expect("list_recursive");
        println!("storage {path} -> {} entries", entries.len());
        assert!(
            !entries.is_empty(),
            "{path}: storage listed nothing; the CWD fallback regressed"
        );
    }
}

/// One file inside a bracketed directory plus its exact size as reported by
/// `SIZE` (pinned 2026-11-17 against the production NAS, alongside the Pierre
/// `.ai` release).
const METADATA_SAMPLES: &[(&str, u64)] = &[(
    "/TV/[O.P.Q.R]/Pierre.2026.S01.1080p.BluRay.HEVC.x265.5.1.BONE/Pierre.2026.S01E01.1080p.BluRay.HEVC.x265.5.1-BONE.mkv",
    812_598_025,
)];

/// The metadata half of the defect: unlike a missing file, `MLST <bracketed
/// path>` does not fail — it answers `250` with no fact line, and parsing that
/// empty reply is what used to hand callers `size = 0` / `modified = UNIX_EPOCH`
/// for a file that really exists.
#[test]
#[ignore = "needs the real NAS"]
fn raw_mlst_of_a_bracketed_file_carries_no_facts() {
    for (path, _) in METADATA_SAMPLES {
        let mut ftp = connect();
        let reply = ftp.mlst(Some(path));
        let _ = ftp.quit();
        match reply {
            Ok(line) => assert!(
                !(line.contains("type=") || line.contains("size=") || line.contains("modify=")),
                "{path}: MLST unexpectedly returned facts: {line:?}"
            ),
            Err(error) => println!("mlst(path) {path} -> rejected as expected: {error}"),
        }
    }
}

/// The fix: `Storage::metadata` must treat a factless `MLST` reply like a
/// rejected one and fall back to `SIZE` plus the parent-directory listing, so a
/// bracketed file reports its real size and a real modification time instead of
/// `0` / the UNIX epoch (which made `video_identity` content-blind).
#[test]
#[ignore = "needs the real NAS"]
fn storage_metadata_of_bracketed_files_is_not_degenerate() {
    for (path, size) in METADATA_SAMPLES {
        let entry = storage("/")
            .metadata(path.trim_start_matches('/'))
            .expect("metadata")
            .unwrap_or_else(|| panic!("{path}: metadata reported the file as missing"));
        println!(
            "metadata {path} -> size {} modified {:?}",
            entry.size, entry.modified
        );
        assert_eq!(
            entry.size, *size,
            "{path}: size must come from SIZE or the parent listing, not the defaults"
        );
        let modified = entry
            .modified
            .unwrap_or_else(|| panic!("{path}: no modification time reported"));
        assert_ne!(
            modified,
            std::time::UNIX_EPOCH,
            "{path}: modification time degraded to the UNIX epoch; the factless-MLST fallback regressed"
        );
    }
}
