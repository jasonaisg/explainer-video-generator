#!/usr/bin/env python3
"""Apply complete P04 user decisions and recompute presenter continuity."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path


MODES = ("V1_PRESENTER_FULL", "V2_PRESENTER_OVERLAY", "V3_ANIMATION_WITH_PIP")
MODE_STATES = {"V1_PRESENTER_FULL": "FULL", "V2_PRESENTER_OVERLAY": "FULL", "V3_ANIMATION_WITH_PIP": "PIP"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def transition(source: str, target: str) -> str:
    if source == "START": return f"从片头进入人物{target}状态"
    if target == "END": return f"人物{source}状态保持至片尾"
    if source == target: return f"人物保持{target}状态"
    return f"人物由{source}状态切换为{target}状态"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix")
    parser.add_argument("decisions")
    parser.add_argument("output")
    parser.add_argument("--approval-ref", required=True)
    args = parser.parse_args()
    matrix_path, decisions_path, output = Path(args.matrix), Path(args.decisions), Path(args.output)
    try:
        matrix_raw = matrix_path.read_bytes(); matrix = json.loads(matrix_raw.decode("utf-8"))
        decision_raw = decisions_path.read_bytes(); decision_data = json.loads(decision_raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"错误：无法读取输入：{exc}")
        return 2
    if matrix.get("schema_version") != "2.0": print("错误：候选矩阵必须为 schema 2.0"); return 2
    if decision_data.get("schema_version") != "1.0": print("错误：决定文件必须为 schema 1.0"); return 2
    if decision_data.get("candidate_matrix_version") != matrix.get("schema_version"):
        print("错误：决定文件对应的候选矩阵版本不一致"); return 2
    expected_matrix_hash = decision_data.get("candidate_matrix_sha256")
    if expected_matrix_hash and expected_matrix_hash.lower() != sha256_bytes(matrix_raw):
        print("错误：决定文件绑定的候选矩阵 SHA-256 不一致"); return 2
    candidates = matrix.get("candidates")
    decisions = decision_data.get("decisions")
    if not isinstance(candidates, list) or not candidates or not isinstance(decisions, list):
        print("错误：候选矩阵或决定数组无效"); return 2
    expected_ids = [item.get("id") for item in candidates if isinstance(item, dict)]
    decision_ids = [item.get("segment_id") if isinstance(item, dict) else None for item in decisions]
    duplicates = sorted({item for item in decision_ids if decision_ids.count(item) > 1})
    missing = sorted(set(expected_ids) - set(decision_ids)); unknown = sorted(set(decision_ids) - set(expected_ids))
    if duplicates or missing or unknown or len(decision_ids) != len(expected_ids):
        print(f"错误：决定必须恰好覆盖全部切片；重复={duplicates}，遗漏={missing}，未知={unknown}")
        return 2
    by_id = {item["segment_id"]: item for item in decisions}
    selected_modes: list[str] = []
    result = copy.deepcopy(matrix)
    for item in result["candidates"]:
        decision = by_id[item["id"]]; mode = decision.get("selected_mode")
        if mode not in MODES: print(f"错误：{item['id']} selected_mode 非法：{mode}"); return 2
        screen_text = decision.get("final_screen_text")
        expression = decision.get("final_visual_expression")
        notes = decision.get("user_notes", "")
        if not isinstance(screen_text, str) or not isinstance(expression, str) or not expression.strip() or not isinstance(notes, str):
            print(f"错误：{item['id']} 用户文字字段必须是字符串，且最终视觉表达不能为空"); return 2
        if mode == "V1_PRESENTER_FULL" and screen_text.strip():
            print(f"错误：{item['id']} 选择 V1 时不得添加额外屏幕文字"); return 2
        option = item.get("mode_options", {}).get(mode)
        if not isinstance(option, dict): print(f"错误：{item['id']} 所选模式没有完整预生成方案"); return 2
        item["user_selected_mode"] = mode
        item["approved_plan"] = {
            "mode": mode,
            "source_option": copy.deepcopy(option),
            "final_screen_text": screen_text,
            "final_visual_expression": expression,
            "user_notes": notes,
        }
        item["user_decision_ref"] = f"{decisions_path.name}#{item['id']}"
        item["approval_ref"] = args.approval_ref
        selected_modes.append(mode)
    for index, item in enumerate(result["candidates"]):
        current = MODE_STATES[selected_modes[index]]
        previous = "START" if index == 0 else MODE_STATES[selected_modes[index - 1]]
        following = "END" if index == len(selected_modes) - 1 else MODE_STATES[selected_modes[index + 1]]
        item["adjacency"] = {
            "previous_presenter_state": previous,
            "current_presenter_state": current,
            "next_presenter_state": following,
            "transition_in_intent": transition(previous, current),
            "transition_out_intent": transition(current, following),
        }
        tracks = ["presenter", "captions"]
        if selected_modes[index] == "V2_PRESENTER_OVERLAY": tracks.append("overlay")
        if selected_modes[index] == "V3_ANIMATION_WITH_PIP": tracks.append("animation")
        item["overlap_tracks"] = tracks
    output.parent.mkdir(parents=True, exist_ok=True)
    try: decision_ref = os.path.relpath(decisions_path.resolve(), output.parent.resolve()).replace("\\", "/")
    except ValueError: decision_ref = str(decisions_path.resolve())
    result["decision_artifact"] = {"path": decision_ref, "sha256": sha256_bytes(decision_raw)}
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(output)
    print(f"已应用 {len(decisions)} 项用户决定并重算人物连续性：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
