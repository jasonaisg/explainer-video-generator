from __future__ import annotations

import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate_p05_scene_packages.py"
SCRIPT_TEMPLATE = ROOT / "assets/templates/scene-motion-script-template.md"


def png(width: int = 2, height: int = 2) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    row = b"\x00" + b"\xff\xff\xff" * width
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b"")


class P05ScenePackageTest(unittest.TestCase):
    def run_validator(self, project: Path, index: Path, *extra: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, str(VALIDATOR), str(project), str(index), *extra], text=True, encoding="utf-8", capture_output=True, check=False)
        if ok and result.returncode != 0: self.fail(result.stdout + result.stderr)
        if not ok and result.returncode == 0: self.fail("验证本应失败")
        return result

    def prepare(self, root: Path) -> tuple[Path, dict]:
        design = root / "04_design"; scene = design / "scenes/A01"; review = scene / "review"
        review.mkdir(parents=True); (design / "DESIGN.md").write_text("# Design\n", encoding="utf-8")
        (design / "motion-timing.json").write_text("{}\n", encoding="utf-8")
        script = SCRIPT_TEMPLATE.read_text(encoding="utf-8").replace(
            "人物全屏与字幕 / 卡片 / 流程图 / 时间线 / 对比表 / 数据图表 / 算式 / 决策树 / 清单 / 路径 / 其他",
            "流程图",
        )
        script = re.sub(r"(?m)^(- [^\n：]+：)\s*$", r"\1已填写", script)
        (scene / "motion-script.md").write_text(script, encoding="utf-8")
        paths = []
        for name in ("01-entry-established.png", "02-information-complete.png", "03-handoff-ready.png"):
            path = review / name; path.write_bytes(png()); paths.append(path)
        data = {
            "schema_version": "1.0", "motion_timing_ref": "04_design/motion-timing.json", "design_ref": "04_design/DESIGN.md", "review_frame_size": {"width": 2, "height": 2},
            "scenes": [{
                "scene_id": "A01", "candidate_ids": ["P04-S001"], "start_seconds": 10.0, "end_seconds": 12.0,
                "script_path": "04_design/scenes/A01/motion-script.md", "script_version": "v1",
                "review_images": [
                    {"role": "ENTRY_ESTABLISHED", "path": "04_design/scenes/A01/review/01-entry-established.png", "absolute_time_seconds": 10.2, "local_time_seconds": 0.2},
                    {"role": "INFORMATION_COMPLETE", "path": "04_design/scenes/A01/review/02-information-complete.png", "absolute_time_seconds": 11.0, "local_time_seconds": 1.0},
                    {"role": "HANDOFF_READY", "path": "04_design/scenes/A01/review/03-handoff-ready.png", "absolute_time_seconds": 11.8, "local_time_seconds": 1.8},
                ],
                "review_status": "APPROVED", "approval_ref": "P05-A01-review-v1",
            }],
        }
        index = scene.parent / "scene-package-index.json"; index.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return index, data

    def test_complete_individual_scene_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); index, _ = self.prepare(root); self.run_validator(root, index, "--final")

    def test_exactly_three_images_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); index, data = self.prepare(root); data["scenes"][0]["review_images"].pop(); index.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = self.run_validator(root, index, "--final", ok=False); self.assertIn("必须且只能有 3 张", result.stdout)

    def test_final_requires_per_scene_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); index, data = self.prepare(root); data["scenes"][0].update({"review_status": "PENDING", "approval_ref": ""}); index.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = self.run_validator(root, index, "--final", ok=False); self.assertIn("尚未获得用户逐场景批准", result.stdout)

    def test_template_category_must_be_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); index, _ = self.prepare(root); script = root / "04_design/scenes/A01/motion-script.md"; script.write_text(SCRIPT_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
            result = self.run_validator(root, index, ok=False); self.assertIn("必须选择具体类别", result.stdout)


if __name__ == "__main__": unittest.main()
