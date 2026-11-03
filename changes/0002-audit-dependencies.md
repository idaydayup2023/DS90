### Fixed

- 修复 `cargo audit` 报告的依赖安全问题：升级 `quinn-proto`、`rustls`、`rustls-webpki`、`webpki-root-certs`、`tokio` 至各自兼容的已修复版本（含 tokio `AsyncFd` I/O 安全公告 RUSTSEC-2026-0386，程序未直接使用该 API，仍一并升级消除）。
