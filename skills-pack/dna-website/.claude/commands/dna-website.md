---
description: Extract a website's complete design DNA into a local inspectable package
argument-hint: <url> [--auth <profile>] [--depth N] [--max-pages N] [...]
allowed-tools: Bash(python:*), Bash(npm:*), Bash(node:*), Read, Write, Edit, Glob
---

# /dna-website

Run the dna-website pipeline against `$ARGUMENTS`.

## What this command does

1. Parses the URL and any flags from `$ARGUMENTS`.
2. If `--auth <profile>` is present, loads the credentials from `.dna-website.env` for that profile. **Never** echo credentials.
3. Runs preflight checks. If the URL is in a blocked category or robots.txt forbids crawling, refuses unless overridden.
4. Runs the 8-stage pipeline (see `SPEC.md`).
5. Reports the output directory and how to launch the inspector.

## Argument handling

- `$ARGUMENTS` is the full string after `/dna-website`. Parse manually.
- The URL is the first positional argument (must start with `http://` or `https://`).
- Flags follow. See `SKILL.md` for the full grammar.

## Steps to take

1. Validate that the user is in the dna-website project root (`pyproject.toml` + `scripts/run.py` should exist). If not, ask them to `cd` there.
2. Run `python -m scripts.doctor` first if this is the user's first invocation in this shell session. Skip if recently verified.
3. Run `python -m scripts.run $ARGUMENTS`.
4. When the pipeline completes, report:
   - The output directory path
   - The number of pages captured
   - Any warnings from the manifest
   - The command to launch the inspector: `python -m scripts.serve <output-dir>`

## Hard rules

- **Never include credentials in any tool call or any message.** The user keeps them in `.dna-website.env`.
- **Never run with `--ignore-robots` without first showing the user what robots.txt says** and getting explicit "yes proceed" in chat.
- **Never run against a blocked-category domain without `--i-own-this-site`** — the preflight will reject anyway, but you should also confirm in chat before invoking.
- If the user names a URL that looks like a personal site (someone's name, a small blog), ask them to confirm they have permission to inspect it.
- If the pipeline fails partway, point them at `references/troubleshooting.md` and at `<output-dir>/run.log`.

## Examples

```
/dna-website https://example.com
/dna-website https://example.com --depth 2 --max-pages 20
/dna-website https://app.example.com --auth myteam --rate-limit 1
/dna-website https://example.com --resume   # continues a previous run
```

## Where to look when something goes wrong

- `<output-dir>/run.log` — full debug logging
- `<output-dir>/manifest.partial.json` — what got done before failure
- `<output-dir>/captures.json` — per-page status, including failure messages
- `references/troubleshooting.md` — known failure modes
