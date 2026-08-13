#!/usr/bin/env python3
"""Validate P04 cognitive segmentation against stable cues and final captions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


TOLERANCE = 0.001
BOUNDARY_KEYS = (
    "start_reason", "not_merge_previous", "not_split_internal",
    "end_reason", "next_task_reason",
)


def nonempty_strings(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def validate(data: object) -> list[str]:
    issues: list[str] = []
    if not isinstance(data, dict):
        return ["根节点必须是 JSON 对象"]
    if data.get("schema_version") != "1.0":
        issues.append("schema_version 必须为 1.0")
    for key in ("master_timeline_ref", "final_captions_ref"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            issues.append(f"{key} 必须是非空字符串")

    coverage = data.get("coverage")
    if not isinstance(coverage, dict):
        issues.append("coverage 必须是对象")
        coverage = {}
    expected_cues = coverage.get("timeline_segment_ids")
    expected_captions = coverage.get("final_caption_ids")
    if not nonempty_strings(expected_cues):
        issues.append("coverage.timeline_segment_ids 必须是非空字符串数组")
        expected_cues = []
    if not nonempty_strings(expected_captions):
        issues.append("coverage.final_caption_ids 必须是非空字符串数组")
        expected_captions = []
    if len(expected_cues) != len(set(expected_cues)):
        issues.append("coverage.timeline_segment_ids 包含重复 ID")
    if len(expected_captions) != len(set(expected_captions)):
        issues.append("coverage.final_caption_ids 包含重复 ID")

    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        return issues + ["segments 必须是非空数组"]
    expected_ids = [f"P04-S{i:03d}" for i in range(1, len(segments) + 1)]
    actual_ids = [item.get("id") if isinstance(item, dict) else None for item in segments]
    if actual_ids != expected_ids:
        issues.append(f"切片编号必须连续：实际 {actual_ids}，预期 {expected_ids}")

    used_cues: list[str] = []
    used_captions: list[str] = []
    previous_end: float | None = None
    for index, item in enumerate(segments):
        label = expected_ids[index]
        if not isinstance(item, dict):
            issues.append(f"{label} 必须是对象")
            continue
        label = str(item.get("id") or label)
        start, end = item.get("start_seconds"), item.get("end_seconds")
        numeric = (
            isinstance(start, (int, float)) and not isinstance(start, bool)
            and isinstance(end, (int, float)) and not isinstance(end, bool)
        )
        if not numeric or end <= start:
            issues.append(f"{label} 时间范围无效")
        else:
            if previous_end is not None and abs(float(start) - previous_end) > TOLERANCE:
                relation = "重叠" if start < previous_end else "存在未解释间隙"
                issues.append(f"{label} 与前一切片{relation}")
            previous_end = float(end)
        for key in ("full_transcript", "cognitive_task"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                issues.append(f"{label} 缺少 {key}")
        cue_ids = item.get("timeline_segment_ids")
        caption_ids = item.get("final_caption_ids")
        if not nonempty_strings(cue_ids):
            issues.append(f"{label} timeline_segment_ids 必须是非空字符串数组")
        else:
            used_cues.extend(cue_ids)
        if not nonempty_strings(caption_ids):
            issues.append(f"{label} final_caption_ids 必须是非空字符串数组")
        else:
            used_captions.extend(caption_ids)
        boundary = item.get("boundary_reason")
        if not isinstance(boundary, dict):
            issues.append(f"{label} boundary_reason 必须是对象")
        else:
            for key in BOUNDARY_KEYS:
                if not isinstance(boundary.get(key), str) or not boundary[key].strip():
                    issues.append(f"{label} 缺少 boundary_reason.{key}")

    for kind, expected, used in (
        ("稳定时间轴", expected_cues, used_cues),
        ("最终字幕", expected_captions, used_captions),
    ):
        duplicates = sorted({item for item in used if used.count(item) > 1})
        missing = sorted(set(expected) - set(used))
        unknown = sorted(set(used) - set(expected))
        if duplicates: issues.append(f"{kind} ID 重复覆盖：{duplicates}")
        if missing: issues.append(f"{kind} ID 未覆盖：{missing}")
        if unknown: issues.append(f"{kind} ID 未在 coverage 声明：{unknown}")
        if expected and used != expected:
            issues.append(f"{kind} ID 覆盖顺序与权威时间轴不一致")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    args = parser.parse_args()
    path = Path(args.path)
    if not path.is_file():
        print(f"错误：文件不存在：{path}")
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"错误：无法读取 JSON：{exc}")
        return 2
    issues = validate(data)
    if issues:
        print(f"语义切片检查未通过，共 {len(issues)} 项：")
        for issue in issues: print(f"- {issue}")
        return 1
    print(f"语义切片检查通过：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
