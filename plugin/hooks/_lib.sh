#!/bin/sh
# Shared shim. Every hook fails open: if python is missing, or the CLI errors, the session proceeds.
run_cli() {
  cli="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}/scripts/agent_os.py"
  [ -f "$cli" ] || return 0
  for py in python python3 py; do
    if command -v "$py" >/dev/null 2>&1; then
      "$py" "$cli" "$@"
      return $?
    fi
  done
  return 0
}
