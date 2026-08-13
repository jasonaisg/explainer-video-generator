from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTCTL = ROOT / "scripts" / "projectctl.py"
CHANGE = ROOT / "scripts" / "change_control.py"
VALIDATE = ROOT / "scripts" / "validate_project.py"
BUILD_MANIFEST = ROOT / "scripts" / "build_manifest.py"


class ChangeControlFlowTest(unittest.TestCase):
    def run_cli(self, script: Path, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(script), *map(str, args)],
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

    def test_selective_rework_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "demo"
            self.run_cli(PROJECTCTL, "init", project, "--name", "依赖测试", "--pm-session-id", "pm-1")
            artifacts = project / "artifacts"; artifacts.mkdir()
            for name, content in {"a.txt": "时间轴 v1", "b.txt": "动效 v1", "c.txt": "技术报告 v1", "d.txt": "无关交付 v1"}.items():
                (artifacts / name).write_text(content, encoding="utf-8")

            self.run_cli(CHANGE, "register-artifact", project, "--artifact-id", "timeline.master", "--path", "artifacts/a.txt", "--phase", "P02", "--version", "v1")
            self.run_cli(CHANGE, "register-artifact", project, "--artifact-id", "design.motion", "--path", "artifacts/b.txt", "--phase", "P05", "--version", "v1", "--depends-on", "timeline.master:REBUILD")
            self.run_cli(CHANGE, "register-artifact", project, "--artifact-id", "report.technical", "--path", "artifacts/c.txt", "--phase", "P08", "--version", "v1", "--depends-on", "design.motion:VERIFY")
            self.run_cli(CHANGE, "register-artifact", project, "--artifact-id", "delivery.unrelated", "--path", "artifacts/d.txt", "--phase", "P12", "--version", "v1")

            self.run_cli(CHANGE, "create-request", project, "--title", "修正时间轴", "--description", "修正一句字幕时间", "--reason", "用户复查", "--requested-by", "用户", "--request-quote", "请把这句时间改一下", "--target", "timeline.master")
            self.run_cli(CHANGE, "analyze", project, "CR-0001")
            analysis = json.loads((project / "00_control/change-requests/CR-0001/impact-analysis.json").read_text(encoding="utf-8"))
            modes = {item["artifact_id"]: item["mode"] for item in analysis["impacted_artifacts"]}
            self.assertEqual(modes, {"timeline.master": "REBUILD", "design.motion": "REBUILD", "report.technical": "VERIFY"})
            self.assertIn("delivery.unrelated", analysis["unaffected_artifacts"])

            self.run_cli(CHANGE, "approve-plan", project, "CR-0001", "--approved-by", "用户", "--approval-quote", "批准按这个影响范围返工")
            self.run_cli(CHANGE, "issue-orders", project, "CR-0001")
            self.run_cli(VALIDATE, project)
            orders = [json.loads((project / f"00_control/rework-orders/RW-0001-{i:02d}/work-order.json").read_text(encoding="utf-8")) for i in range(1, 4)]
            self.assertEqual([item["status"] for item in orders], ["READY", "BLOCKED", "BLOCKED"])
            self.run_cli(CHANGE, "assign-order", project, "RW-0001-01", "--session-id", "replacement-p02", "--reason", "原 Session 已归档")

            self.run_cli(CHANGE, "start-order", project, "RW-0001-01")
            (artifacts / "a-v2.txt").write_text("时间轴 v2", encoding="utf-8")
            self.run_cli(CHANGE, "update-artifact", project, "RW-0001-01", "--artifact-id", "timeline.master", "--path", "artifacts/a-v2.txt", "--version", "v2")
            self.run_cli(CHANGE, "authorize-order", project, "RW-0001-01", "--authorized-by", "用户", "--authorization-quote", "可以提交项目经理")
            self.run_cli(CHANGE, "record-review", project, "RW-0001-01", "--item-id", "Q1", "--status", "OPEN", "--message", "再解释一下时间点")
            self.run_cli(CHANGE, "submit-order", project, "RW-0001-01", "--summary", "不应成功", ok=False)
            self.run_cli(CHANGE, "record-review", project, "RW-0001-01", "--item-id", "Q1", "--status", "CLOSED", "--message", "已解释并确认")
            self.run_cli(CHANGE, "record-advice", project, "RW-0001-01", "--advice-id", "ADV-1", "--topic", "措辞", "--recommendation", "建议改写", "--rationale", "Agent 参考意见")
            self.run_cli(CHANGE, "record-owner-decision", project, "RW-0001-01", "--decision-id", "DEC-1", "--decision", "KEEP_ORIGINAL", "--scope", "返工产物措辞", "--decision-quote", "保留我的内容", "--advice-id", "ADV-1", "--advice-disposition", "REJECTED")
            self.run_cli(CHANGE, "authorize-order", project, "RW-0001-01", "--authorized-by", "用户", "--authorization-quote", "现在可以提交项目经理")
            self.run_cli(CHANGE, "record-advice", project, "RW-0001-01", "--advice-id", "ADV-2", "--topic", "风格", "--recommendation", "建议换色", "--rationale", "仅供参考")
            self.run_cli(CHANGE, "submit-order", project, "RW-0001-01", "--summary", "时间轴已修正")
            self.run_cli(CHANGE, "accept-order", project, "RW-0001-01", "--evidence", "时间轴校验通过")

            second = json.loads((project / "00_control/rework-orders/RW-0001-02/work-order.json").read_text(encoding="utf-8"))
            self.assertEqual(second["status"], "READY")
            self.run_cli(CHANGE, "start-order", project, "RW-0001-02")
            (artifacts / "b-v2.txt").write_text("动效 v2", encoding="utf-8")
            self.run_cli(CHANGE, "update-artifact", project, "RW-0001-02", "--artifact-id", "design.motion", "--path", "artifacts/b-v2.txt", "--version", "v2")
            self.run_cli(CHANGE, "authorize-order", project, "RW-0001-02", "--authorized-by", "用户", "--authorization-quote", "可以提交项目经理")
            self.run_cli(CHANGE, "submit-order", project, "RW-0001-02", "--summary", "动效已更新")
            self.run_cli(CHANGE, "accept-order", project, "RW-0001-02", "--evidence", "动效回归通过")

            third = json.loads((project / "00_control/rework-orders/RW-0001-03/work-order.json").read_text(encoding="utf-8"))
            self.assertEqual(third["status"], "READY")
            self.run_cli(CHANGE, "start-order", project, "RW-0001-03")
            self.run_cli(CHANGE, "verify-artifact", project, "RW-0001-03", "--artifact-id", "report.technical", "--evidence", "报告内容与时间轴字段解耦，回归检查通过")
            self.run_cli(CHANGE, "authorize-order", project, "RW-0001-03", "--authorized-by", "用户", "--authorization-quote", "可以提交项目经理")
            self.run_cli(CHANGE, "submit-order", project, "RW-0001-03", "--summary", "技术报告无需改字节，验证通过")
            self.run_cli(CHANGE, "accept-order", project, "RW-0001-03", "--evidence", "回归证据已核对")
            self.run_cli(CHANGE, "close-request", project, "CR-0001", "--evidence", "三张工单全部验收")

            graph = json.loads((project / "00_control/artifact-dependency-graph.json").read_text(encoding="utf-8"))
            self.assertTrue(all(node["status"] == "VALID" for node in graph["nodes"].values()))
            self.assertEqual(graph["nodes"]["delivery.unrelated"]["version"], "v1")
            self.assertEqual((artifacts / "a.txt").read_text(encoding="utf-8"), "时间轴 v1")
            request = json.loads((project / "00_control/change-requests/CR-0001/change-request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["status"], "CLOSED")
            self.run_cli(VALIDATE, project)

    def test_manifest_metadata_can_populate_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "demo"
            self.run_cli(PROJECTCTL, "init", project, "--name", "清单导入", "--pm-session-id", "pm-2")
            outputs = project / "03_content_plan"; outputs.mkdir(exist_ok=True)
            (outputs / "source.json").write_text("{}", encoding="utf-8")
            (outputs / "timeline.json").write_text('{"duration": 1}', encoding="utf-8")
            self.run_cli(CHANGE, "register-artifact", project, "--artifact-id", "media.sync", "--path", "03_content_plan/source.json", "--phase", "P01", "--version", "v1", "--type", "DATA")
            artifact_map = project / "artifact-map.json"
            artifact_map.write_text(json.dumps({
                "03_content_plan/timeline.json": {
                    "artifact_id": "timeline.master", "version": "v1", "type": "DATA",
                    "depends_on": [{"artifact_id": "media.sync", "propagation": "REBUILD"}],
                }
            }, ensure_ascii=False), encoding="utf-8")
            self.run_cli(BUILD_MANIFEST, project, "P02", "03_content_plan/timeline.json", "--artifact-map", artifact_map)
            self.run_cli(CHANGE, "import-manifest", project, "--manifest", "stages/P02/deliverables-manifest.json")
            graph = json.loads((project / "00_control/artifact-dependency-graph.json").read_text(encoding="utf-8"))
            self.assertEqual(graph["nodes"]["timeline.master"]["depends_on"], [{"artifact_id": "media.sync", "propagation": "REBUILD"}])

    def test_bootstrap_migrates_legacy_control_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "legacy"
            self.run_cli(PROJECTCTL, "init", project, "--name", "旧项目", "--pm-session-id", "pm-3")
            control = project / "00_control"
            for name in ("project-config.json", "project-state.json", "session-registry.json"):
                path = control / name; data = json.loads(path.read_text(encoding="utf-8")); data["schema_version"] = "1.1"
                if name == "project-state.json":
                    data.pop("active_change_requests", None); data.pop("rework_orders", None)
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (control / "artifact-dependency-graph.json").unlink()
            (control / "change-control-state.json").unlink()
            self.run_cli(CHANGE, "bootstrap", project)
            state = json.loads((control / "project-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["schema_version"], "1.2")
            self.assertEqual(state["active_change_requests"], [])
            self.assertTrue((control / "artifact-dependency-graph.json").is_file())
            self.run_cli(VALIDATE, project)


if __name__ == "__main__":
    unittest.main()
