#!/bin/bash
# DS90 SSH 只读诊断助手：ds90_ssh.sh '<remote command>'
# 密码经 stdin 喂给 sudo -S，不出现在命令行/日志
set -o pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ASK="$DIR/askpass.sh"
[ -x "$ASK" ] || { printf '#!/bin/sh\nprintf "%%s\\n" "$DSH_SECRET_SUBTRANS_FTP_PASSWORD"\n' > "$ASK" && chmod 700 "$ASK"; }
CMD="$1"
Q=$(printf '%q' "$CMD")
printf '%s\n' "$DSH_SECRET_SUBTRANS_FTP_PASSWORD" | \
  SSH_ASKPASS="$ASK" SSH_ASKPASS_REQUIRE=force \
  ssh -p 60022 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o NumberOfPasswordPrompts=1 \
  "$DSH_SECRET_SUBTRANS_FTP_USERNAME"@172.19.60.90 "sudo -S -p '' bash -c $Q"
