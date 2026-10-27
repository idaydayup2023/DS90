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
/// Pinned from the 2026-10-27 probe; they only grow when content is added.
const SAMPLES: &[(&str, usize)] = &[
    ("/TV/[ChineseTVs]", 21),
    ("/TV/[A.B.C]", 80),
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
