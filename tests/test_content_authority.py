from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTCTL = ROOT / "scripts" / "projectctl.py"
VALIDATE = ROOT / "scripts" / "validate_project.py"


class ContentAuthorityTest(unittest.TestCase):
    def run_cli(self, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(PROJECTCTL), *map(str, args)],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if ok and result.returncode != 0:
            self.fail(f"命令失败：{result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
        if not ok and result.returncode == 0:
            self.fail(f"命令本应失败：{result.args}\nstdout={result.stdout}")
        return result

    def prepare_manifest(self, project: Path, phase: str = "P00") -> None:
        artifact = project / "artifacts" / "final.txt"
        artifact.parent.mkdir(exist_ok=True)
        artifact.write_text("用户最终内容", encoding="utf-8")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        manifest = {"phase": phase, "version": 1, "files": [{"path": "artifacts/final.txt", "sha256": digest}]}
        (project / "stages" / phase / "deliverables-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (project / "stages" / phase / "handoff.md").write_text("# 交接\n\n已按用户决定完成。\n", encoding="utf-8")

    def authorize(self, project: Path, phase: str = "P00", ok: bool = True) -> None:
        self.run_cli(
            "authorize-submit", project, phase, "--artifact", "artifacts/final.txt", "--version", "v1",
            "--scope", "用户最终内容", "--authorization-quote", "可以提交项目经理",
            "--open-items", "0", "--conditions-status", "CLOSED", "--qa-status", "COMPLETE", ok=ok,
        )

    def test_rejected_high_priority_advice_never_blocks_or_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "demo"
            self.run_cli("init", project, "--name", "内容权威测试", "--pm-session-id", "pm-1")
            self.run_cli("register", project, "P00", "--session-id", "p00-1")
            self.prepare_manifest(project)
            self.run_cli(
                "record-advice", project, "P00", "--advice-id", "ADV-001", "--priority", "HIGH",
                "--topic", "措辞", "--recommendation", "建议修改", "--rationale", "Agent 自己的判断",
            )
            self.run_cli(
                "record-owner-decision", project, "P00", "--decision-id", "DEC-001",
                "--decision", "KEEP_ORIGINAL", "--scope", "全部内容", "--decision-quote", "保留我的原内容",
                "--advice-id", "ADV-001", "--advice-disposition", "REJECTED",
            )
            self.authorize(project)
            self.run_cli(
                "record-advice", project, "P00", "--advice-id", "ADV-002", "--priority", "HIGH",
                "--topic", "事实", "--recommendation", "另一项建议", "--rationale", "仅供参考",
            )
            state_before = json.loads((project / "00_control/project-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state_before["phase_status"]["P00"], "SUBMISSION_AUTHORIZED")
            decisions_path = project / "stages/P00/owner-decisions.json"
            original_decisions = decisions_path.read_bytes()
            tampered = json.loads(original_decisions.decode("utf-8")); tampered["decisions"]["DEC-001"]["decision_quote"] = "授权后篡改"
            decisions_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.run_cli("submit", project, "P00", "--summary", "不应接受治理快照漂移", ok=False)
            decisions_path.write_bytes(original_decisions)
            self.run_cli("submit", project, "P00", "--summary", "忠实执行用户内容")
            self.run_cli("accept", project, "P00", "--approval-ref", "用户最终决定 DEC-001")
            advice = json.loads((project / "stages/P00/content-advice.json").read_text(encoding="utf-8"))["items"]
            self.assertEqual(advice["ADV-001"]["status"], "REJECTED")
            self.assertTrue(all(item["gate_effect"] == "NONE" for item in advice.values()))
            subprocess.run([sys.executable, str(VALIDATE), str(project)], check=True, text=True, encoding="utf-8", capture_output=True)

    def test_objective_high_blocks_until_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "demo"
            self.run_cli("init", project, "--name", "客观门禁测试", "--pm-session-id", "pm-2")
            self.run_cli("register", project, "P00", "--session-id", "p00-2")
            self.prepare_manifest(project)
            self.run_cli(
                "record-issue", project, "P00", "--issue-id", "TECH-001", "--severity", "HIGH",
                "--category", "MEDIA_DECODE", "--description", "输出文件无法解码", "--evidence", "ffprobe 失败",
            )
            self.authorize(project, ok=False)
            self.run_cli(
                "record-owner-decision", project, "P00", "--decision-id", "DEC-TECH",
                "--decision", "KEEP_ORIGINAL", "--scope", "内容", "--decision-quote", "内容保持不变",
                "--resolve-issue", "TECH-001", ok=False,
            )
            decisions = json.loads((project / "stages/P00/owner-decisions.json").read_text(encoding="utf-8"))["decisions"]
            self.assertNotIn("DEC-TECH", decisions)
            self.run_cli("resolve-issue", project, "P00", "--issue-id", "TECH-001", "--resolution", "FIXED", "--evidence", "ffprobe 复测通过")
            self.authorize(project)

    def test_migration_requires_explicit_legacy_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "legacy"
            self.run_cli("init", project, "--name", "迁移测试", "--pm-session-id", "pm-3")
            control = project / "00_control"
            for name in ("project-config.json", "project-state.json", "session-registry.json"):
                path = control / name; data = json.loads(path.read_text(encoding="utf-8")); data["schema_version"] = "1.2"
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result_path = project / "stages/P03/stage-result.json"
            result = json.loads(result_path.read_text(encoding="utf-8")); result["issues"]["HIGH"] = 2
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            config_path = control / "project-config.json"
            config_before = config_path.read_bytes()
            self.run_cli("migrate-governance", project, ok=False)
            self.run_cli("migrate-governance", project, "--legacy-phase-classification", "P03=ADVISORY")
            self.assertEqual(config_path.read_bytes(), config_before)
            migrated = json.loads((project / "stages/P03/content-advice.json").read_text(encoding="utf-8"))["items"]
            self.assertEqual(len(migrated), 2)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["issues"]["HIGH"], 0)

    def test_migrated_legacy_user_gate_keeps_old_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "legacy-accepted"
            self.run_cli("init", project, "--name", "旧验收迁移", "--pm-session-id", "pm-4")
            self.run_cli("register", project, "P00", "--session-id", "p00-4")
            self.prepare_manifest(project)
            state_path = project / "00_control/project-state.json"
            registry_path = project / "00_control/session-registry.json"
            result_path = project / "stages/P00/stage-result.json"
            state = json.loads(state_path.read_text(encoding="utf-8")); state["schema_version"] = "1.0"; state["phase_status"]["P00"] = "ACCEPTED"
            registry = json.loads(registry_path.read_text(encoding="utf-8")); registry["schema_version"] = "1.0"; registry["stages"][0]["status"] = "ACCEPTED"
            result = json.loads(result_path.read_text(encoding="utf-8")); result["status"] = "SUBMITTED"
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.run_cli("migrate-governance", project)
            validated = subprocess.run([sys.executable, str(VALIDATE), str(project)], text=True, encoding="utf-8", capture_output=True, check=False)
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)


if __name__ == "__main__":
    unittest.main()
