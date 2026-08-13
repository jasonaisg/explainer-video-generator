#!/usr/bin/env python3
"""Build a SHA-256 deliverables manifest from project-relative files."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): value.update(chunk)
    return value.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("root"); p.add_argument("phase"); p.add_argument("files", nargs="+"); p.add_argument("--output"); p.add_argument("--artifact-map", help="按项目相对路径提供 artifact_id、version、type 和 depends_on 的 JSON 对象")
    args = p.parse_args(); root = Path(args.root).resolve(); items = []
    metadata = json.loads(Path(args.artifact_map).read_text(encoding="utf-8")) if args.artifact_map else {}
    for name in args.files:
        target = (root / name).resolve()
        try: rel = target.relative_to(root).as_posix()
        except ValueError: print(f"ERROR: 交付物不在项目根目录内：{target}"); return 2
        if not target.is_file(): print(f"ERROR: 文件不存在：{target}"); return 2
        item = {"path": rel, "bytes": target.stat().st_size, "sha256": digest(target)}
        if rel in metadata:
            extra = metadata[rel]
            required = {"artifact_id", "version", "type", "depends_on"}
            if not isinstance(extra, dict) or not required.issubset(extra): print(f"ERROR: {rel} 的 artifact-map 字段不完整：{sorted(required)}"); return 2
            item.update({key: extra[key] for key in required})
        items.append(item)
    out = Path(args.output) if args.output else root / "stages" / args.phase / "deliverables-manifest.json"
    payload = {"phase": args.phase, "version": 1, "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "files": items}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {len(items)} 个交付物：{out}"); return 0


if __name__ == "__main__": raise SystemExit(main())
