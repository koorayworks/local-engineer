#!/usr/bin/env python3
"""Print a compact, shareable Local Engineer diagnostic report.

This intentionally avoids dumping source diffs, environment variables, or full logs.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|authorization)\b"
    r"(\s*[:=]\s*|\s+)([^\s,;]+)"
)
URL_CREDENTIALS_RE = re.compile(r"(https?://)[^/@\s:]+:[^/@\s]+@")
IMPORTANT_RE = re.compile(
    r"(?i)(traceback|\bfailed\b|\bfailures?\b|\berror\b|assertionerror|"
    r"exception|timed?\s*out|\btimeout\b|\bblocked\b|\binterrupted\b)"
)
SUMMARY_RE = re.compile(r"(?i)^\s*(Ran \d+ tests?.*|OK(?: \(.*\))?|FAILED \(.*\)|"
                        r"collected \d+ items?.*|=+ .* (?:failed|passed|error).* =+)\s*$")


def redact(line: str) -> str:
    """Best-effort redaction for common inline secret formats."""
    line = URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", line)
    return SECRET_RE.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", line)


def summarize_log(text: str, limit: int = 12) -> list[str]:
    """Return a short summary plus the most relevant error lines."""
    lines = [redact(line.rstrip()) for line in text.splitlines() if line.strip()]
    if not lines:
        return ["Log is empty."]
    summaries = [line for line in lines if SUMMARY_RE.match(line)]
    relevant = [line for line in lines if IMPORTANT_RE.search(line)]
    # Preserve order and avoid repeated lines.
    chosen: list[str] = []
    for line in summaries + relevant:
        if line not in chosen:
            chosen.append(line)
    if not chosen:
        chosen = lines[-min(6, limit):]
    return chosen[:limit]


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or f"git {' '.join(args)} failed ({result.returncode})"
        return f"[unavailable: {detail}]"
    return result.stdout.strip()


def build_report(root: Path, base: str | None = None) -> str:
    output = ["=== Local Engineer diagnostic report ==="]
    output.append(f"Branch: {git(root, 'branch', '--show-current') or '(detached HEAD)'}")
    output.append(f"HEAD: {git(root, 'log', '-1', '--format=%h %s') or '(unavailable)'}")
    status = git(root, 'status', '--short')
    output.append("Working tree: clean" if not status else "Working tree changes:\n" + status)
    unstaged = git(root, 'diff', '--stat')
    staged = git(root, 'diff', '--cached', '--stat')
    output.append("Unstaged diff: " + (unstaged.replace("\n", " | ") if unstaged else "none"))
    output.append("Staged diff: " + (staged.replace("\n", " | ") if staged else "none"))
    if base:
        output.append(f"Changes vs {base}:")
        names = git(root, 'diff', '--name-only', f'{base}...HEAD')
        stats = git(root, 'diff', '--stat', f'{base}...HEAD')
        output.append("Files: " + (names.replace("\n", ", ") if names else "none"))
        output.append("Stats: " + (stats.replace("\n", " | ") if stats else "none"))
    output.append("=== End report ===")
    return "\n".join(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", help="optional test/build log file to summarize")
    parser.add_argument("--base", help="optional Git ref for a committed-change summary, e.g. origin/main")
    parser.add_argument("--limit", type=int, default=12, help="maximum relevant log lines to print (default: 12)")
    args = parser.parse_args(argv)
    if args.limit < 1 or args.limit > 40:
        parser.error("--limit must be between 1 and 40")

    root = Path(__file__).resolve().parent.parent
    print(build_report(root, args.base))
    if args.log:
        path = Path(args.log).expanduser()
        try:
            # Bound memory use; diagnostic output should not ingest unlimited files.
            with path.open("rb") as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
            truncated = len(raw) > 2 * 1024 * 1024
            text = raw[:2 * 1024 * 1024].decode("utf-8", errors="replace")
        except OSError as exc:
            print(f"\n=== Log summary ===\nCould not read log: {exc}")
            return 2
        print("\n=== Log summary ===")
        if truncated:
            print("[input truncated to first 2 MiB]")
        for line in summarize_log(text, args.limit):
            print(line[:240])
        print("=== End log summary ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
