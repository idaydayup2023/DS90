#!/usr/bin/env bash
# version4 check after step E.
# T0: scripts/agent-check.sh
# T1: scripts/agent-check.sh --workspace
# Both run fmt, clippy, and locked tests for the whole workspace.
# #[ignore] tests are not run by T0 or T1.
# T2: scripts/agent-check.sh --live
# T2 requires SUBTRANS_LIVE=1 and FTP host, port, account, and sample
# paths from the environment. Missing variables fail closed. There is no
# built-in host or sample library.
# T0, T1, and T2 do not run extra/. That directory holds DownloadStation,
# SSH, and external-site scripts. Their live entry points are not verification.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

tier="t0"
case "${1:-}" in
  "")
    tier="t0"
    ;;
  --workspace)
    tier="t1"
    ;;
  --live)
    tier="t2"
    missing=()
    if [[ "${SUBTRANS_LIVE:-}" != "1" ]]; then
      missing+=("SUBTRANS_LIVE=1")
    fi
    for name in SUBTRANS_FTP_HOST SUBTRANS_FTP_PORT SUBTRANS_FTP_USERNAME SUBTRANS_FTP_PASSWORD SUBTRANS_FTP_SAMPLES; do
      if [[ -z "${!name:-}" ]]; then
        missing+=("$name")
      fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
      printf '%s\n' "{\"ok\":false,\"tier\":\"t2\",\"failed\":1,\"reason\":\"missing ${missing[*]}; refusing to contact a default host or sample library\"}" >&2
      exit 2
    fi
    on_err() {
      local status=$?
      trap - ERR
      printf '%s\n' "{\"ok\":false,\"tier\":\"${tier}\",\"failed\":1,\"exit\":${status}}" >&2
      exit "$status"
    }
    trap on_err ERR
    cargo test --locked --workspace --test ftp_bracket_realrun -- --ignored --nocapture
    trap - ERR
    printf '%s\n' "{\"ok\":true,\"tier\":\"t2\",\"failed\":0}"
    exit 0
    ;;
  *)
    printf 'usage: scripts/agent-check.sh [--workspace|--live]\n' >&2
    exit 2
    ;;
esac

if [[ $# -gt 1 ]]; then
  printf 'usage: scripts/agent-check.sh [--workspace|--live]\n' >&2
  exit 2
fi

on_err() {
  local status=$?
  trap - ERR
  printf '%s\n' "{\"ok\":false,\"tier\":\"${tier}\",\"failed\":1,\"exit\":${status}}" >&2
  exit "$status"
}
trap on_err ERR

cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
# cargo test does not execute #[ignore] tests unless --ignored is passed.
cargo test --locked --workspace --all-targets

trap - ERR
printf '%s\n' "{\"ok\":true,\"tier\":\"${tier}\",\"failed\":0}"
