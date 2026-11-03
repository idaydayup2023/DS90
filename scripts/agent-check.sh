#!/usr/bin/env bash
# version4 step A check. Single crate. No product-behavior change.
# T0: scripts/agent-check.sh
# T1: scripts/agent-check.sh --workspace
# Both run fmt, clippy, and locked tests. With one crate they are the same
# commands; --workspace is the CI entry. #[ignore] tests are not run.
# --live is refused: step A does not contact a NAS or run tools/.
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
    printf '%s\n' '{"ok":false,"tier":"t2","failed":1,"reason":"live tier is not enabled in step A; this script does not contact a NAS"}' >&2
    exit 2
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
cargo clippy --locked --all-targets -- -D warnings
# cargo test does not execute #[ignore] tests unless --ignored is passed.
cargo test --locked --all-targets

trap - ERR
printf '%s\n' "{\"ok\":true,\"tier\":\"${tier}\",\"failed\":0}"
