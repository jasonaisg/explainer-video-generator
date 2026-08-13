from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTCTL = ROOT / "scripts/projectctl.py"


class ControlConsistencyTest(unittest.TestCase):
    def cli(self, *args: object, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, str(PROJECTCTL), *map(str, args)], text=True, encoding="utf-8", capture_output=True, check=False)
        if ok and result.returncode != 0: self.fail(result.stdout + result.stderr)
        if not ok and result.returncode == 0: self.fail("命令本应失败")
        return result

    def prepare(self, project: Path) -> Path:
        self.cli("init", project, "--name", "控制一致性测试", "--pm-session-id", "pm-1")
        self.cli("register", project, "P00", "--session-id", "p00-1")
        artifact = project / "artifacts/final.txt"; artifact.parent.mkdir(); artifact.write_text("冻结内容", encoding="utf-8")
        manifest = {"phase": "P00", "version": 1, "files": [{"path": "artifacts/final.txt", "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}]}
        (project / "stages/P00/deliverables-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (project / "stages/P00/handoff.md").write_text("# 交接\n\n实时状态以控制文件为准。\n", encoding="utf-8")
        return artifact

    def authorize(self, project: Path) -> None:
        self.cli("authorize-submit", project, "P00", "--artifact", "artifacts/final.txt", "--version", "v1", "--scope", "冻结内容", "--authorization-quote", "可以提交项目经理", "--open-items", 0, "--conditions-status", "CLOSED", "--qa-status", "COMPLETE")

    def test_manifest_rejects_dynamic_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "demo"; self.prepare(project)
            path = project / "stages/P00/deliverables-manifest.json"; data = json.loads(path.read_text(encoding="utf-8")); data["submission_status"] = "PENDING"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = self.cli("authorize-submit", project, "P00", "--artifact", "x", "--version", "v1", "--scope", "x", "--authorization-quote", "可以提交", "--open-items", 0, "--conditions-status", "CLOSED", "--qa-status", "COMPLETE", ok=False)
            self.assertIn("动态流程字段", result.stderr)

    def test_submit_updates_three_control_surfaces_consistently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "demo"; self.prepare(project); self.authorize(project)
            self.cli("submit", project, "P00", "--summary", "完成")
            self.cli("validate-control-consistency", project)
            state = json.loads((project / "00_control/project-state.json").read_text(encoding="utf-8"))
            registry = json.loads((project / "00_control/session-registry.json").read_text(encoding="utf-8"))
            result = json.loads((project / "stages/P00/stage-result.json").read_text(encoding="utf-8"))
            self.assertEqual((state["phase_status"]["P00"], registry["stages"][0]["status"], result["status"]), ("SUBMITTED", "SUBMITTED", "SUBMITTED"))

    def test_control_revision_proves_content_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "demo"; artifact = self.prepare(project); self.authorize(project); self.cli("submit", project, "P00", "--summary", "完成")
            self.cli("return", project, "P00", "--issue-id", "CTRL-001", "--reason", "修正交接状态", "--revision-type", "CONTROL", "--protected-artifact", "artifacts/final.txt")
            artifact.write_text("内容被改变", encoding="utf-8")
            self.cli("resolve-issue", project, "P00", "--issue-id", "CTRL-001", "--resolution", "FIXED", "--evidence", "已修正", ok=False)
            artifact.write_text("冻结内容", encoding="utf-8")
            self.cli("resolve-issue", project, "P00", "--issue-id", "CTRL-001", "--resolution", "FIXED", "--evidence", "内容哈希一致")
            self.cli("validate-control-consistency", project)


if __name__ == "__main__": unittest.main()
