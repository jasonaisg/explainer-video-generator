#!/usr/bin/env python3
"""Build a standalone top-level P04 review page from a schema 2.0 matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix")
    parser.add_argument("output")
    parser.add_argument("--title", default="P04 动画与人物布局审批")
    parser.add_argument("--template")
    args = parser.parse_args()
    matrix_path = Path(args.matrix)
    output = Path(args.output)
    template = Path(args.template) if args.template else Path(__file__).resolve().parents[1] / "assets/templates/p04-review-template.html"
    try:
        raw = matrix_path.read_bytes(); data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"错误：无法读取候选矩阵：{exc}")
        return 2
    if data.get("schema_version") != "2.0" or not isinstance(data.get("candidates"), list) or not data["candidates"]:
        print("错误：审批页只接受非空的候选矩阵 schema 2.0")
        return 2
    data = dict(data); data["matrix_sha256"] = sha256_bytes(raw)
    try: html = template.read_text(encoding="utf-8")
    except OSError as exc: print(f"错误：无法读取审批模板：{exc}"); return 2
    if "<iframe" in html.lower() or "sandbox=" in html.lower():
        print("错误：P04 正式审批页不得使用 sandbox iframe")
        return 2
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("__TITLE__", args.title).replace("__MATRIX_JSON__", payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8", newline="\n")
    print(f"P04 独立审批页已生成：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
