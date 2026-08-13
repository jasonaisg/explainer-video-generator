from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK_ENVIRONMENT = ROOT / "scripts" / "check_environment.py"
PROJECTCTL = ROOT / "scripts" / "projectctl.py"


class PortabilityTest(unittest.TestCase):
    def test_environment_probe_is_read_only_and_machine_adaptive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "nested" / "environment-report.json"
            result = subprocess.run(
                [sys.executable, str(CHECK_ENVIRONMENT), "--output", str(report_path)],
                text=True, encoding="utf-8", capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], "1.0")
            self.assertTrue(report["python"]["available"])
            self.assertEqual(Path(report["python"]["command"]), Path(sys.executable).resolve())
            self.assertEqual(
                set(report["tools"]),
                {"hyperframes", "ffmpeg", "ffprobe", "node", "npm", "npx", "browser"},
            )

    def test_initialized_project_has_no_platform_specific_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "portable"
            result = subprocess.run(
                [sys.executable, str(PROJECTCTL), "init", str(project), "--name", "portable"],
                text=True, encoding="utf-8", capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads((project / "00_control/project-config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["environment"]["discovery"], "AUTO")
            self.assertEqual(config["backend"]["launcher"], "")
            self.assertEqual(config["backend"]["discovery"], "AUTO")

    def test_skill_does_not_embed_developer_machine_configuration(self) -> None:
        forbidden = (
            re.compile(r"conda[_-]video", re.IGNORECASE),
            re.compile(r"conda\s+run\s+-n", re.IGNORECASE),
            re.compile(r"[A-Za-z]:\\(?:Users|Program Files|OneDrive|miniconda)", re.IGNORECASE),
            re.compile(r"scripts[\\/]hyperframes-local\.cmd", re.IGNORECASE),
        )
        text_suffixes = {".md", ".py", ".yaml", ".yml", ".json", ".txt"}
        violations: list[str] = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in text_suffixes:
                continue
            if path == Path(__file__).resolve():
                continue
            content = path.read_text(encoding="utf-8")
            for pattern in forbidden:
                if pattern.search(content):
                    violations.append(f"{path.relative_to(ROOT)}: {pattern.pattern}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
