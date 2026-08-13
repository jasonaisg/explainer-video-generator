from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_motion_timing.py"


def scene() -> dict:
    return {
        "scene_id": "A01", "candidate_ids": ["C001"],
        "start_seconds": 0.0, "end_seconds": 5.0,
        "trigger_time_seconds": 0.5, "semantic_complete_time_seconds": 4.0,
        "available_duration_seconds": 5.0,
        "action_budget_seconds": {
            "entry": 0.4, "information_progression": 2.4,
            "readable_hold": 1.5, "exit_or_handoff": 0.7, "total": 5.0,
        },
        "previous_presenter_state": "START", "presenter_mode": "V3_ANIMATION_WITH_PIP",
        "next_presenter_state": "END", "transition_in": "人物缩入画中画",
        "transition_out": "人物恢复全屏", "overlap_tracks": ["presenter", "animation", "captions"],
        "track_index": 0, "allow_scene_overlap": False, "scene_overlap_reason": "",
        "timing_evidence": "预算与五秒区间完全匹配",
        "composition_mode": "INTEGRATED_HYPERFRAMES_SCENE",
        "optional_independent_asset": False, "independent_asset_approval_ref": "",
    }


class MotionTimingValidationTest(unittest.TestCase):
    def data(self) -> dict:
        return {
            "schema_version": "1.0", "timeline_ref": "master-timeline.json",
            "candidate_matrix_ref": "animation-candidate-matrix.json", "scenes": [scene()],
        }

    def run_validator(self, data: dict, ok: bool = True) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "timing.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)], text=True,
                encoding="utf-8", capture_output=True, check=False,
            )
        if ok and result.returncode != 0:
            self.fail(f"验证本应通过：\n{result.stdout}\n{result.stderr}")
        if not ok and result.returncode == 0:
            self.fail("验证本应失败")
        return result

    def test_valid_integrated_scene_passes(self) -> None:
        self.run_validator(self.data())

    def test_schema_11_requires_scene_package_and_individual_script(self) -> None:
        data = self.data(); data["schema_version"] = "1.1"
        result = self.run_validator(data, ok=False)
        self.assertIn("scene_package_index_ref", result.stdout)
        self.assertIn("scene_script_ref", result.stdout)
        data["scene_package_index_ref"] = "04_design/scenes/scene-package-index.json"
        data["scenes"][0]["scene_script_ref"] = "04_design/scenes/A01/motion-script.md"
        self.run_validator(data)

    def test_action_budget_cannot_exceed_locked_interval(self) -> None:
        data = self.data(); budget = data["scenes"][0]["action_budget_seconds"]
        budget.update({"readable_hold": 2.0, "total": 5.5})
        result = self.run_validator(data, ok=False)
        self.assertIn("超过可用时长", result.stdout)

    def test_transparent_or_independent_asset_requires_user_request(self) -> None:
        data = self.data(); data["scenes"][0]["optional_independent_asset"] = True
        result = self.run_validator(data, ok=False)
        self.assertIn("用户交付要求引用", result.stdout)

    def test_scene_overlap_requires_reason_and_separate_track(self) -> None:
        data = self.data(); second = scene()
        second.update({
            "scene_id": "A02", "candidate_ids": ["C002"], "start_seconds": 4.0,
            "end_seconds": 6.0, "trigger_time_seconds": 4.0,
            "semantic_complete_time_seconds": 5.5, "available_duration_seconds": 2.0,
            "action_budget_seconds": {
                "entry": 0.2, "information_progression": 0.8,
                "readable_hold": 0.6, "exit_or_handoff": 0.4, "total": 2.0,
            },
        })
        data["scenes"].append(second)
        result = self.run_validator(data, ok=False)
        self.assertIn("未声明重叠", result.stdout)
        self.assertIn("同一 track_index", result.stdout)


if __name__ == "__main__":
    unittest.main()
