from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEGMENT = ROOT / "scripts/validate_semantic_segmentation.py"
CANDIDATES = ROOT / "scripts/validate_animation_candidates.py"
BUILD = ROOT / "scripts/build_p04_review.py"
APPLY = ROOT / "scripts/apply_p04_decisions.py"
TEMPLATE = ROOT / "assets/templates/animation-candidate-matrix-template.json"


def complete_matrix() -> dict:
    data = json.loads(TEMPLATE.read_text(encoding="utf-8")); item = data["candidates"][0]
    item.update({
        "cognitive_task": "理解一个条件结论", "boundary_reason": "该区间完成一个独立认知任务",
        "timing_evidence": "一秒只保留最小结构", "mode_recommendation_reason": "人物表达已经足够",
        "layout_constraints": "避开字幕和平台绝对遮挡区",
    })
    item["final_caption_refs"][0]["text"] = "符合条件时成立"
    item["first_principles"].update({
        "cognitive_goal": "理解条件结论", "cognitive_obstacle": "容易遗漏条件",
        "visual_advantage_reason": "轻提示可保留条件", "minimal_structure": "人物与字幕",
        "memory_result": "符合条件时成立",
    })
    for score in item["visual_necessity_scores"].values(): score["evidence"] = "有明确取值依据"
    for mode, option in item["mode_options"].items():
        option.update({
            "purpose": "完成条件结论的理解", "appearance_sequence": "随口播进入并在结论后保持",
            "cognitive_obstacle_reduced": "避免遗漏条件", "timing_evidence": "可在当前区间完成",
        })
        if mode != "V1_PRESENTER_FULL": option["screen_text"] = "符合条件"
        if mode == "V2_PRESENTER_OVERLAY":
            option.update({"visual_structure": "人物旁显示条件标签", "layout_and_avoidance": "避开人脸和字幕", "misreading_control": "保留条件限定"})
        if mode == "V3_ANIMATION_WITH_PIP":
            option.update({"visual_structure": "条件闸门与结论卡", "appearance_sequence": "闸门先出现，结论卡随后进入", "cognitive_obstacle_reduced": "显示条件与结论关系", "timing_evidence": "简化后可执行", "misreading_control": "条件始终可见"})
    for scores in item["mode_fit_scores"].values():
        for score in scores.values(): score["evidence"] = "与认知任务和时长相符"
    return data


class P04V2Test(unittest.TestCase):
    def run_script(self, script: Path, *args: object, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, str(script), *map(str, args)], text=True, encoding="utf-8", capture_output=True, check=False)
        if ok and result.returncode != 0: self.fail(result.stdout + result.stderr)
        if not ok and result.returncode == 0: self.fail("命令本应失败")
        return result

    def test_segmentation_requires_exact_dual_coverage(self) -> None:
        data = {
            "schema_version": "1.0", "master_timeline_ref": "master.json", "final_captions_ref": "captions.json",
            "coverage": {"timeline_segment_ids": ["S001"], "final_caption_ids": ["caption-0001"]},
            "segments": [{"id": "P04-S001", "start_seconds": 0, "end_seconds": 1, "timeline_segment_ids": ["S001"], "final_caption_ids": ["caption-0001"], "full_transcript": "符合条件时成立", "cognitive_task": "理解条件结论", "boundary_reason": {"start_reason": "口播开始", "not_merge_previous": "首段", "not_split_internal": "单一任务", "end_reason": "结论完成", "next_task_reason": "末段"}}],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "seg.json"; path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.run_script(SEGMENT, path)
            data["segments"][0]["final_caption_ids"].append("caption-0001"); path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = self.run_script(SEGMENT, path, ok=False); self.assertIn("重复覆盖", result.stdout)

    def test_review_export_apply_and_final_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); matrix_path = folder / "matrix.json"; output = folder / "final.json"; page = folder / "review.html"
            matrix = complete_matrix(); raw = json.dumps(matrix, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"; matrix_path.write_bytes(raw)
            self.run_script(CANDIDATES, matrix_path)
            self.run_script(BUILD, matrix_path, page)
            html = page.read_text(encoding="utf-8"); self.assertNotIn("<iframe", html.lower()); self.assertIn("localStorage", html); self.assertIn("Blob", html); self.assertIn("备用下载 JSON", html); self.assertIn("json-output", html)
            decisions = {"schema_version": "1.0", "candidate_matrix_version": "2.0", "candidate_matrix_sha256": hashlib.sha256(raw).hexdigest(), "decisions": [{"segment_id": "P04-S001", "selected_mode": "V3_ANIMATION_WITH_PIP", "final_screen_text": "符合条件", "final_visual_expression": "条件闸门与结论卡", "user_notes": "采用完整画布"}], "exported_at": "2026-08-13T00:00:00+08:00"}
            decision_path = folder / "p04-decisions.json"; decision_path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.run_script(APPLY, matrix_path, decision_path, output, "--approval-ref", "P04-review-v1")
            self.run_script(CANDIDATES, output, "--final")
            final = json.loads(output.read_text(encoding="utf-8")); item = final["candidates"][0]
            self.assertEqual(item["approved_plan"]["final_screen_text"], "符合条件")
            self.assertEqual(item["adjacency"]["current_presenter_state"], "PIP")

    def test_stringified_score_reports_type_error_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "matrix.json"; data = complete_matrix(); data["candidates"][0]["visual_necessity_scores"]["memory_gain"] = "@{value=1}"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = self.run_script(CANDIDATES, path, ok=False)
            self.assertIn("禁止字符串化对象", result.stdout); self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__": unittest.main()
