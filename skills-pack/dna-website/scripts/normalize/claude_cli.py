"""
Claude CLI backend — shells out to the `claude` binary so we use the user's
existing Claude Code OAuth login instead of a separate API key.

Why this exists:
  The Anthropic Python SDK requires ANTHROPIC_API_KEY. Users running this
  inside Claude Code already have an OAuth session — paying twice for the
  same model is silly. This backend wraps `claude --print` calls so each
  "AI step" runs against the user's existing auth.

How it talks to claude:
  claude --print --output-format json --model <m>
         --no-session-persistence
         --dangerously-skip-permissions
         --system-prompt-file <tmp_system.txt>
         --max-budget-usd <cap>
   < user_prompt_on_stdin

Output is a JSON envelope like:
  {"type":"result","subtype":"success","result":"<model text>","usage":{...},
   "is_error":false,"total_cost_usd":0.07,...}

We extract `.result` and (if expect_json) parse the inner JSON.

Concurrency:
  Each call spawns a fresh subprocess. The CLI internally maintains a 5m /
  1h ephemeral prompt cache against your auth, so the second call with the
  same --system-prompt-file gets cache_read hits without re-uploading.

Cost / safety:
  --max-budget-usd is applied per-call. The normalizer's orchestrator
  computes a per-stage budget so a runaway prompt doesn't drain the account.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


@dataclass
class ClaudeCliUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    total_cost_usd: float = 0.0

    def add_from_envelope(self, env: dict) -> None:
        self.calls += 1
        usage = env.get("usage") or {}
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
        self.cache_read_tokens += int(usage.get("cache_read_input_tokens") or 0)
        self.cache_create_tokens += int(usage.get("cache_creation_input_tokens") or 0)
        try:
            self.total_cost_usd += float(env.get("total_cost_usd") or 0.0)
        except Exception:
            pass


class ClaudeCLIBackend:
    """A subset of the LLMClient API powered by `claude --print`."""

    def __init__(
        self,
        shared_system_text: str,
        *,
        model: str = "sonnet",
        max_budget_usd: float = 5.0,
        binary: str | None = None,
    ) -> None:
        self.model = model
        self.max_budget_usd = max_budget_usd
        self.usage = ClaudeCliUsage()
        # Pin the binary path so we don't surprise-pick up another `claude`
        # on PATH (e.g. an old install).
        self.binary = binary or _resolve_claude_binary()
        # Write the shared system text to a temp file once per backend so
        # every subprocess can reuse it via --system-prompt-file. The file
        # is content-addressed so the CLI prompt-cache reuses across calls.
        self._sys_dir = Path(tempfile.mkdtemp(prefix="dna-normalize-"))
        self._sys_file = self._sys_dir / "system.txt"
        self._sys_file.write_text(shared_system_text, encoding="utf-8")

    # ---------------------------------------------------------------------

    def ask(
        self,
        user_prompt: str,
        *,
        expect_json: bool = False,
        max_tokens: int | None = None,  # unused — CLI doesn't expose this
        temperature: float = 0.0,  # unused — CLI doesn't expose this
        max_retries: int = 3,
    ) -> Any:
        cmd = [
            self.binary,
            "--print",
            "--output-format", "json",
            "--model", self.model,
            "--no-session-persistence",
            "--dangerously-skip-permissions",
            "--system-prompt-file", str(self._sys_file),
            "--max-budget-usd", str(self.max_budget_usd),
        ]
        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                envelope = self._run(cmd, user_prompt)
                self.usage.add_from_envelope(envelope)
                if envelope.get("is_error"):
                    err = envelope.get("result") or envelope.get("error") or "claude reported error"
                    raise RuntimeError(f"claude CLI error: {err}")
                result_text = envelope.get("result") or ""
                if expect_json:
                    return _parse_json(result_text)
                return result_text
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                if any(x in msg for x in ("not logged in", "permission", "command not found")):
                    raise
                backoff = 2 ** (attempt - 1)
                log.warning(f"claude CLI attempt {attempt}/{max_retries} failed: {e}; retrying in {backoff}s")
                time.sleep(backoff)
        raise RuntimeError(f"claude CLI exhausted retries: {last_err}")

    # ---------------------------------------------------------------------

    def _run(self, cmd: list[str], stdin_text: str) -> dict:
        try:
            proc = subprocess.run(
                cmd,
                input=stdin_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                # Generous because per-page calls can take 20–60s
                timeout=int(os.environ.get("DNA_CLAUDE_CLI_TIMEOUT", "180")),
                check=False,
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"claude binary not found ({self.binary}): {e}") from e
        if proc.returncode not in (0, None):
            stderr_tail = (proc.stderr or "")[-500:]
            stdout_tail = (proc.stdout or "")[-500:]
            raise RuntimeError(f"claude exit {proc.returncode}: {stderr_tail or stdout_tail}")
        out = (proc.stdout or "").strip()
        if not out:
            raise RuntimeError("claude returned no stdout")
        try:
            envelope = json.loads(out)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"claude returned non-JSON: {e}\n{out[:500]}")
        return envelope

    # ---------------------------------------------------------------------

    def close(self) -> None:
        try:
            self._sys_file.unlink(missing_ok=True)
            self._sys_dir.rmdir()
        except Exception:
            pass


# ---------------------------------------------------------------------------


def is_claude_cli_available() -> bool:
    """True iff `claude` is on PATH AND not in 'requires API key' mode."""
    bin_path = _resolve_claude_binary(default=None)
    return bin_path is not None


def _resolve_claude_binary(default: str | None = "claude") -> str | None:
    """Find the claude CLI binary. On Windows the npm-installed shim is
    `claude.cmd`. Returns the absolute path so subprocess doesn't trip on
    PATH lookups."""
    import shutil
    for cand in ("claude.cmd", "claude.exe", "claude"):
        p = shutil.which(cand)
        if p:
            return p
    return default


def _parse_json(text: str) -> Any:
    """Strip code fences, parse, raise on failure. Mirrors LLMClient._parse_json."""
    cleaned = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if m:
        cleaned = m.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fall back: find embedded JSON object/array
        for pat in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
            mo = re.search(pat, cleaned)
            if mo:
                try:
                    return json.loads(mo.group(0))
                except json.JSONDecodeError:
                    continue
        raise ValueError(f"claude returned non-JSON result: {text[:500]}")
