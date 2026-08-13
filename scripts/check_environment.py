#!/usr/bin/env python3
"""Discover available video-production tools without changing the machine."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


TOOL_CANDIDATES = {
    "hyperframes": ("hyperframes",),
    "ffmpeg": ("ffmpeg",),
    "ffprobe": ("ffprobe",),
    "node": ("node",),
    "npm": ("npm",),
    "npx": ("npx",),
    "browser": (
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
        "chrome", "msedge", "microsoft-edge",
    ),
}


def resolve(value: str | None, candidates: tuple[str, ...]) -> str | None:
    if value:
        supplied = Path(value).expanduser()
        if supplied.is_file():
            return str(supplied.resolve())
        return shutil.which(value)
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def version_of(command: str | None) -> dict[str, object]:
    if not command:
        return {"available": False, "command": None, "version": None, "probe_ok": False}
    try:
        result = subprocess.run(
            [command, "--version"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=8, check=False,
        )
        output = (result.stdout or result.stderr).strip().splitlines()
        return {
            "available": True,
            "command": command,
            "version": output[0][:500] if output else None,
            "probe_ok": result.returncode == 0,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": True, "command": command, "version": None, "probe_ok": False, "error": str(exc)[:500]}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", help="Optional UTF-8 JSON report path")
    for name in ("hyperframes", "ffmpeg", "ffprobe", "node", "npm", "npx", "browser"):
        p.add_argument(f"--{name}", help=f"Explicit {name} executable or launcher")
    return p


def main() -> int:
    args = parser().parse_args()
    overrides = vars(args)
    tools = {
        name: version_of(resolve(overrides.get(name), candidates))
        for name, candidates in TOOL_CANDIDATES.items()
    }
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "python": {
            "available": sys.version_info >= (3, 10),
            "command": str(Path(sys.executable).resolve()),
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "tools": tools,
        "notes": [
            "Discovery is read-only and PATH-based unless an explicit launcher is supplied.",
            "Unavailable optional tools only matter when the corresponding stage or module needs them.",
        ],
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        target = Path(args.output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["python"]["available"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
