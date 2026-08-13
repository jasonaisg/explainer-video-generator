from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_animation_candidates.py"


def candidate() -> dict:
    scores = {
        "comprehension_gain": {"value": 2, "evidence": "关系用画面更容易理解"},
        "memory_gain": {"value": 2, "evidence": "可以形成稳定视觉锚点"},
        "information_density": {"value": 2, "evidence": "包含数据与比较"},
        "misreading_risk": {"value": 1, "evidence": "需要保留适用范围"},
        "production_value": {"value": 1, "evidence": "可用轻量结构完成"},
    }
    return {
        "id": "C001", "start_seconds": 0.0, "end_seconds": 5.0,
        "transcript_ref": "timeline:S001",
        "timeline_segment_ids": ["S001"], "trigger_time_seconds": 0.5,
        "semantic_complete_time_seconds": 4.0, "available_duration_seconds": 5.0,
        "timing_feasibility": "PASS", "timing_evidence": "五秒足以完成两卡片比较",
        "first_principles": {
            "cognitive_goal": "理解两项差异", "cognitive_obstacle": "比较关系容易混淆",
            "visual_advantage": True, "visual_advantage_reason": "并排结构比口播更快",
            "minimal_structure": "两张同轴卡片", "memory_result": "两项差异",
        },
        "information_type": "两项比较", "preferred_visual_structure": "并排卡片",
        "non_preferred_structure": "两套无关画风", "scores": scores,
        "total_score": 8, "threshold_recommendation": "PRIORITIZE",
        "screen_copy": {
            "locked_full_fact": "符合条件时，两项存在差异", "compressed_text": "符合条件｜两项差异",
            "preserved_qualifiers": ["符合条件"],
        },
        "agent_recommendation": "PRIORITIZE", "agent_recommendation_reason": "理解收益明确",
        "final_disposition": "PRIORITIZE", "presenter_mode": "V3_ANIMATION_WITH_PIP",
        "layout_constraints": "避开人物与字幕区", "not_selected_reason": "",
        "adjacency": {
            "previous_presenter_state": "START", "next_presenter_state": "END",
            "transition_in_intent": "人物缩入画中画", "transition_out_intent": "人物恢复全屏",
        },
        "overlap_tracks": ["presenter", "animation", "captions"],
        "user_override": False, "user_decision_quote": "", "approval_ref": "P04-G04-v1",
    }


class AnimationCandidateValidationTest(unittest.TestCase):
    def run_validator(self, data: dict, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "candidates.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path), *args], text=True,
                encoding="utf-8", capture_output=True, check=False,
            )
        if ok and result.returncode != 0:
            self.fail(f"验证本应通过：\n{result.stdout}\n{result.stderr}")
        if not ok and result.returncode == 0:
            self.fail("验证本应失败")
        return result

    def data(self) -> dict:
        return {
            "schema_version": "1.0", "timeline_ref": "master-timeline.json",
            "coverage": {
                "start_seconds": 0.0, "end_seconds": 5.0,
                "source_segment_ids": ["S001"], "uncovered_segment_ids": [],
            },
            "candidates": [candidate()],
        }

    def test_complete_final_matrix_passes(self) -> None:
        self.run_validator(self.data(), "--final")

    def test_user_can_override_high_score_recommendation(self) -> None:
        data = self.data(); item = data["candidates"][0]
        item.update({
            "final_disposition": "PRESENTER_ONLY", "not_selected_reason": "用户希望保留人物口播",
            "user_override": True, "user_decision_quote": "这一段不要动画，保留人物",
        })
        self.run_validator(data, "--final")

    def test_override_requires_user_evidence_but_not_score_compliance(self) -> None:
        data = self.data(); item = data["candidates"][0]
        item.update({"final_disposition": "PRESENTER_ONLY", "not_selected_reason": "保留口播"})
        result = self.run_validator(data, "--final", ok=False)
        self.assertIn("user_override=true", result.stdout)

    def test_score_total_and_threshold_are_deterministic(self) -> None:
        data = self.data(); data["candidates"][0]["total_score"] = 7
        result = self.run_validator(data, ok=False)
        self.assertIn("total_score 应为 8", result.stdout)

    def test_visual_plan_must_be_time_feasible(self) -> None:
        data = self.data(); data["candidates"][0]["timing_feasibility"] = "PRESENTER_ONLY"
        result = self.run_validator(data, "--final", ok=False)
        self.assertIn("时间方案调整为 PASS 或 SIMPLIFY", result.stdout)

    def test_every_master_timeline_segment_must_be_covered(self) -> None:
        data = self.data(); data["coverage"]["source_segment_ids"].append("S002")
        result = self.run_validator(data, ok=False)
        self.assertIn("S002", result.stdout)


if __name__ == "__main__":
    unittest.main()
