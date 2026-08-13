#!/usr/bin/env python3
"""Validate explainer-video project structure and orchestration state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

PHASES = [f"P{i:02d}" for i in range(15)]
USER_GATES = {"P00", "P04", "P05", "P07", "P08", "P10", "P14"}
VALID_PHASE_STATES = {"NOT_STARTED", "READY", "IN_PROGRESS", "SELF_CHECK", "USER_REVIEW", "SUBMISSION_AUTHORIZED", "SUBMITTED", "REVISION_REQUIRED", "ACCEPTED", "STALE", "BLOCKED"}
VALID_ARTIFACT_STATES = {"VALID", "REWORK_REQUIRED", "VERIFY_REQUIRED", "PENDING_REVIEW", "RETIRED"}
VALID_ORDER_STATES = {"BLOCKED", "READY", "IN_PROGRESS", "WAITING_USER", "SUBMISSION_AUTHORIZED", "SUBMITTED", "ACCEPTED", "CANCELLED"}
FILES = ("task-packet.md", "stage-result.json", "deliverables-manifest.json", "handoff.md", "open-issues.md", "approval-record.md")
GOVERNANCE_FILES = ("content-advice.json", "owner-decisions.json", "review-items.json", "stage-issues.json")
OBJECTIVE_ISSUE_CATEGORIES = {
    "INPUT_MISSING", "FILE_INTEGRITY", "HASH_DRIFT", "MEDIA_DECODE", "MEDIA_SYNC",
    "CONFIG_CONFORMANCE", "RENDER_FAILURE", "RIGHTS_EVIDENCE", "OUTPUT_MISSING",
    "TECHNICAL_VALIDATION", "USER_DECISION_PENDING", "LEGACY_OBJECTIVE_REVIEW",
}


def load(path: Path, errors: list[str]) -> dict:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: errors.append(f"无法读取 JSON {path}: {exc}"); return {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def governance_snapshot(folder: Path) -> str:
    digest = hashlib.sha256()
    for filename in ("owner-decisions.json", "review-items.json", "stage-issues.json"):
        path = folder / filename
        digest.update(filename.encode("utf-8")); digest.update(b"\0"); digest.update(path.read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def schema_at_least(value: object, major: int, minor: int) -> bool:
    try:
        parts = str(value).split(".")
        return (int(parts[0]), int(parts[1])) >= (major, minor)
    except (ValueError, IndexError):
        return False


def validate_change_control(root: Path, state: dict, errors: list[str], warnings: list[str]) -> None:
    control = root / "00_control"; graph_path = control / "artifact-dependency-graph.json"
    if not graph_path.is_file():
        if schema_at_least(state.get("schema_version"), 1, 2): errors.append("1.2 项目缺少 artifact-dependency-graph.json")
        else: warnings.append("尚未启用 1.2 产物依赖图；首次变更前运行 change_control.py bootstrap")
        return
    graph = load(graph_path, errors); nodes = graph.get("nodes", {})
    if not isinstance(nodes, dict): errors.append("artifact-dependency-graph.nodes 必须为对象"); return
    visiting: set[str] = set(); visited: set[str] = set()
    def visit(node_id: str) -> None:
        if node_id in visiting: errors.append(f"产物依赖图存在环：{node_id}"); return
        if node_id in visited: return
        visiting.add(node_id)
        node = nodes.get(node_id, {})
        if node.get("artifact_id") != node_id: errors.append(f"产物节点 ID 不一致：{node_id}")
        if node.get("producer_phase") not in PHASES: errors.append(f"{node_id} producer_phase 非法")
        if node.get("status") not in VALID_ARTIFACT_STATES: errors.append(f"{node_id} 状态非法：{node.get('status')}")
        for dep in node.get("depends_on", []):
            other = dep.get("artifact_id"); mode = dep.get("propagation")
            if other not in nodes: errors.append(f"{node_id} 引用了不存在的依赖：{other}")
            elif other not in visiting: visit(other)
            else: errors.append(f"产物依赖图存在环：{node_id} -> {other}")
            if mode not in {"REBUILD", "VERIFY"}: errors.append(f"{node_id} 传播模式非法：{mode}")
        path_value = node.get("path")
        if path_value and node.get("status") in {"VALID", "PENDING_REVIEW"}:
            target = Path(path_value)
            if not target.is_absolute(): target = root / target
            if not target.is_file(): errors.append(f"有效产物文件不存在：{node_id} -> {path_value}")
            elif node.get("sha256") and sha256(target) != str(node["sha256"]).lower(): errors.append(f"有效产物哈希漂移：{node_id}")
        visiting.discard(node_id); visited.add(node_id)
    for node_id in nodes: visit(node_id)
    for cr_id in state.get("active_change_requests", []):
        path = control / "change-requests" / cr_id / "change-request.json"
        if not path.is_file(): errors.append(f"活动变更请求不存在：{cr_id}")
        elif load(path, errors).get("status") in {"CLOSED", "REJECTED"}: errors.append(f"活动变更请求状态矛盾：{cr_id}")
    for order_id, summary in state.get("rework_orders", {}).items():
        path = control / "rework-orders" / order_id / "work-order.json"
        if not path.is_file(): errors.append(f"返工工单不存在：{order_id}"); continue
        order = load(path, errors)
        if order.get("status") not in VALID_ORDER_STATES: errors.append(f"{order_id} 状态非法：{order.get('status')}")
        if order.get("status") != summary.get("status"): errors.append(f"{order_id} 与 project-state 状态不一致")
        for advice_id, advice in order.get("advisory_items", {}).items():
            if advice.get("gate_effect") != "NONE": errors.append(f"{order_id} 内容建议不得产生门禁：{advice_id}")
        for decision_id, decision in order.get("owner_decisions", {}).items():
            if decision.get("status") != "BINDING" or not str(decision.get("quote", "")).strip(): errors.append(f"{order_id} 用户最终决定无效：{decision_id}")
        for artifact_id in order.get("rebuild_artifacts", []) + order.get("verify_artifacts", []):
            if artifact_id not in nodes: errors.append(f"{order_id} 引用了不存在的产物：{artifact_id}")


def validate_governance(folder: Path, phase: str, result: dict, accepted: bool, errors: list[str]) -> bool:
    loaded: dict[str, dict] = {}
    for filename in GOVERNANCE_FILES:
        path = folder / filename
        if not path.is_file(): errors.append(f"1.3 项目缺少：{path}"); continue
        loaded[filename] = load(path, errors)
    advice = loaded.get("content-advice.json", {}).get("items", {})
    for advice_id, item in advice.items():
        if item.get("advice_id") != advice_id: errors.append(f"{phase} 内容建议 ID 不一致：{advice_id}")
        if item.get("gate_effect") != "NONE": errors.append(f"{phase} 内容建议不得产生门禁：{advice_id}")
        if item.get("status") not in {"PRESENTED", "ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "NOTED"}: errors.append(f"{phase} 内容建议状态非法：{advice_id}")
    decisions = loaded.get("owner-decisions.json", {}).get("decisions", {})
    for decision_id, item in decisions.items():
        if item.get("decision_id") != decision_id or item.get("status") != "BINDING": errors.append(f"{phase} 用户最终决定无效：{decision_id}")
        if not str(item.get("decision_quote", "")).strip(): errors.append(f"{phase} 用户最终决定缺少原话：{decision_id}")
        for advice_id in item.get("advice_ids", []):
            if advice_id not in advice: errors.append(f"{phase} 用户决定引用不存在的内容建议：{advice_id}")
    reviews = loaded.get("review-items.json", {}).get("items", {})
    for review_id, item in reviews.items():
        if item.get("item_id") != review_id: errors.append(f"{phase} 用户要求 ID 不一致：{review_id}")
        if item.get("status") not in {"OPEN", "CLOSED"}: errors.append(f"{phase} 用户要求状态非法：{review_id}")
    open_reviews = [key for key, item in reviews.items() if item.get("status") == "OPEN"]
    issues = loaded.get("stage-issues.json", {}).get("items", {})
    counts = {level: 0 for level in ("BLOCKER", "HIGH", "MEDIUM", "LOW")}
    open_blocking: list[str] = []
    for issue_id, item in issues.items():
        if item.get("issue_id") != issue_id: errors.append(f"{phase} 客观问题 ID 不一致：{issue_id}")
        if item.get("category") not in OBJECTIVE_ISSUE_CATEGORIES: errors.append(f"{phase} 客观问题类别非法或属于内容判断：{issue_id}")
        if item.get("status") not in {"OPEN", "CLOSED"}: errors.append(f"{phase} 客观问题状态非法：{issue_id}")
        severity = item.get("severity")
        if severity not in counts: errors.append(f"{phase} 客观问题等级非法：{issue_id}")
        elif item.get("status") == "OPEN": counts[severity] += 1
        expected_gate = "BLOCKING" if severity in {"BLOCKER", "HIGH"} else "NON_BLOCKING"
        if item.get("gate_effect") != expected_gate: errors.append(f"{phase} 客观问题门禁与等级不一致：{issue_id}")
        if item.get("status") == "OPEN" and item.get("gate_effect") == "BLOCKING": open_blocking.append(issue_id)
    if result.get("issues") != counts: errors.append(f"{phase} stage-result 问题计数不是 stage-issues.json 的派生结果")
    if accepted and open_reviews: errors.append(f"{phase} 已验收但仍有未完成用户要求：{open_reviews}")
    if accepted and open_blocking: errors.append(f"{phase} 已验收但仍有开放客观阻断问题：{open_blocking}")
    return bool(result.get("requires_submission_authorization"))


def validate(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []; warnings: list[str] = []
    control = root / "00_control"
    required = [control / "project-config.json", control / "project-state.json", control / "session-registry.json"]
    for path in required:
        if not path.is_file(): errors.append(f"缺少：{path}")
    if errors: return errors, warnings
    config = load(required[0], errors); state = load(required[1], errors); registry = load(required[2], errors)
    phase_status = state.get("phase_status", {})
    if set(phase_status) != set(PHASES): errors.append("phase_status 必须且只能包含 P00–P14")
    for phase, value in phase_status.items():
        if value not in VALID_PHASE_STATES: errors.append(f"{phase} 状态非法：{value}")
    accepted_gap = False
    for phase in PHASES:
        if phase_status.get(phase) != "ACCEPTED": accepted_gap = True
        elif accepted_gap: errors.append(f"阶段非连续验收：{phase} 已 ACCEPTED，但前序未全部通过")
        folder = root / "stages" / phase
        for name in FILES:
            if not (folder / name).is_file(): errors.append(f"缺少：{folder / name}")
        result_path = folder / "stage-result.json"
        result = load(result_path, errors) if result_path.is_file() else {}
        dynamic_user_gate = False
        if schema_at_least(state.get("schema_version"), 1, 3):
            dynamic_user_gate = validate_governance(folder, phase, result, phase_status.get(phase) == "ACCEPTED", errors)
        manifest_path = folder / "deliverables-manifest.json"
        if manifest_path.is_file():
            manifest = load(manifest_path, errors)
            if schema_at_least(state.get("schema_version"), 1, 3):
                reserved = {f"stages/{phase}/{name}" for name in ("approval-record.md", "stage-result.json", "open-issues.md", *GOVERNANCE_FILES)}
                listed = {str(item.get("path", "")).replace("\\", "/") for item in manifest.get("files", [])}
                if reserved & listed: errors.append(f"{phase} 交付清单包含可变治理控制记录：{sorted(reserved & listed)}")
            if phase_status.get(phase) == "ACCEPTED" and not manifest.get("files"):
                errors.append(f"{phase} 已验收但交付物清单为空")
            for item in manifest.get("files", []):
                rel = item.get("path", ""); target = (root / rel).resolve()
                try: target.relative_to(root)
                except ValueError: errors.append(f"{phase} manifest 路径越出项目：{rel}"); continue
                if not rel or not target.is_file(): errors.append(f"{phase} manifest 文件不存在：{rel}"); continue
                expected = item.get("sha256")
                if expected and sha256(target) != str(expected).lower(): errors.append(f"{phase} manifest 哈希漂移：{rel}")
        handoff = folder / "handoff.md"
        if phase_status.get(phase) == "ACCEPTED" and handoff.is_file() and len(handoff.read_text(encoding="utf-8").strip().splitlines()) < 3:
            errors.append(f"{phase} 已验收但 handoff 内容为空")
        approval = folder / "approval-record.md"
        requires_authorization = phase in USER_GATES or dynamic_user_gate
        if requires_authorization and phase_status.get(phase) == "ACCEPTED" and approval.is_file() and schema_at_least(state.get("schema_version"), 1, 1):
            text = approval.read_text(encoding="utf-8")
            events = list(re.finditer(r"(?m)^##\s+(审阅互动|内容意见|提交授权)\b[^\n]*$", text))
            latest = text[events[-1].start():] if events else ""
            if not events or events[-1].group(1) != "提交授权" or "授权状态：`SUBMISSION_AUTHORIZED`" not in latest:
                errors.append(f"{phase} 已验收但最新互动事件不是有效提交授权")
            manifest_hash = re.search(r"交付清单 SHA-256：`?([0-9a-fA-F]{64})`?", latest)
            if not manifest_hash or not manifest_path.is_file() or sha256(manifest_path) != manifest_hash.group(1).lower():
                errors.append(f"{phase} 已验收但提交授权绑定的交付清单已变化")
            accepted_under = result.get("accepted_under_schema", state.get("schema_version"))
            if schema_at_least(state.get("schema_version"), 1, 3) and schema_at_least(accepted_under, 1, 3):
                governance_hash = re.search(r"治理快照 SHA-256：`?([0-9a-fA-F]{64})`?", latest)
                if not governance_hash or governance_snapshot(folder) != governance_hash.group(1).lower():
                    errors.append(f"{phase} 已验收但提交授权绑定的治理快照已变化")
            elif schema_at_least(state.get("schema_version"), 1, 3):
                warnings.append(f"{phase} 在治理协议 {accepted_under} 下已验收，保留历史授权且不倒追治理快照")
        elif requires_authorization and phase_status.get(phase) == "ACCEPTED" and not schema_at_least(state.get("schema_version"), 1, 1):
            warnings.append(f"{phase} 使用 1.0 旧审批协议，保留历史验收；后续阶段须使用 SUBMISSION_AUTHORIZED")
    stages = registry.get("stages", [])
    if [x.get("phase") for x in stages] != PHASES: errors.append("session-registry stages 必须按 P00–P14 排列")
    for entry in stages:
        phase = entry.get("phase")
        if phase_status.get(phase) == "ACCEPTED" and entry.get("session_id") == "UNASSIGNED": errors.append(f"{phase} 已验收但无真实 Session ID")
    if config.get("source", {}).get("picture_locked") is not True: errors.append("source.picture_locked 必须为 true")
    if config.get("source", {}).get("canonical_audio") != "audio_mp3": warnings.append("canonical_audio 不是建议的 audio_mp3")
    if config.get("presenter", {}).get("always_visible") is not True: errors.append("presenter.always_visible 必须为 true")
    if config.get("backend", {}).get("name") != "hyperframes": errors.append("backend.name 必须为 hyperframes")
    environment = config.get("environment", {})
    if environment.get("discovery") != "AUTO": warnings.append("environment.discovery 不是 AUTO；确认这是当前项目的显式配置")
    report_value = environment.get("report", "")
    if not report_value:
        warnings.append("尚未配置环境报告路径")
    else:
        report_path = Path(report_value)
        if not report_path.is_absolute(): report_path = root / report_path
        if not report_path.is_file():
            warnings.append(f"环境报告尚不存在：{report_value}")
        else:
            report = load(report_path, errors)
            if report.get("schema_version") != "1.0": warnings.append("环境报告 schema_version 未识别")
            if report.get("python", {}).get("available") is not True: errors.append("环境报告未确认兼容的 Python 3")
    for key in ("video_mp4", "audio_mp3", "script", "original_config"):
        if not config.get("source", {}).get(key): warnings.append(f"尚未填写 source.{key}")
    current = state.get("current_phase")
    if state.get("project_status") not in {"COMPLETE", "CHANGE_IN_PROGRESS"} and current not in PHASES: errors.append("活动项目的 current_phase 非法")
    validate_change_control(root, state, errors, warnings)
    return errors, warnings


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("root"); args = p.parse_args()
    root = Path(args.root).resolve(); errors, warnings = validate(root)
    for item in warnings: print(f"WARN: {item}")
    for item in errors: print(f"ERROR: {item}")
    if errors: print(f"项目校验失败：{len(errors)} error, {len(warnings)} warning"); return 1
    print(f"项目结构与状态校验通过：{root}（{len(warnings)} warning）"); return 0


if __name__ == "__main__": raise SystemExit(main())
