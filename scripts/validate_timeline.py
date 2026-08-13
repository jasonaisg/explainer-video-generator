#!/usr/bin/env python3
"""Validate transcript, caption, or presenter-layout timeline JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MODES = {"V1_PRESENTER_FULL", "V2_PRESENTER_OVERLAY", "V3_ANIMATION_WITH_PIP"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("path"); p.add_argument("--kind", choices=["transcript", "captions", "layout"], required=True); p.add_argument("--duration", type=float, required=True); p.add_argument("--epsilon", type=float, default=0.05); p.add_argument("--require-ids", action="store_true", help="Require unique stable IDs, intended for the P02 master timeline")
    args = p.parse_args(); data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    segments = data.get("segments", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    issues = []
    if not isinstance(segments, list) or not segments: issues.append("segments 为空或不是数组"); segments = []
    previous_end = 0.0
    seen_ids: set[str] = set()
    for i, seg in enumerate(segments):
        try: start = float(seg["start"]); end = float(seg["end"])
        except (KeyError, TypeError, ValueError): issues.append(f"segment {i} 缺少有效 start/end"); continue
        if start < -args.epsilon or end <= start or end > args.duration + args.epsilon: issues.append(f"segment {i} 时间范围非法：{start}–{end}")
        if start < previous_end - args.epsilon: issues.append(f"segment {i} 与前段重叠或逆序")
        if args.kind in {"transcript", "captions"} and not str(seg.get("text", "")).strip(): issues.append(f"segment {i} 文本为空")
        if args.require_ids:
            segment_id = seg.get("id")
            if not isinstance(segment_id, str) or not segment_id.strip():
                issues.append(f"segment {i} 缺少稳定 id")
            elif segment_id in seen_ids:
                issues.append(f"segment {i} id 重复：{segment_id}")
            else:
                seen_ids.add(segment_id)
        if args.kind == "layout":
            if seg.get("mode") not in MODES: issues.append(f"segment {i} mode 非法")
            if seg.get("presenter_visible") is not True: issues.append(f"segment {i} presenter_visible 必须为 true")
            if start > previous_end + args.epsilon: issues.append(f"layout 在 {previous_end}–{start} 存在空档")
        previous_end = max(previous_end, end)
    if args.kind == "layout" and abs(previous_end - args.duration) > args.epsilon: issues.append(f"layout 未覆盖结尾：{previous_end} vs {args.duration}")
    for issue in issues: print(f"ERROR: {issue}")
    if issues: print(f"时间轴校验失败：{len(issues)} 项"); return 1
    print(f"时间轴校验通过：{len(segments)} segments / {args.kind}"); return 0


if __name__ == "__main__": raise SystemExit(main())
