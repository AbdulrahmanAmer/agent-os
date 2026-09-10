#!/bin/sh
# PreToolUse - deny an edit the current stage forbids. Silent (exit 0) when there is nothing to say.
. "$(dirname "$0")/_lib.sh" 2>/dev/null || exit 0
run_cli gate
exit 0
