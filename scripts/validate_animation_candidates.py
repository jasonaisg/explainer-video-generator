#!/usr/bin/env python3
"""Validate legacy or schema 2.0 P04 animation candidate matrices."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


VISUAL_SCORE_KEYS = (
    "comprehension_gain", "memory_gain", "information_density",
    "misreading_risk", "production_value",
)
MODE_SCORE_KEYS = (
    "cognitive_goal_fit", "obstacle_reduction", "minimal_sufficiency",
    "misreading_control", "timing_fit",
)
FIRST_PRINCIPLE_KEYS = (
    "cognitive_goal", "cognitive_obstacle", "visual_advantage",
    "visual_advantage_reason", "minimal_structure", "memory_result",
)
OPTION_KEYS = (
    "natural_name", "purpose", "screen_text", "visual_structure",
    "appearance_sequence", "presenter_state", "layout_and_avoidance",
    "cognitive_obstacle_reduced", "timing_feasibility",
    "timing_evidence", "misreading_control",
)
MODES = ("V1_PRESENTER_FULL", "V2_PRESENTER_OVERLAY", "V3_ANIMATION_WITH_PIP")
MODE_STATES = {"V1_PRESENTER_FULL": "FULL", "V2_PRESENTER_OVERLAY": "FULL", "V3_ANIMATION_WITH_PIP": "PIP"}
TIMING_FEASIBILITY = {"PASS", "SIMPLIFY", "MERGE", "PRESENTER_ONLY"}
FINAL_DISPOSITIONS = {"PENDING", "PRIORITIZE", "MERGE_OR_SIMPLIFY", "PRESENTER_ONLY", "CUSTOM"}
TOLERANCE = 0.001


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def string_list(value: object, *, allow_empty: bool = False) -> bool:
    return isinstance(value, list) and (allow_empty or bool(value)) and all(nonempty(item) for item in value)


def expected_threshold(total: int) -> str:
    if total >= 7: return "PRIORITIZE"
    if total >= 4: return "MERGE_OR_SIMPLIFY"
    return "PRESENTER_ONLY"


def validate_scores(container: object, keys: tuple[str, ...], label: str, issues: list[str]) -> int:
    if not isinstance(container, dict):
        issues.append(f"{label} 必须是对象")
        return 0
    total = 0
    for key in keys:
        score = container.get(key)
        if not isinstance(score, dict):
            issues.append(f"{label}.{key} 必须是对象，禁止字符串化对象")
            continue
        value = score.get("value")
        if not isinstance(value, int) or isinstance(value, bool) or value not in {0, 1, 2}:
            issues.append(f"{label}.{key}.value 必须为 0、1 或 2")
        else:
            total += value
        if not nonempty(score.get("evidence")):
            issues.append(f"{label}.{key}.evidence 不能为空")
    return total


def validate_time(item: dict, label: str, issues: list[str]) -> None:
    start, end = item.get("start_seconds"), item.get("end_seconds")
    numeric = all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (start, end))
    if not numeric or end <= start:
        issues.append(f"{label} 时间范围无效")
        return
    trigger = item.get("trigger_time_seconds")
    complete = item.get("semantic_complete_time_seconds")
    available = item.get("available_duration_seconds")
    if not isinstance(trigger, (int, float)) or isinstance(trigger, bool) or not start - TOLERANCE <= trigger <= end + TOLERANCE:
        issues.append(f"{label} trigger_time_seconds 必须位于区间内")
    if not isinstance(complete, (int, float)) or isinstance(complete, bool) or not (trigger if isinstance(trigger, (int, float)) else start) - TOLERANCE <= complete <= end + TOLERANCE:
        issues.append(f"{label} semantic_complete_time_seconds 必须位于触发点之后且不超出区间")
    expected = float(end) - float(start)
    if not isinstance(available, (int, float)) or isinstance(available, bool) or abs(float(available) - expected) > TOLERANCE:
        issues.append(f"{label} available_duration_seconds 应为 {expected:.3f}")


def validate_first_principles(value: object, label: str, issues: list[str]) -> None:
    if not isinstance(value, dict):
        issues.append(f"{label}.first_principles 必须是对象")
        return
    for key in FIRST_PRINCIPLE_KEYS:
        if key == "visual_advantage":
            if not isinstance(value.get(key), bool): issues.append(f"{label} first_principles.{key} 必须为布尔值")
        elif not nonempty(value.get(key)):
            issues.append(f"{label} 缺少 first_principles.{key}")


def coverage_issues(expected: list[str], used: list[str], label: str) -> list[str]:
    issues: list[str] = []
    duplicates = sorted({item for item in used if used.count(item) > 1})
    missing = sorted(set(expected) - set(used))
    unknown = sorted(set(used) - set(expected))
    if duplicates: issues.append(f"{label} ID 重复覆盖：{duplicates}")
    if missing: issues.append(f"{label} ID 未覆盖：{missing}")
    if unknown: issues.append(f"{label} ID 未在 coverage 声明：{unknown}")
    if expected and used != expected: issues.append(f"{label} ID 覆盖顺序与权威时间轴不一致")
    return issues


def validate_v1(data: dict, final: bool) -> list[str]:
    """Keep schema 1.0 behavior for already frozen projects."""
    issues: list[str] = []
    coverage = data.get("coverage")
    if not isinstance(coverage, dict): coverage = {}; issues.append("coverage 必须是对象")
    expected = coverage.get("source_segment_ids")
    if not string_list(expected): issues.append("coverage.source_segment_ids 必须列出 P02 的全部有效片段 ID"); expected = []
    if coverage.get("uncovered_segment_ids"): issues.append("coverage.uncovered_segment_ids 必须为空；每个有效口播片段都要有记录")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates: return issues + ["candidates 必须是非空数组"]
    expected_ids = [f"C{i:03d}" for i in range(1, len(candidates) + 1)]
    if [x.get("id") if isinstance(x, dict) else None for x in candidates] != expected_ids: issues.append("候选编号必须连续")
    used: list[str] = []
    for index, item in enumerate(candidates):
        label = expected_ids[index]
        if not isinstance(item, dict): issues.append(f"{label} 必须是对象"); continue
        label = str(item.get("id") or label); validate_time(item, label, issues)
        if not nonempty(item.get("transcript_ref")): issues.append(f"{label} 缺少 transcript_ref")
        ids = item.get("timeline_segment_ids")
        if not string_list(ids): issues.append(f"{label} timeline_segment_ids 必须是非空字符串数组")
        else: used.extend(ids)
        if item.get("timing_feasibility") not in TIMING_FEASIBILITY: issues.append(f"{label} timing_feasibility 非法")
        if not nonempty(item.get("timing_evidence")): issues.append(f"{label} 缺少 timing_evidence")
        validate_first_principles(item.get("first_principles"), label, issues)
        total = validate_scores(item.get("scores"), VISUAL_SCORE_KEYS, f"{label} scores", issues)
        if item.get("total_score") != total: issues.append(f"{label} total_score 应为 {total}")
        threshold = expected_threshold(total)
        if item.get("threshold_recommendation") != threshold: issues.append(f"{label} threshold_recommendation 应为 {threshold}")
        if item.get("agent_recommendation") not in FINAL_DISPOSITIONS - {"PENDING"}: issues.append(f"{label} agent_recommendation 非法")
        if not nonempty(item.get("agent_recommendation_reason")): issues.append(f"{label} 缺少 agent_recommendation_reason")
        screen = item.get("screen_copy")
        if not isinstance(screen, dict): screen = {}; issues.append(f"{label} screen_copy 必须是对象")
        if not nonempty(screen.get("locked_full_fact")): issues.append(f"{label} 缺少 screen_copy.locked_full_fact")
        if not isinstance(screen.get("preserved_qualifiers"), list): issues.append(f"{label} screen_copy.preserved_qualifiers 必须为数组")
        if item.get("presenter_mode") not in MODES: issues.append(f"{label} presenter_mode 非法")
        if not nonempty(item.get("layout_constraints")): issues.append(f"{label} 缺少 layout_constraints")
        adjacency = item.get("adjacency")
        if not isinstance(adjacency, dict): adjacency = {}; issues.append(f"{label} adjacency 必须是对象")
        valid_states = set(MODES) | {"START", "END"}
        for key in ("previous_presenter_state", "next_presenter_state"):
            if adjacency.get(key) not in valid_states: issues.append(f"{label} adjacency.{key} 非法")
        for key in ("transition_in_intent", "transition_out_intent"):
            if not nonempty(adjacency.get(key)): issues.append(f"{label} 缺少 adjacency.{key}")
        if not isinstance(item.get("overlap_tracks"), list) or "presenter" not in item["overlap_tracks"]: issues.append(f"{label} overlap_tracks 必须包含 presenter")
        disposition = item.get("final_disposition")
        if disposition not in FINAL_DISPOSITIONS: issues.append(f"{label} final_disposition 非法")
        if disposition == "PRESENTER_ONLY" and not nonempty(item.get("not_selected_reason")): issues.append(f"{label} 保留纯口播时必须记录 not_selected_reason")
        if final:
            if disposition == "PENDING": issues.append(f"{label} 最终矩阵不得保持 PENDING")
            if disposition in {"PRIORITIZE", "CUSTOM"} and item.get("timing_feasibility") not in {"PASS", "SIMPLIFY"}: issues.append(f"{label} 最终制作视觉前必须把时间方案调整为 PASS 或 SIMPLIFY")
            if disposition != "PRESENTER_ONLY" and not nonempty(screen.get("compressed_text")): issues.append(f"{label} 制作视觉时缺少 screen_copy.compressed_text")
            if not nonempty(item.get("approval_ref")): issues.append(f"{label} 最终矩阵缺少 approval_ref")
            if disposition != item.get("agent_recommendation") and not item.get("user_override"): issues.append(f"{label} 最终去留不同于 Agent 建议时必须标记 user_override=true")
            if item.get("user_override") and not nonempty(item.get("user_decision_quote")): issues.append(f"{label} 用户 override 缺少 user_decision_quote")
    issues.extend(coverage_issues(expected, used, "主时间轴"))
    return issues


def validate_option(option: object, mode: str, label: str, issues: list[str]) -> None:
    if not isinstance(option, dict):
        issues.append(f"{label} mode_options.{mode} 必须是完整对象")
        return
    for key in OPTION_KEYS:
        if mode == "V1_PRESENTER_FULL" and key == "screen_text":
            continue
        if not nonempty(option.get(key)): issues.append(f"{label} mode_options.{mode}.{key} 不能为空")
    if option.get("timing_feasibility") not in TIMING_FEASIBILITY: issues.append(f"{label} mode_options.{mode}.timing_feasibility 非法")
    if mode == "V1_PRESENTER_FULL":
        if option.get("screen_text") != "": issues.append(f"{label} V1 不得包含额外屏幕文字")
        if option.get("presenter_state") != "FULL": issues.append(f"{label} V1 presenter_state 必须为 FULL")
    elif mode == "V2_PRESENTER_OVERLAY" and option.get("presenter_state") != "FULL":
        issues.append(f"{label} V2 presenter_state 必须为 FULL")
    elif mode == "V3_ANIMATION_WITH_PIP" and option.get("presenter_state") != "PIP":
        issues.append(f"{label} V3 presenter_state 必须为 PIP")


def validate_v2(data: dict, final: bool, base_dir: Path | None) -> list[str]:
    issues: list[str] = []
    for key in ("segmentation_ref", "master_timeline_ref", "final_captions_ref"):
        if not nonempty(data.get(key)): issues.append(f"{key} 必须是非空字符串")
    coverage = data.get("coverage")
    if not isinstance(coverage, dict): coverage = {}; issues.append("coverage 必须是对象")
    expected_cues = coverage.get("timeline_segment_ids")
    expected_captions = coverage.get("final_caption_ids")
    if not string_list(expected_cues): issues.append("coverage.timeline_segment_ids 必须是非空字符串数组"); expected_cues = []
    if not string_list(expected_captions): issues.append("coverage.final_caption_ids 必须是非空字符串数组"); expected_captions = []
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates: return issues + ["candidates 必须是非空数组"]
    expected_ids = [f"P04-S{i:03d}" for i in range(1, len(candidates) + 1)]
    actual_ids = [x.get("id") if isinstance(x, dict) else None for x in candidates]
    if actual_ids != expected_ids: issues.append(f"候选编号必须连续：实际 {actual_ids}，预期 {expected_ids}")
    used_cues: list[str] = []; used_captions: list[str] = []
    modes: list[str] = []
    previous_end: float | None = None
    for index, item in enumerate(candidates):
        label = expected_ids[index]
        if not isinstance(item, dict): issues.append(f"{label} 必须是对象"); modes.append("PENDING"); continue
        label = str(item.get("id") or label); validate_time(item, label, issues)
        start = item.get("start_seconds")
        if previous_end is not None and isinstance(start, (int, float)) and abs(float(start) - previous_end) > TOLERANCE: issues.append(f"{label} 与前一切片不连续")
        if isinstance(item.get("end_seconds"), (int, float)): previous_end = float(item["end_seconds"])
        for key in ("cognitive_task", "boundary_reason", "timing_evidence", "mode_recommendation_reason", "layout_constraints"):
            if not nonempty(item.get(key)): issues.append(f"{label} 缺少 {key}")
        cue_ids = item.get("timeline_segment_ids")
        if not string_list(cue_ids): issues.append(f"{label} timeline_segment_ids 必须是非空字符串数组")
        else: used_cues.extend(cue_ids)
        refs = item.get("final_caption_refs")
        if not isinstance(refs, list) or not refs: issues.append(f"{label} final_caption_refs 必须是非空数组")
        else:
            for ref in refs:
                if not isinstance(ref, dict): issues.append(f"{label} final_caption_refs 成员必须是对象"); continue
                caption_id = ref.get("id")
                if not nonempty(caption_id): issues.append(f"{label} final_caption_refs.id 不能为空")
                else: used_captions.append(caption_id)
                if not nonempty(ref.get("text")): issues.append(f"{label} 最终字幕 {caption_id or '?'} 文本为空")
        validate_first_principles(item.get("first_principles"), label, issues)
        total = validate_scores(item.get("visual_necessity_scores"), VISUAL_SCORE_KEYS, f"{label} visual_necessity_scores", issues)
        if item.get("visual_necessity_total") != total: issues.append(f"{label} visual_necessity_total 应为 {total}")
        if item.get("visual_necessity_recommendation") != expected_threshold(total): issues.append(f"{label} visual_necessity_recommendation 与总分不一致")
        options = item.get("mode_options")
        if not isinstance(options, dict): options = {}; issues.append(f"{label} mode_options 必须是对象")
        fits = item.get("mode_fit_scores")
        if not isinstance(fits, dict): fits = {}; issues.append(f"{label} mode_fit_scores 必须是对象")
        for mode in MODES:
            validate_option(options.get(mode), mode, label, issues)
            validate_scores(fits.get(mode), MODE_SCORE_KEYS, f"{label} mode_fit_scores.{mode}", issues)
        recommendation = item.get("mode_recommendation")
        if recommendation not in MODES: issues.append(f"{label} mode_recommendation 非法")
        selected = item.get("user_selected_mode")
        if selected not in (*MODES, "PENDING"): issues.append(f"{label} user_selected_mode 非法")
        modes.append(selected)
        if item.get("timing_feasibility") not in TIMING_FEASIBILITY: issues.append(f"{label} timing_feasibility 非法")
        if final:
            if selected == "PENDING": issues.append(f"{label} 最终矩阵不得保持 PENDING")
            approved = item.get("approved_plan")
            if not isinstance(approved, dict): issues.append(f"{label} approved_plan 必须是对象")
            else:
                if approved.get("mode") != selected: issues.append(f"{label} approved_plan.mode 与用户选择不一致")
                if selected in options and approved.get("source_option") != options.get(selected): issues.append(f"{label} approved_plan.source_option 与已生成方案不一致")
            if not nonempty(item.get("user_decision_ref")): issues.append(f"{label} 缺少 user_decision_ref")
            if not nonempty(item.get("approval_ref")): issues.append(f"{label} 缺少 approval_ref")
    issues.extend(coverage_issues(expected_cues, used_cues, "稳定时间轴"))
    issues.extend(coverage_issues(expected_captions, used_captions, "最终字幕"))
    if final:
        for index, item in enumerate(candidates):
            if not isinstance(item, dict): continue
            label = str(item.get("id") or expected_ids[index]); selected = modes[index]
            adjacency = item.get("adjacency")
            if not isinstance(adjacency, dict): issues.append(f"{label} adjacency 必须是对象"); continue
            current = MODE_STATES.get(selected)
            previous = "START" if index == 0 else MODE_STATES.get(modes[index - 1])
            following = "END" if index == len(candidates) - 1 else MODE_STATES.get(modes[index + 1])
            for key, expected in (("previous_presenter_state", previous), ("current_presenter_state", current), ("next_presenter_state", following)):
                if adjacency.get(key) != expected: issues.append(f"{label} adjacency.{key} 应为 {expected}")
            for key in ("transition_in_intent", "transition_out_intent"):
                if not nonempty(adjacency.get(key)): issues.append(f"{label} 缺少 adjacency.{key}")
            tracks = item.get("overlap_tracks")
            required = {"presenter", "captions"}
            if selected == "V2_PRESENTER_OVERLAY": required.add("overlay")
            if selected == "V3_ANIMATION_WITH_PIP": required.add("animation")
            if not isinstance(tracks, list) or not required.issubset(set(tracks)): issues.append(f"{label} overlap_tracks 缺少 {sorted(required)}")
        artifact = data.get("decision_artifact")
        if not isinstance(artifact, dict): issues.append("decision_artifact 必须是对象")
        else:
            rel, expected_hash = artifact.get("path"), artifact.get("sha256")
            if not nonempty(rel) or not isinstance(expected_hash, str) or len(expected_hash) != 64:
                issues.append("decision_artifact 必须包含路径和 SHA-256")
            elif base_dir is not None:
                target = Path(rel)
                if not target.is_absolute(): target = base_dir / target
                if not target.is_file(): issues.append(f"用户决定文件不存在：{target}")
                elif sha256(target) != expected_hash.lower(): issues.append("用户决定文件哈希与矩阵记录不一致")
    return issues


def validate(data: object, final: bool = False, base_dir: Path | None = None) -> list[str]:
    if not isinstance(data, dict): return ["根节点必须是 JSON 对象"]
    version = data.get("schema_version")
    if version == "1.0": return validate_v1(data, final)
    if version == "2.0": return validate_v2(data, final, base_dir)
    return [f"schema_version 必须为 1.0 或 2.0，实际为 {version}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args(); path = Path(args.path)
    if not path.is_file(): print(f"错误：文件不存在：{path}"); return 2
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: print(f"错误：无法读取 JSON：{exc}"); return 2
    issues = validate(data, args.final, path.parent)
    if issues:
        print(f"候选矩阵检查未通过，共 {len(issues)} 项：")
        for issue in issues: print(f"- {issue}")
        return 1
    print(f"候选矩阵检查通过：{path}")
    print("提示：评分仅生成制作建议；用户最终决定不由本验证器评判。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
