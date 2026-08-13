from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_scene_modules.py"


class SceneModuleValidationTest(unittest.TestCase):
    def create_project(self, root: Path) -> Path:
        timing_path = root / "04_design/motion-timing.json"
        timing_path.parent.mkdir(parents=True)
        timing = {
            "schema_version": "1.0",
            "scenes": [{
                "scene_id": "A01", "start_seconds": 10.0, "end_seconds": 15.0,
                "available_duration_seconds": 5.0, "previous_presenter_state": "START",
                "presenter_mode": "V3_ANIMATION_WITH_PIP", "next_presenter_state": "END",
                "candidate_ids": ["C001"], "transition_in": "人物缩入画中画",
                "transition_out": "人物恢复全屏",
            }],
        }
        timing_path.write_text(json.dumps(timing, ensure_ascii=False), encoding="utf-8")
        module = root / "06_hyperframes/src/scenes/A01"
        module.mkdir(parents=True)
        (module / "scene.js").write_text("export const scene = {};\n", encoding="utf-8")
        (module / "data.json").write_text("{}\n", encoding="utf-8")
        manifest = {
            "schema_version": "1.0", "scene_id": "A01", "status": "IMPLEMENTED",
            "candidate_ids": ["C001"], "timeline_segment_ids": ["S001"],
            "motion_timing_ref": "04_design/motion-timing.json#A01",
            "absolute_timing": {"start_seconds": 10.0, "end_seconds": 15.0, "duration_seconds": 5.0},
            "local_timing": {"zero_seconds": 0.0, "duration_seconds": 5.0},
            "presenter": {"previous_state": "START", "mode": "V3_ANIMATION_WITH_PIP", "next_state": "END"},
            "boundary": {
                "previous_scene_id": "START", "next_scene_id": "END",
                "transition_in": "人物缩入画中画", "transition_out": "人物恢复全屏",
            },
            "source": {
                "entrypoint": "06_hyperframes/src/scenes/A01/scene.js",
                "data_file": "06_hyperframes/src/scenes/A01/data.json",
                "isolated_composition_id": "A01-preview", "shared_dependencies": ["design.tokens"],
            },
            "preview": {
                "checkpoints": ["entry", "information_complete", "handoff"],
                "output_directory": "07_previews/keyframes/A01",
            },
            "output": {
                "composition_mode": "INTEGRATED_HYPERFRAMES_SCENE",
                "optional_independent_asset": False, "independent_asset_approval_ref": "",
            },
            "approval_ref": "P05-G05-v1",
        }
        (module / "scene-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        index = {
            "schema_version": "1.0", "master_timeline_ref": "03_content_plan/master-timeline.json",
            "motion_timing_ref": "04_design/motion-timing.json", "design_ref": "04_design/DESIGN.md",
            "scenes": [{"scene_id": "A01", "manifest": "06_hyperframes/src/scenes/A01/scene-manifest.json"}],
        }
        index_path = root / "06_hyperframes/src/scenes/scene-module-index.json"
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        return index_path

    def run_validator(self, root: Path, index: Path, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(root), str(index.relative_to(root)), "--implemented"],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result

    def test_independent_source_module_with_local_clock_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); index = self.create_project(root)
            self.run_validator(root, index)

    def test_local_duration_must_match_absolute_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); index = self.create_project(root)
            manifest_path = root / "06_hyperframes/src/scenes/A01/scene-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["local_timing"]["duration_seconds"] = 4.5
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            result = self.run_validator(root, index, ok=False)
            self.assertIn("局部时长必须等于绝对时长", result.stdout)

    def test_scene_entrypoint_cannot_escape_its_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); index = self.create_project(root)
            shared_entry = root / "06_hyperframes/src/shared-scene.js"
            shared_entry.write_text("export {};\n", encoding="utf-8")
            manifest_path = root / "06_hyperframes/src/scenes/A01/scene-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source"]["entrypoint"] = "06_hyperframes/src/shared-scene.js"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            result = self.run_validator(root, index, ok=False)
            self.assertIn("必须位于自身模块目录", result.stdout)

    def test_boundary_contract_must_match_index_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); index = self.create_project(root)
            manifest_path = root / "06_hyperframes/src/scenes/A01/scene-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["boundary"]["next_scene_id"] = "A02"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            result = self.run_validator(root, index, ok=False)
            self.assertIn("next_scene_id 应为 END", result.stdout)


if __name__ == "__main__":
    unittest.main()
