#!/bin/sh
# Stop - block a claim that a stage gate was met when the state file was never written.
. "$(dirname "$0")/_lib.sh" 2>/dev/null || exit 0
run_cli settle
rc=$?
[ "$rc" = "2" ] && exit 2
exit 0
