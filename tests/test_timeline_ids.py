from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_timeline.py"


class TimelineStableIdTest(unittest.TestCase):
    def run_validator(self, segments: list[dict], require_ids: bool, ok: bool) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "timeline.json"
            path.write_text(json.dumps({"segments": segments}, ensure_ascii=False), encoding="utf-8")
            command = [sys.executable, str(VALIDATOR), str(path), "--kind", "transcript", "--duration", "5"]
            if require_ids:
                command.append("--require-ids")
            result = subprocess.run(command, text=True, encoding="utf-8", capture_output=True, check=False)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result

    def test_master_timeline_accepts_unique_stable_ids(self) -> None:
        self.run_validator(
            [{"id": "S001", "start": 0, "end": 2, "text": "第一段"}, {"id": "S002", "start": 2, "end": 5, "text": "第二段"}],
            require_ids=True, ok=True,
        )

    def test_master_timeline_rejects_duplicate_ids(self) -> None:
        result = self.run_validator(
            [{"id": "S001", "start": 0, "end": 2, "text": "第一段"}, {"id": "S001", "start": 2, "end": 5, "text": "第二段"}],
            require_ids=True, ok=False,
        )
        self.assertIn("id 重复", result.stdout)

    def test_raw_transcript_can_remain_without_stable_ids(self) -> None:
        self.run_validator([{"start": 0, "end": 5, "text": "原始机器转录"}], require_ids=False, ok=True)


if __name__ == "__main__":
    unittest.main()
