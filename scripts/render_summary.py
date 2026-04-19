#!/usr/bin/env python3
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def block(title: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        value = "none"
    return f"## {title}\n{value}\n"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: render_summary.py <summary_file>", file=sys.stderr)
        return 1

    summary_file = Path(sys.argv[1])
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw_output = sys.stdin.read().strip()

    content = [
        "# Planner Summary",
        "",
        f"Generated: {generated}",
        "",
        block("ACTIVE ROLE", os.getenv("SUMMARY_ACTIVE_ROLE", "none")).rstrip(),
        "",
        block("STATUS", os.getenv("SUMMARY_STATUS", "error")).rstrip(),
        "",
        block("OBJECTIVE", os.getenv("SUMMARY_OBJECTIVE", "")).rstrip(),
        "",
        block("FILES IN SCOPE", os.getenv("SUMMARY_FILES_IN_SCOPE", "")).rstrip(),
        "",
        block("FILES READ", os.getenv("SUMMARY_FILES_READ", "")).rstrip(),
        "",
        block("FILES CHANGED", os.getenv("SUMMARY_FILES_CHANGED", "")).rstrip(),
        "",
        block("COMMANDS RUN", os.getenv("SUMMARY_COMMANDS_RUN", "")).rstrip(),
        "",
        block("KEY ERROR OUTPUT", os.getenv("SUMMARY_KEY_OUTPUT", "")).rstrip(),
        "",
        block("SUMMARY", os.getenv("SUMMARY_TEXT", "")).rstrip(),
        "",
        block("BLOCKERS", os.getenv("SUMMARY_BLOCKERS", "")).rstrip(),
        "",
        block("RECOMMENDED NEXT ROLE", os.getenv("SUMMARY_NEXT_ROLE", "planner")).rstrip(),
        "",
        block("RECOMMENDED NEXT STEP", os.getenv("SUMMARY_NEXT_STEP", "Read summary.md, then write command.md")).rstrip(),
        "",
        block("RAW OUTPUT", raw_output).rstrip(),
        "",
        f"## LAST UPDATED\n{generated}",
        "",
    ]
    summary_file.write_text("\n".join(content), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
