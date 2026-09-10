"""
LLM client wrapper for the normalizer.

Three backends, picked in this priority order:

  1. MOCK   — env DNA_NORMALIZE_MOCK_LLM=1. Empty replies → deterministic
              fallbacks fire. Tests and dry-runs use this.
  2. CLI    — `claude` is on PATH. Spawns `claude --print` per call so we
              use the existing Claude Code OAuth login. No API key needed.
              This is the default when running inside a Claude Code session.
  3. SDK    — env ANTHROPIC_API_KEY set. Uses the anthropic Python SDK.
              Pay-per-token billing on a separate API key.

You can force a specific backend with DNA_NORMALIZE_LLM_BACKEND=mock|cli|sdk.

Env vars consumed:
  ANTHROPIC_API_KEY         - if set, enables the SDK backend
  DNA_LLM_MODEL             - model id; default 'claude-sonnet-4-6' (SDK) /
                              'sonnet' (CLI)
  DNA_NORMALIZE_MOCK_LLM=1  - forces mock backend
  DNA_NORMALIZE_LLM_BACKEND - explicit backend override (mock|cli|sdk)
  DNA_LLM_MAX_BUDGET_USD    - per-call cost cap for the CLI backend (default 5)
  DNA_CLAUDE_CLI_TIMEOUT    - per-call subprocess timeout in seconds (default 180)

Usage:
   client = LLMClient(shared_context=ctx_blocks)
   reply = client.ask(prompt, expect_json=True)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


DEFAULT_MODEL = os.environ.get("DNA_LLM_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = int(os.environ.get("DNA_LLM_MAX_TOKENS", "8000"))


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_create_tokens: int = 0
    cache_read_tokens: int = 0
    calls: int = 0

    def add(self, other: "LLMUsage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_create_tokens += other.cache_create_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.calls += other.calls


class LLMClient:
    """
    Unified client. Internally delegates to one of:
      * MOCK   — empty replies, drives deterministic fallbacks
      * CLI    — subprocess to `claude --print` (uses OAuth)
      * SDK    — anthropic Python SDK (uses ANTHROPIC_API_KEY)

    Public surface: `ask(user_prompt, expect_json=...)`.
    """

    def __init__(
        self,
        shared_context: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.max_tokens = max_tokens
        self.usage = LLMUsage()

        # Resolve backend
        backend_override = (os.environ.get("DNA_NORMALIZE_LLM_BACKEND") or "").lower().strip()
        if os.environ.get("DNA_NORMALIZE_MOCK_LLM") == "1" or backend_override == "mock":
            self.backend = "mock"
        elif backend_override == "sdk":
            self.backend = "sdk"
        elif backend_override == "cli":
            self.backend = "cli"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            self.backend = "sdk"
        else:
            # Try the CLI; fall back to mock if not available
            try:
                from .claude_cli import is_claude_cli_available
                self.backend = "cli" if is_claude_cli_available() else "mock"
            except Exception:
                self.backend = "mock"

        # Keep .mock for backward compat with code/tests that check it
        self.mock = self.backend == "mock"

        # Model: if not overridden, pick a sensible default per backend
        if model:
            self.model = model
        elif self.backend == "cli":
            self.model = os.environ.get("DNA_LLM_MODEL", "sonnet")
        else:
            self.model = os.environ.get("DNA_LLM_MODEL", DEFAULT_MODEL)

        # System blocks: SDK uses native cache_control content blocks.
        # CLI uses a flattened --system-prompt-file (cache hits handled
        # internally by the CLI).
        self._shared_system_blocks: list[dict[str, Any]] = []
        self._shared_system_text = ""
        if shared_context:
            for block in shared_context:
                b = dict(block)
                b.setdefault("cache_control", {"type": "ephemeral"})
                self._shared_system_blocks.append(b)
            self._shared_system_text = "\n\n".join(
                (b.get("text") or "") for b in shared_context if isinstance(b, dict)
            )

        # Initialise the chosen backend
        self._sdk_client = None
        self._cli_client = None
        if self.backend == "sdk":
            try:
                import anthropic  # noqa: F401
                self._sdk_client = anthropic.Anthropic()
            except Exception as e:
                log.warning(f"anthropic SDK init failed ({e}); falling back to CLI")
                self.backend = "cli"
        if self.backend == "cli":
            try:
                from .claude_cli import ClaudeCLIBackend
                max_budget = float(os.environ.get("DNA_LLM_MAX_BUDGET_USD", "5"))
                self._cli_client = ClaudeCLIBackend(
                    self._shared_system_text or "You are a helper. Reply with strict JSON only when asked.",
                    model=self.model,
                    max_budget_usd=max_budget,
                )
            except Exception as e:
                log.warning(f"claude CLI init failed ({e}); falling back to mock")
                self.backend = "mock"
        self.mock = self.backend == "mock"

    # ---------------------------------------------------------------------

    def ask(
        self,
        user_prompt: str,
        *,
        system_extra: str | None = None,
        expect_json: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        max_retries: int = 3,
    ) -> Any:
        """
        Send a single-turn request and return the assistant's text reply
        (parsed as JSON when `expect_json=True`). Dispatches to whichever
        backend was chosen at init time.
        """
        if self.backend == "mock":
            return self._mock_response(user_prompt, expect_json)

        if self.backend == "cli":
            assert self._cli_client is not None
            # CLI doesn't support per-call system_extra; fold it into the prompt
            full_prompt = user_prompt
            if system_extra:
                full_prompt = f"# Additional system instructions:\n{system_extra}\n\n# Task:\n{user_prompt}"
            try:
                result = self._cli_client.ask(
                    full_prompt,
                    expect_json=expect_json,
                    max_retries=max_retries,
                )
                # Fold CLI usage into LLMUsage so callers see one number
                cu = self._cli_client.usage
                self.usage.calls = cu.calls
                self.usage.input_tokens = cu.input_tokens
                self.usage.output_tokens = cu.output_tokens
                self.usage.cache_read_tokens = cu.cache_read_tokens
                self.usage.cache_create_tokens = cu.cache_create_tokens
                return result
            except Exception as e:
                raise

        # SDK backend
        assert self._sdk_client is not None
        messages = [{"role": "user", "content": user_prompt}]
        system = list(self._shared_system_blocks)
        if system_extra:
            system.append({"type": "text", "text": system_extra})

        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = self._sdk_client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens or self.max_tokens,
                    temperature=temperature,
                    system=system if system else None,
                    messages=messages,
                )
                self._record_usage(resp)
                text = self._extract_text(resp)
                if expect_json:
                    return self._parse_json(text)
                return text
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                if any(x in msg for x in ("invalid api key", "permission_denied", "not found")):
                    raise
                backoff = 2 ** (attempt - 1)
                log.warning(f"LLM attempt {attempt}/{max_retries} failed: {e}; retrying in {backoff}s")
                time.sleep(backoff)
        raise RuntimeError(f"LLM exhausted retries: {last_err}")

    def close(self) -> None:
        try:
            if self._cli_client:
                self._cli_client.close()
        except Exception:
            pass

    # ---------------------------------------------------------------------

    def _record_usage(self, resp: Any) -> None:
        try:
            u = resp.usage
            self.usage.calls += 1
            self.usage.input_tokens += getattr(u, "input_tokens", 0) or 0
            self.usage.output_tokens += getattr(u, "output_tokens", 0) or 0
            self.usage.cache_create_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
            self.usage.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
        except Exception:
            pass

    def _extract_text(self, resp: Any) -> str:
        parts: list[str] = []
        for block in (resp.content or []):
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts).strip()

    def _parse_json(self, text: str) -> Any:
        """Strip ```json fences, parse, raise on failure."""
        cleaned = text.strip()
        m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            # Sometimes the model adds a leading "Here's the JSON:" preamble.
            # Try to find a top-level JSON object or array.
            obj_match = re.search(r"\{[\s\S]*\}", cleaned)
            arr_match = re.search(r"\[[\s\S]*\]", cleaned)
            for cand in (obj_match, arr_match):
                if cand:
                    try:
                        return json.loads(cand.group(0))
                    except json.JSONDecodeError:
                        continue
            raise ValueError(f"LLM returned invalid JSON: {e}\nRaw text:\n{text[:1000]}")

    # ---------------------------------------------------------------------

    def _mock_response(self, user_prompt: str, expect_json: bool) -> Any:
        """Mock mode returns EMPTY structured responses so the downstream
        deterministic fallbacks fire. That way `--mock` produces a
        meaningful, browsable project without burning API tokens. Tests
        that want a non-empty stub can monkeypatch this method.
        """
        self.usage.calls += 1
        lower = user_prompt.lower()
        if "wire_interactions" in lower or "runtime.js" in lower or "rewire" in lower or "vanilla javascript" in lower:
            return {"js": "", "css": "", "patterns_wired": [], "patterns_skipped_by_policy": [], "notes": ["mock — fallback runtime will fire"]}
        if "rewrite one page" in lower or "rewrite the page" in lower or "clean, semantic html5" in lower or "generate the html" in lower:
            return {"html": "", "page_css": "", "page_js": "", "notes": ["mock — deterministic fallback will fire"], "todos": []}
        if "consolidate css" in lower or "css cleanup" in lower or "produce a clean base.css" in lower:
            return {"css": "", "kept_selectors": 0, "stripped_categories": [], "notes": ["mock — fallback base/components.css will fire"]}
        if expect_json:
            return {"mock": True, "received_chars": len(user_prompt)}
        return "[mock response]"
