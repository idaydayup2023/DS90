//! Real-NAS regression for the square-bracket listing defect.
//!
//! These tests are `#[ignore]`d. T0 and T1 never run them. T2 runs them only
//! when every variable below is set. There is no built-in host, port, account,
//! or sample library.

use std::env;

use subtrans_io::storage::{FtpStorage, Storage};
use suppaftp::FtpStream;

fn require_var(name: &str) -> String {
    match env::var(name) {
        Ok(value) if !value.trim().is_empty() => value,
        Ok(_) => {
            panic!("{name} is empty; T2 does not fall back to a built-in host or sample library")
        }
        Err(_) => {
            panic!("missing {name}; T2 does not fall back to a built-in host or sample library")
        }
    }
}

fn host() -> String {
    require_var("SUBTRANS_FTP_HOST")
}

fn port() -> u16 {
    let raw = require_var("SUBTRANS_FTP_PORT");
    raw.parse().unwrap_or_else(|_| {
        panic!("SUBTRANS_FTP_PORT={raw} is not a port; T2 does not fall back to a built-in port")
    })
}

/// `path=count` entries separated by `;`. The path may contain `=`; the count
/// is the final field.
fn samples() -> Vec<(String, usize)> {
    let raw = require_var("SUBTRANS_FTP_SAMPLES");
    let mut samples = Vec::new();
    for item in raw.split(';') {
        let item = item.trim();
        if item.is_empty() {
            continue;
        }
        let (path, count) = item.rsplit_once('=').unwrap_or_else(|| {
            panic!("SUBTRANS_FTP_SAMPLES entries must be path=count separated by ';'; got {item}")
        });
        let count: usize = count
            .trim()
            .parse()
            .unwrap_or_else(|_| panic!("SUBTRANS_FTP_SAMPLES count is not an integer in {item}"));
        if path.trim().is_empty() || count == 0 {
            panic!("SUBTRANS_FTP_SAMPLES entry must have a path and a positive count: {item}");
        }
        samples.push((path.trim().to_string(), count));
    }
    if samples.is_empty() {
        panic!("SUBTRANS_FTP_SAMPLES is empty; T2 does not fall back to a built-in sample library");
    }
    samples
}

fn connect() -> FtpStream {
    let user = require_var("SUBTRANS_FTP_USERNAME");
    let password = require_var("SUBTRANS_FTP_PASSWORD");
    let mut ftp = FtpStream::connect(format!("{}:{}", host(), port())).expect("ftp connect");
    ftp.login(&user, &password).expect("ftp login");
    ftp
}

fn storage(root: &str) -> FtpStorage {
    let user = require_var("SUBTRANS_FTP_USERNAME");
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
    for (path, expected) in samples() {
        let mut ftp = connect();
        let listing = ftp.mlsd(Some(&path)).expect("mlsd");
        let _ = ftp.quit();
        println!("mlsd(path) {path} -> {} entries", listing.len());
        assert!(
            listing.is_empty(),
            "{path}: expected the known empty-listing defect, got {} entries",
            listing.len()
        );
        assert!(expected > 0, "{path}: pin must be positive");
    }
}

/// The workaround: entering the directory first returns the real entries.
#[test]
#[ignore = "needs the real NAS"]
fn bracketed_path_listed_from_inside_returns_the_real_entries() {
    for (path, expected) in samples() {
        let mut ftp = connect();
        ftp.cwd(&path).expect("cwd into bracketed directory");
        let listing = ftp.mlsd(None).expect("mlsd");
        let _ = ftp.quit();
        println!(
            "cwd+mlsd {path} -> {} entries (pin {expected})",
            listing.len()
        );
        assert_eq!(
            listing.len(),
            expected,
            "{path}: entry count changed; re-probe the NAS before updating the pin"
        );
    }
}

/// End-to-end: the storage layer the scans use must see these directories.
#[test]
#[ignore = "needs the real NAS"]
fn storage_lists_every_bracketed_sample_non_empty() {
    for (path, _) in samples() {
        let entries = storage(&path).list_recursive("").expect("list_recursive");
        println!("storage {path} -> {} entries", entries.len());
        assert!(
            !entries.is_empty(),
            "{path}: storage listed nothing; the CWD fallback regressed"
        );
    }
}
