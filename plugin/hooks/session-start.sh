#!/bin/sh
# SessionStart - print the layered context for the CURRENT stage only. stdout joins the context.
. "$(dirname "$0")/_lib.sh" 2>/dev/null || exit 0
run_cli context
exit 0
