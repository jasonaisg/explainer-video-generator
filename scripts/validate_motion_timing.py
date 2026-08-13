#!/usr/bin/env python3
"""Validate P05 action-level timing against a locked master timeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


BUDGET_KEYS = ("entry", "information_progression", "readable_hold", "exit_or_handoff")
PRESENTER_MODES = {"V1_PRESENTER_FULL", "V2_PRESENTER_OVERLAY", "V3_ANIMATION_WITH_PIP"}
PRESENTER_STATES = PRESENTER_MODES | {"START", "END"}
TOLERANCE = 0.001


def validate(data: dict) -> list[str]:
    issues: list[str] = []
    if data.get("schema_version") != "1.0":
        issues.append("schema_version 必须为 1.0")
    for key in ("timeline_ref", "candidate_matrix_ref"):
        if not str(data.get(key, "")).strip():
            issues.append(f"缺少 {key}")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return issues + ["scenes 必须是非空数组"]
    expected_ids = [f"A{i:02d}" for i in range(1, len(scenes) + 1)]
    actual_ids = [scene.get("scene_id") for scene in scenes]
    if actual_ids != expected_ids:
        issues.append(f"场景编号必须连续：实际 {actual_ids}，预期 {expected_ids}")
    ordered: list[dict] = []
    for index, scene in enumerate(scenes):
        scene_id = scene.get("scene_id") or f"第 {index + 1} 项"
        candidate_ids = scene.get("candidate_ids")
        if not isinstance(candidate_ids, list) or not candidate_ids or not all(isinstance(x, str) and x.strip() for x in candidate_ids):
            issues.append(f"{scene_id} candidate_ids 必须是非空字符串数组")
        start = scene.get("start_seconds"); end = scene.get("end_seconds")
        trigger = scene.get("trigger_time_seconds"); complete = scene.get("semantic_complete_time_seconds")
        available = scene.get("available_duration_seconds")
        valid_range = isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start
        if not valid_range:
            issues.append(f"{scene_id} 时间范围无效")
        else:
            expected_available = float(end) - float(start)
            if not isinstance(trigger, (int, float)) or trigger < start - TOLERANCE or trigger > end + TOLERANCE:
                issues.append(f"{scene_id} trigger_time_seconds 必须位于场景内")
            if not isinstance(complete, (int, float)) or complete < (trigger if isinstance(trigger, (int, float)) else start) - TOLERANCE or complete > end + TOLERANCE:
                issues.append(f"{scene_id} semantic_complete_time_seconds 必须位于触发点之后且不超出场景")
            if not isinstance(available, (int, float)) or abs(float(available) - expected_available) > TOLERANCE:
                issues.append(f"{scene_id} available_duration_seconds 应为 {expected_available:.3f}")
            ordered.append(scene)
        budget = scene.get("action_budget_seconds", {})
        total = 0.0
        for key in BUDGET_KEYS:
            value = budget.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                issues.append(f"{scene_id} action_budget_seconds.{key} 必须为非负数")
            else:
                total += float(value)
        declared_total = budget.get("total")
        if not isinstance(declared_total, (int, float)) or abs(float(declared_total) - total) > TOLERANCE:
            issues.append(f"{scene_id} action_budget_seconds.total 应为 {total:.3f}")
        if isinstance(available, (int, float)) and total > float(available) + TOLERANCE:
            issues.append(f"{scene_id} 动作预算 {total:.3f} 超过可用时长 {float(available):.3f}")
        if scene.get("presenter_mode") not in PRESENTER_MODES:
            issues.append(f"{scene_id} presenter_mode 非法")
        for key in ("previous_presenter_state", "next_presenter_state"):
            if scene.get(key) not in PRESENTER_STATES:
                issues.append(f"{scene_id} {key} 非法：{scene.get(key)}")
        for key in ("transition_in", "transition_out", "timing_evidence"):
            if not str(scene.get(key, "")).strip():
                issues.append(f"{scene_id} 缺少 {key}")
        tracks = scene.get("overlap_tracks")
        if not isinstance(tracks, list) or "presenter" not in tracks:
            issues.append(f"{scene_id} overlap_tracks 必须包含 presenter")
        track_index = scene.get("track_index")
        if not isinstance(track_index, int) or isinstance(track_index, bool) or track_index < 0:
            issues.append(f"{scene_id} track_index 必须为非负整数")
        if scene.get("composition_mode") != "INTEGRATED_HYPERFRAMES_SCENE":
            issues.append(f"{scene_id} composition_mode 必须为 INTEGRATED_HYPERFRAMES_SCENE")
        independent = scene.get("optional_independent_asset")
        if not isinstance(independent, bool):
            issues.append(f"{scene_id} optional_independent_asset 必须为布尔值")
        elif independent and not str(scene.get("independent_asset_approval_ref", "")).strip():
            issues.append(f"{scene_id} 独立或透明素材必须有用户交付要求引用")
    ordered.sort(key=lambda item: item["start_seconds"])
    for index, current in enumerate(ordered):
        for previous in ordered[:index]:
            if current["start_seconds"] >= previous["end_seconds"] - TOLERANCE:
                continue
            if not current.get("allow_scene_overlap"):
                issues.append(f"{current.get('scene_id')} 与 {previous.get('scene_id')} 存在未声明重叠")
            elif not str(current.get("scene_overlap_reason", "")).strip():
                issues.append(f"{current.get('scene_id')} 已允许重叠但缺少 scene_overlap_reason")
            if current.get("track_index") == previous.get("track_index"):
                issues.append(f"{current.get('scene_id')} 与 {previous.get('scene_id')} 重叠时不能使用同一 track_index")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("path"); args = parser.parse_args()
    path = Path(args.path)
    if not path.is_file():
        print(f"错误：文件不存在：{path}"); return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"错误：无法读取 JSON：{exc}"); return 2
    issues = validate(data)
    if issues:
        print(f"动作时间设计检查未通过，共 {len(issues)} 项：")
        for issue in issues: print(f"- {issue}")
        return 1
    print(f"动作时间设计检查通过：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
