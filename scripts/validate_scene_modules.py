#!/usr/bin/env python3
"""Validate independently maintainable scene modules against P05 timing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PRESENTER_MODES = {"V1_PRESENTER_FULL", "V2_PRESENTER_OVERLAY", "V3_ANIMATION_WITH_PIP"}
PRESENTER_STATES = PRESENTER_MODES | {"START", "END"}
CHECKPOINTS = {"entry", "information_complete", "handoff"}
TOLERANCE = 0.001


def load(path: Path, issues: list[str]) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"无法读取 JSON {path}: {exc}")
        return {}


def project_path(root: Path, value: object, label: str, issues: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{label} 路径为空"); return None
    path = Path(value)
    if path.is_absolute():
        issues.append(f"{label} 必须使用项目相对路径：{value}"); return None
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        issues.append(f"{label} 越出项目目录：{value}"); return None
    return resolved


def close(left: object, right: object) -> bool:
    return isinstance(left, (int, float)) and isinstance(right, (int, float)) and abs(float(left) - float(right)) <= TOLERANCE


def validate(root: Path, index_path: Path, implemented: bool) -> list[str]:
    issues: list[str] = []
    index = load(index_path, issues)
    if index.get("schema_version") != "1.0": issues.append("索引 schema_version 必须为 1.0")
    for key in ("master_timeline_ref", "design_ref"):
        if not str(index.get(key, "")).strip(): issues.append(f"索引缺少 {key}")
    timing_path = project_path(root, index.get("motion_timing_ref"), "motion_timing_ref", issues)
    timing = load(timing_path, issues) if timing_path and timing_path.is_file() else {}
    if timing_path and not timing_path.is_file(): issues.append(f"动作时间设计不存在：{timing_path}")
    timing_scenes = {item.get("scene_id"): item for item in timing.get("scenes", [])}
    entries = index.get("scenes")
    if not isinstance(entries, list) or not entries: return issues + ["索引 scenes 必须是非空数组"]
    expected_ids = [f"A{i:02d}" for i in range(1, len(entries) + 1)]
    actual_ids = [item.get("scene_id") for item in entries]
    if actual_ids != expected_ids: issues.append(f"场景索引必须连续：实际 {actual_ids}，预期 {expected_ids}")
    seen_manifests: set[Path] = set()
    seen_composition_ids: set[str] = set()
    for position, entry in enumerate(entries):
        scene_id = entry.get("scene_id") or f"第 {position + 1} 项"
        manifest_path = project_path(root, entry.get("manifest"), f"{scene_id} manifest", issues)
        if not manifest_path or not manifest_path.is_file():
            if manifest_path: issues.append(f"{scene_id} manifest 不存在：{manifest_path}")
            continue
        if manifest_path in seen_manifests: issues.append(f"{scene_id} manifest 路径重复")
        seen_manifests.add(manifest_path)
        manifest = load(manifest_path, issues)
        if manifest.get("schema_version") != "1.0": issues.append(f"{scene_id} manifest schema_version 必须为 1.0")
        if manifest.get("scene_id") != scene_id: issues.append(f"{scene_id} manifest 中的 scene_id 不一致")
        if manifest.get("status") not in {"PLANNED", "IMPLEMENTED"}: issues.append(f"{scene_id} status 非法")
        if implemented and manifest.get("status") != "IMPLEMENTED": issues.append(f"{scene_id} 尚未标记 IMPLEMENTED")
        for key in ("candidate_ids", "timeline_segment_ids"):
            values = manifest.get(key)
            if not isinstance(values, list) or not values or not all(isinstance(x, str) and x.strip() for x in values):
                issues.append(f"{scene_id} {key} 必须是非空字符串数组")
        timing_scene = timing_scenes.get(scene_id)
        if not timing_scene:
            issues.append(f"{scene_id} 在动作时间设计中不存在"); timing_scene = {}
        expected_timing_ref = f"{index.get('motion_timing_ref')}#{scene_id}"
        if manifest.get("motion_timing_ref") != expected_timing_ref: issues.append(f"{scene_id} motion_timing_ref 应为 {expected_timing_ref}")
        if timing_scene and manifest.get("candidate_ids") != timing_scene.get("candidate_ids"):
            issues.append(f"{scene_id} candidate_ids 与 P05 动作时间设计不一致")
        absolute = manifest.get("absolute_timing", {}); local = manifest.get("local_timing", {})
        start = absolute.get("start_seconds"); end = absolute.get("end_seconds"); duration = absolute.get("duration_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            issues.append(f"{scene_id} absolute_timing 范围无效")
        elif not close(duration, float(end) - float(start)):
            issues.append(f"{scene_id} absolute_timing.duration_seconds 与起止时间不一致")
        if not close(local.get("zero_seconds"), 0.0): issues.append(f"{scene_id} local_timing.zero_seconds 必须为 0")
        if not close(local.get("duration_seconds"), duration): issues.append(f"{scene_id} 局部时长必须等于绝对时长")
        for manifest_key, timing_key in (("start_seconds", "start_seconds"), ("end_seconds", "end_seconds"), ("duration_seconds", "available_duration_seconds")):
            if timing_scene and not close(absolute.get(manifest_key), timing_scene.get(timing_key)):
                issues.append(f"{scene_id} {manifest_key} 与 P05 动作时间设计不一致")
        presenter = manifest.get("presenter", {})
        for key in ("previous_state", "next_state"):
            if presenter.get(key) not in PRESENTER_STATES: issues.append(f"{scene_id} presenter.{key} 非法")
        if presenter.get("mode") not in PRESENTER_MODES: issues.append(f"{scene_id} presenter.mode 非法")
        if timing_scene:
            comparisons = (("previous_state", "previous_presenter_state"), ("mode", "presenter_mode"), ("next_state", "next_presenter_state"))
            for manifest_key, timing_key in comparisons:
                if presenter.get(manifest_key) != timing_scene.get(timing_key): issues.append(f"{scene_id} presenter.{manifest_key} 与 P05 不一致")
        boundary = manifest.get("boundary", {})
        expected_previous = "START" if position == 0 else expected_ids[position - 1]
        expected_next = "END" if position == len(entries) - 1 else expected_ids[position + 1]
        if boundary.get("previous_scene_id") != expected_previous: issues.append(f"{scene_id} previous_scene_id 应为 {expected_previous}")
        if boundary.get("next_scene_id") != expected_next: issues.append(f"{scene_id} next_scene_id 应为 {expected_next}")
        for key in ("transition_in", "transition_out"):
            if not str(boundary.get(key, "")).strip(): issues.append(f"{scene_id} boundary.{key} 不能为空")
            elif timing_scene and boundary.get(key) != timing_scene.get(key): issues.append(f"{scene_id} boundary.{key} 与 P05 不一致")
        source = manifest.get("source", {})
        entrypoint = project_path(root, source.get("entrypoint"), f"{scene_id} entrypoint", issues)
        data_value = source.get("data_file")
        data_file = project_path(root, data_value, f"{scene_id} data_file", issues) if data_value else None
        for label, path in (("entrypoint", entrypoint), ("data_file", data_file)):
            if path:
                try: path.relative_to(manifest_path.parent)
                except ValueError: issues.append(f"{scene_id} {label} 必须位于自身模块目录")
                if implemented and not path.is_file(): issues.append(f"{scene_id} {label} 文件不存在：{path}")
        composition_id = source.get("isolated_composition_id")
        if not isinstance(composition_id, str) or not composition_id.strip(): issues.append(f"{scene_id} 缺少 isolated_composition_id")
        elif composition_id in seen_composition_ids: issues.append(f"{scene_id} isolated_composition_id 重复：{composition_id}")
        else: seen_composition_ids.add(composition_id)
        shared = source.get("shared_dependencies")
        if not isinstance(shared, list) or not all(isinstance(x, str) and x.strip() for x in shared): issues.append(f"{scene_id} shared_dependencies 必须为字符串数组")
        preview = manifest.get("preview", {})
        checkpoints = preview.get("checkpoints")
        if not isinstance(checkpoints, list) or not CHECKPOINTS.issubset(set(checkpoints)): issues.append(f"{scene_id} 必须声明 entry、information_complete、handoff 三个预览点")
        project_path(root, preview.get("output_directory"), f"{scene_id} preview.output_directory", issues)
        output = manifest.get("output", {})
        if output.get("composition_mode") != "INTEGRATED_HYPERFRAMES_SCENE": issues.append(f"{scene_id} 默认合成方式必须为 INTEGRATED_HYPERFRAMES_SCENE")
        independent = output.get("optional_independent_asset")
        if not isinstance(independent, bool): issues.append(f"{scene_id} optional_independent_asset 必须为布尔值")
        elif independent and not str(output.get("independent_asset_approval_ref", "")).strip(): issues.append(f"{scene_id} 独立素材缺少用户要求引用")
        if not str(manifest.get("approval_ref", "")).strip(): issues.append(f"{scene_id} 缺少 approval_ref")
    missing_timing = sorted(set(timing_scenes) - set(actual_ids))
    if missing_timing: issues.append(f"动作时间设计中的场景未进入模块索引：{missing_timing}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root"); parser.add_argument("index"); parser.add_argument("--implemented", action="store_true")
    args = parser.parse_args(); root = Path(args.root).resolve()
    index_path = Path(args.index); index_path = index_path.resolve() if index_path.is_absolute() else (root / index_path).resolve()
    try: index_path.relative_to(root)
    except ValueError: print("错误：索引路径越出项目目录"); return 2
    issues = validate(root, index_path, args.implemented)
    if issues:
        print(f"场景模块检查未通过，共 {len(issues)} 项：")
        for issue in issues: print(f"- {issue}")
        return 1
    print(f"场景模块检查通过：{index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
