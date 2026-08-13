#!/usr/bin/env python3
"""Validate a P04 first-principles animation candidate matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SCORE_KEYS = (
    "comprehension_gain", "memory_gain", "information_density",
    "misreading_risk", "production_value",
)
FIRST_PRINCIPLE_KEYS = (
    "cognitive_goal", "cognitive_obstacle", "visual_advantage",
    "visual_advantage_reason", "minimal_structure", "memory_result",
)
FINAL_DISPOSITIONS = {
    "PENDING", "PRIORITIZE", "MERGE_OR_SIMPLIFY", "PRESENTER_ONLY", "CUSTOM",
}
AGENT_RECOMMENDATIONS = FINAL_DISPOSITIONS - {"PENDING"}
PRESENTER_MODES = {"V1_PRESENTER_FULL", "V2_PRESENTER_OVERLAY", "V3_ANIMATION_WITH_PIP"}
PRESENTER_STATES = PRESENTER_MODES | {"START", "END"}
TIMING_FEASIBILITY = {"PASS", "SIMPLIFY", "MERGE", "PRESENTER_ONLY"}
TOLERANCE = 0.001


def expected_threshold(total: int) -> str:
    if total >= 7:
        return "PRIORITIZE"
    if total >= 4:
        return "MERGE_OR_SIMPLIFY"
    return "PRESENTER_ONLY"


def validate(data: dict, final: bool = False) -> list[str]:
    issues: list[str] = []
    if data.get("schema_version") != "1.0":
        issues.append("schema_version 必须为 1.0")
    coverage = data.get("coverage", {})
    source_segment_ids = coverage.get("source_segment_ids")
    if not isinstance(source_segment_ids, list) or not source_segment_ids or not all(isinstance(x, str) and x.strip() for x in source_segment_ids):
        issues.append("coverage.source_segment_ids 必须列出 P02 的全部有效片段 ID")
        source_segment_ids = []
    if coverage.get("uncovered_segment_ids"):
        issues.append("coverage.uncovered_segment_ids 必须为空；每个有效口播片段都要有记录")
    coverage_start = coverage.get("start_seconds")
    coverage_end = coverage.get("end_seconds")
    if not isinstance(coverage_start, (int, float)) or not isinstance(coverage_end, (int, float)) or coverage_end <= coverage_start:
        issues.append("coverage 时间范围无效")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return issues + ["candidates 必须是非空数组"]
    expected_ids = [f"C{i:03d}" for i in range(1, len(candidates) + 1)]
    actual_ids = [item.get("id") for item in candidates]
    if actual_ids != expected_ids:
        issues.append(f"候选编号必须连续：实际 {actual_ids}，预期 {expected_ids}")
    previous_end: float | None = None
    used_segment_ids: set[str] = set()
    for index, item in enumerate(candidates):
        item_id = item.get("id") or f"第 {index + 1} 项"
        start = item.get("start_seconds")
        end = item.get("end_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            issues.append(f"{item_id} 时间范围无效")
        elif previous_end is not None and start < previous_end:
            issues.append(f"{item_id} 与前一区间重叠或逆序")
        if isinstance(start, (int, float)) and isinstance(coverage_start, (int, float)) and start < coverage_start - TOLERANCE:
            issues.append(f"{item_id} 起点超出主时间轴覆盖范围")
        if isinstance(end, (int, float)) and isinstance(coverage_end, (int, float)) and end > coverage_end + TOLERANCE:
            issues.append(f"{item_id} 终点超出主时间轴覆盖范围")
        if isinstance(end, (int, float)):
            previous_end = float(end)
        if not str(item.get("transcript_ref", "")).strip():
            issues.append(f"{item_id} 缺少 transcript_ref")
        segment_ids = item.get("timeline_segment_ids")
        if not isinstance(segment_ids, list) or not segment_ids or not all(isinstance(x, str) and x.strip() for x in segment_ids):
            issues.append(f"{item_id} timeline_segment_ids 必须是非空字符串数组")
        else:
            used_segment_ids.update(segment_ids)
            unknown = sorted(set(segment_ids) - set(source_segment_ids))
            if unknown:
                issues.append(f"{item_id} 引用了 coverage 中不存在的片段：{unknown}")
        trigger = item.get("trigger_time_seconds")
        complete = item.get("semantic_complete_time_seconds")
        available = item.get("available_duration_seconds")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
            expected_available = float(end) - float(start)
            if not isinstance(trigger, (int, float)) or trigger < start - TOLERANCE or trigger > end + TOLERANCE:
                issues.append(f"{item_id} trigger_time_seconds 必须位于区间内")
            if not isinstance(complete, (int, float)) or complete < (trigger if isinstance(trigger, (int, float)) else start) - TOLERANCE or complete > end + TOLERANCE:
                issues.append(f"{item_id} semantic_complete_time_seconds 必须位于触发点之后且不超出区间")
            if not isinstance(available, (int, float)) or abs(float(available) - expected_available) > TOLERANCE:
                issues.append(f"{item_id} available_duration_seconds 应为 {expected_available:.3f}")
        feasibility = item.get("timing_feasibility")
        if feasibility not in TIMING_FEASIBILITY:
            issues.append(f"{item_id} timing_feasibility 非法：{feasibility}")
        if not str(item.get("timing_evidence", "")).strip():
            issues.append(f"{item_id} 缺少 timing_evidence")
        answers = item.get("first_principles", {})
        for key in FIRST_PRINCIPLE_KEYS:
            if key == "visual_advantage":
                if not isinstance(answers.get(key), bool):
                    issues.append(f"{item_id} first_principles.{key} 必须为布尔值")
            elif not str(answers.get(key, "")).strip():
                issues.append(f"{item_id} 缺少 first_principles.{key}")
        for key in ("information_type", "preferred_visual_structure", "non_preferred_structure"):
            if not str(item.get(key, "")).strip():
                issues.append(f"{item_id} 缺少 {key}")
        scores = item.get("scores", {})
        total = 0
        for key in SCORE_KEYS:
            score = scores.get(key, {})
            value = score.get("value")
            if not isinstance(value, int) or isinstance(value, bool) or value not in {0, 1, 2}:
                issues.append(f"{item_id} scores.{key}.value 必须为 0、1 或 2")
            else:
                total += value
            if not str(score.get("evidence", "")).strip():
                issues.append(f"{item_id} scores.{key}.evidence 不能为空")
        if item.get("total_score") != total:
            issues.append(f"{item_id} total_score 应为 {total}")
        threshold = expected_threshold(total)
        if item.get("threshold_recommendation") != threshold:
            issues.append(f"{item_id} threshold_recommendation 应为 {threshold}")
        agent_recommendation = item.get("agent_recommendation")
        if agent_recommendation not in AGENT_RECOMMENDATIONS:
            issues.append(f"{item_id} agent_recommendation 非法：{agent_recommendation}")
        if not str(item.get("agent_recommendation_reason", "")).strip():
            issues.append(f"{item_id} 缺少 agent_recommendation_reason")
        screen_copy = item.get("screen_copy", {})
        if not str(screen_copy.get("locked_full_fact", "")).strip():
            issues.append(f"{item_id} 缺少 screen_copy.locked_full_fact")
        if not isinstance(screen_copy.get("preserved_qualifiers"), list):
            issues.append(f"{item_id} screen_copy.preserved_qualifiers 必须为数组")
        presenter_mode = item.get("presenter_mode")
        if presenter_mode not in PRESENTER_MODES:
            issues.append(f"{item_id} presenter_mode 非法：{presenter_mode}")
        if not str(item.get("layout_constraints", "")).strip():
            issues.append(f"{item_id} 缺少 layout_constraints")
        adjacency = item.get("adjacency", {})
        for key in ("previous_presenter_state", "next_presenter_state"):
            if adjacency.get(key) not in PRESENTER_STATES:
                issues.append(f"{item_id} adjacency.{key} 非法：{adjacency.get(key)}")
        for key in ("transition_in_intent", "transition_out_intent"):
            if not str(adjacency.get(key, "")).strip():
                issues.append(f"{item_id} 缺少 adjacency.{key}")
        overlap_tracks = item.get("overlap_tracks")
        if not isinstance(overlap_tracks, list) or "presenter" not in overlap_tracks:
            issues.append(f"{item_id} overlap_tracks 必须包含 presenter")
        disposition = item.get("final_disposition")
        if disposition not in FINAL_DISPOSITIONS:
            issues.append(f"{item_id} final_disposition 非法：{disposition}")
        if disposition == "PRESENTER_ONLY" and not str(item.get("not_selected_reason", "")).strip():
            issues.append(f"{item_id} 保留纯口播时必须记录 not_selected_reason")
        if final:
            if disposition == "PENDING":
                issues.append(f"{item_id} 最终矩阵不得保持 PENDING")
            if disposition in {"PRIORITIZE", "CUSTOM"} and feasibility not in {"PASS", "SIMPLIFY"}:
                issues.append(f"{item_id} 最终制作视觉前必须把时间方案调整为 PASS 或 SIMPLIFY")
            if disposition == "MERGE_OR_SIMPLIFY" and feasibility == "PRESENTER_ONLY":
                issues.append(f"{item_id} 合并或简化方案仍被标记为时间不可执行")
            if disposition != "PRESENTER_ONLY" and not str(screen_copy.get("compressed_text", "")).strip():
                issues.append(f"{item_id} 制作视觉时缺少 screen_copy.compressed_text")
            if not str(item.get("approval_ref", "")).strip():
                issues.append(f"{item_id} 最终矩阵缺少 approval_ref")
            if disposition != agent_recommendation and not item.get("user_override"):
                issues.append(f"{item_id} 最终去留不同于 Agent 建议时必须标记 user_override=true")
            if item.get("user_override") and not str(item.get("user_decision_quote", "")).strip():
                issues.append(f"{item_id} 用户 override 缺少 user_decision_quote")
    missing_segments = sorted(set(source_segment_ids) - used_segment_ids)
    if missing_segments:
        issues.append(f"以下主时间轴片段没有候选记录：{missing_segments}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--final", action="store_true")
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
    issues = validate(data, args.final)
    if issues:
        print(f"候选矩阵检查未通过，共 {len(issues)} 项：")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print(f"候选矩阵检查通过：{path}")
    print("提示：评分仅生成制作建议；用户最终决定不由本验证器评判。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
