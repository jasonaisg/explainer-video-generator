#!/usr/bin/env python3
"""管理产物级依赖图、变更请求和选择性返工工单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PHASES = [f"P{i:02d}" for i in range(15)]
ARTIFACT_STATES = {"VALID", "REWORK_REQUIRED", "VERIFY_REQUIRED", "PENDING_REVIEW", "RETIRED"}
ORDER_STATES = {"BLOCKED", "READY", "IN_PROGRESS", "WAITING_USER", "SUBMISSION_AUTHORIZED", "SUBMITTED", "ACCEPTED", "CANCELLED"}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def control(root: Path) -> Path:
    return root / "00_control"


def graph_path(root: Path) -> Path:
    return control(root) / "artifact-dependency-graph.json"


def cr_dir(root: Path, cr_id: str) -> Path:
    return control(root) / "change-requests" / cr_id


def order_dir(root: Path, order_id: str) -> Path:
    return control(root) / "rework-orders" / order_id


def project_path(root: Path, value: str) -> tuple[Path, str]:
    target = Path(value)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        stored = target.relative_to(root).as_posix()
    except ValueError:
        stored = str(target)
    return target, stored


def version_tuple(value: object) -> tuple[int, int]:
    try:
        parts = str(value).split("."); return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return 0, 0


def bootstrap(root: Path) -> None:
    ctl = control(root)
    if not (ctl / "project-state.json").is_file():
        raise SystemExit("项目尚未初始化：缺少 00_control/project-state.json")
    (ctl / "change-requests").mkdir(parents=True, exist_ok=True)
    (ctl / "rework-orders").mkdir(parents=True, exist_ok=True)
    if not graph_path(root).is_file():
        write(graph_path(root), {"schema_version": "1.0", "revision": 0, "updated_at": now(), "nodes": {}})
    counter = ctl / "change-control-state.json"
    if not counter.is_file():
        existing = [int(m.group(1)) for p in (ctl / "change-requests").glob("CR-*") if (m := re.fullmatch(r"CR-(\d{4})", p.name))]
        write(counter, {"schema_version": "1.0", "next_change_request": max(existing, default=0) + 1, "updated_at": now()})
    for name in ("project-config.json", "project-state.json", "session-registry.json"):
        path = ctl / name
        if path.is_file():
            data = load(path)
            if version_tuple(data.get("schema_version")) < (1, 2):
                data["schema_version"] = "1.2"
                write(path, data)
    state_path = ctl / "project-state.json"; state = load(state_path)
    changed = False
    if "active_change_requests" not in state:
        state["active_change_requests"] = []; changed = True
    if "rework_orders" not in state:
        state["rework_orders"] = {}; changed = True
    if changed:
        state["updated_at"] = now(); write(state_path, state)


def parse_dependencies(values: list[str]) -> list[dict]:
    result = []
    seen = set()
    for value in values:
        artifact_id, sep, mode = value.partition(":")
        mode = mode.upper() if sep else "REBUILD"
        if not artifact_id or mode not in {"REBUILD", "VERIFY"}:
            raise SystemExit(f"依赖格式非法：{value}；使用 ARTIFACT_ID[:REBUILD|VERIFY]")
        if artifact_id not in seen:
            result.append({"artifact_id": artifact_id, "propagation": mode}); seen.add(artifact_id)
    return result


def assert_acyclic(nodes: dict) -> None:
    visiting: set[str] = set(); visited: set[str] = set()
    def visit(node_id: str) -> None:
        if node_id in visiting: raise SystemExit(f"产物依赖图存在环：{node_id}")
        if node_id in visited: return
        visiting.add(node_id)
        for dep in nodes[node_id].get("depends_on", []):
            other = dep["artifact_id"]
            if other not in nodes: raise SystemExit(f"{node_id} 引用了不存在的依赖：{other}")
            visit(other)
        visiting.remove(node_id); visited.add(node_id)
    for node_id in nodes: visit(node_id)


def save_graph(root: Path, graph: dict) -> None:
    assert_acyclic(graph["nodes"])
    graph["revision"] = int(graph.get("revision", 0)) + 1
    graph["updated_at"] = now(); write(graph_path(root), graph)


def register_artifact(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); graph = load(graph_path(root))
    if args.phase not in PHASES: raise SystemExit("--phase 必须为 P00–P14；原始输入由 P00 登记")
    target, stored = project_path(root, args.path)
    if not target.is_file(): raise SystemExit(f"产物文件不存在：{target}")
    dependencies = parse_dependencies(args.depends_on or [])
    for dep in dependencies:
        if dep["artifact_id"] not in graph["nodes"]: raise SystemExit(f"依赖尚未登记：{dep['artifact_id']}")
    new_digest = digest(target); old = graph["nodes"].get(args.artifact_id)
    if old and old.get("status") in {"REWORK_REQUIRED", "VERIFY_REQUIRED"}:
        raise SystemExit("失效产物只能通过 update-artifact 或 verify-artifact 在对应返工工单中处理")
    state = load(control(root) / "project-state.json")
    if old and state.get("phase_status", {}).get(old.get("producer_phase")) == "ACCEPTED":
        changed = (stored, args.version, new_digest, dependencies, args.phase, args.type) != (old.get("path"), old.get("version"), old.get("sha256"), old.get("depends_on", []), old.get("producer_phase"), old.get("type"))
        if changed: raise SystemExit("已验收产物不得通过普通登记更新；必须创建变更请求和返工工单")
    history = list(old.get("history", [])) if old else []
    if old:
        history.append({k: old.get(k) for k in ("path", "version", "sha256", "status", "updated_at")})
    graph["nodes"][args.artifact_id] = {
        "artifact_id": args.artifact_id, "path": stored, "type": args.type,
        "producer_phase": args.phase, "version": args.version, "sha256": new_digest,
        "status": "VALID", "depends_on": dependencies, "updated_at": now(), "history": history,
    }
    save_graph(root, graph); print(f"已登记产物：{args.artifact_id} -> {stored}")


def import_manifest(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); graph = load(graph_path(root))
    manifest_path, _ = project_path(root, args.manifest)
    if not manifest_path.is_file(): raise SystemExit(f"交付清单不存在：{manifest_path}")
    manifest = load(manifest_path); phase = manifest.get("phase")
    if phase not in PHASES: raise SystemExit("交付清单 phase 必须为 P00–P14")
    pending = {}
    for item in manifest.get("files", []):
        artifact_id = item.get("artifact_id")
        if not artifact_id: continue
        required = ("path", "version", "type", "depends_on", "sha256")
        missing = [key for key in required if key not in item]
        if missing: raise SystemExit(f"{artifact_id} 缺少依赖图字段：{missing}")
        pending[artifact_id] = item
    if not pending: raise SystemExit("交付清单没有带 artifact_id 的产物")
    imported = []
    while pending:
        progressed = False
        for artifact_id, item in list(pending.items()):
            dependencies = item["depends_on"]
            if not isinstance(dependencies, list): raise SystemExit(f"{artifact_id}.depends_on 必须为数组")
            parsed = []
            for dep in dependencies:
                if isinstance(dep, str): parsed.extend(parse_dependencies([dep]))
                elif isinstance(dep, dict) and dep.get("artifact_id") and dep.get("propagation") in {"REBUILD", "VERIFY"}: parsed.append({"artifact_id": dep["artifact_id"], "propagation": dep["propagation"]})
                else: raise SystemExit(f"{artifact_id} 的依赖项非法：{dep}")
            if any(dep["artifact_id"] not in graph["nodes"] and dep["artifact_id"] not in imported for dep in parsed): continue
            target, stored = project_path(root, item["path"])
            if not target.is_file() or digest(target) != str(item["sha256"]).lower(): raise SystemExit(f"{artifact_id} 的文件或清单哈希无效")
            old = graph["nodes"].get(artifact_id); history = list(old.get("history", [])) if old else []
            if old and old.get("status") in {"REWORK_REQUIRED", "VERIFY_REQUIRED"}: raise SystemExit(f"{artifact_id} 已进入返工，不能通过普通清单覆盖")
            state = load(control(root) / "project-state.json")
            if old and state.get("phase_status", {}).get(old.get("producer_phase")) == "ACCEPTED":
                changed = (stored, item["version"], str(item["sha256"]).lower(), parsed, phase, item["type"]) != (old.get("path"), old.get("version"), old.get("sha256"), old.get("depends_on", []), old.get("producer_phase"), old.get("type"))
                if changed: raise SystemExit(f"{artifact_id} 已验收，必须通过变更请求和返工工单更新")
            if old: history.append({k: old.get(k) for k in ("path", "version", "sha256", "status", "updated_at")})
            graph["nodes"][artifact_id] = {"artifact_id": artifact_id, "path": stored, "type": item["type"], "producer_phase": phase, "version": item["version"], "sha256": str(item["sha256"]).lower(), "status": "VALID", "depends_on": parsed, "updated_at": now(), "history": history}
            imported.append(artifact_id); del pending[artifact_id]; progressed = True
        if not progressed: raise SystemExit(f"无法导入清单；存在缺失依赖或循环：{sorted(pending)}")
    save_graph(root, graph); print(f"已从交付清单导入 {len(imported)} 个产物节点")


def create_request(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); graph = load(graph_path(root))
    targets = list(dict.fromkeys(args.target))
    missing = [item for item in targets if item not in graph["nodes"]]
    if missing: raise SystemExit(f"变更目标尚未登记：{missing}")
    unavailable = [item for item in targets if graph["nodes"][item].get("status") != "VALID"]
    if unavailable: raise SystemExit(f"变更目标当前不是 VALID，先完成已有返工：{unavailable}")
    counter_path = control(root) / "change-control-state.json"; counter = load(counter_path)
    cr_id = f"CR-{int(counter['next_change_request']):04d}"; counter["next_change_request"] += 1; counter["updated_at"] = now(); write(counter_path, counter)
    payload = {
        "schema_version": "1.0", "change_request_id": cr_id, "status": "OPEN",
        "title": args.title, "description": args.description, "reason": args.reason,
        "requested_by": args.requested_by, "request_quote": args.request_quote,
        "target_artifacts": targets, "created_at": now(), "updated_at": now(),
        "graph_revision_at_request": graph["revision"], "approval": None, "work_orders": [],
    }
    write(cr_dir(root, cr_id) / "change-request.json", payload)
    (cr_dir(root, cr_id) / "request.md").write_text(
        f"# 变更请求 {cr_id}\n\n- 标题：{args.title}\n- 请求人：{args.requested_by}\n- 目标产物：{', '.join(targets)}\n- 原因：{args.reason}\n- 用户原话：{args.request_quote}\n\n{args.description}\n",
        encoding="utf-8")
    print(f"已创建变更请求：{cr_id}")


def reverse_edges(nodes: dict) -> dict[str, list[tuple[str, str]]]:
    result = {node_id: [] for node_id in nodes}
    for child, node in nodes.items():
        for dep in node.get("depends_on", []): result.setdefault(dep["artifact_id"], []).append((child, dep.get("propagation", "REBUILD")))
    return result


def impact_map(nodes: dict, targets: list[str]) -> dict[str, str]:
    reverse = reverse_edges(nodes); impact = {item: "REBUILD" for item in targets}; queue = list(targets)
    while queue:
        source = queue.pop(0)
        for child, edge_mode in reverse.get(source, []):
            mode = "REBUILD" if impact[source] == "REBUILD" and edge_mode == "REBUILD" else "VERIFY"
            if child not in impact or (impact[child] == "VERIFY" and mode == "REBUILD"):
                impact[child] = mode; queue.append(child)
    return impact


def analyze(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); request_path = cr_dir(root, args.change_request) / "change-request.json"
    request = load(request_path); graph = load(graph_path(root)); nodes = graph["nodes"]
    if request["status"] not in {"OPEN", "ANALYZED"}: raise SystemExit("只有 OPEN/ANALYZED 变更请求可以重新分析")
    impact = impact_map(nodes, request["target_artifacts"])
    items = [{"artifact_id": node_id, "mode": mode, "producer_phase": nodes[node_id]["producer_phase"], "path": nodes[node_id]["path"], "current_version": nodes[node_id]["version"]} for node_id, mode in impact.items()]
    items.sort(key=lambda x: (PHASES.index(x["producer_phase"]), x["artifact_id"]))
    affected = sorted({item["producer_phase"] for item in items}, key=PHASES.index)
    analysis = {
        "schema_version": "1.0", "change_request_id": args.change_request,
        "graph_revision": graph["revision"], "generated_at": now(), "impacted_artifacts": items,
        "affected_phases": affected, "unaffected_artifacts": sorted(set(nodes) - set(impact)),
        "summary": {"rebuild": sum(x["mode"] == "REBUILD" for x in items), "verify": sum(x["mode"] == "VERIFY" for x in items)},
    }
    write(cr_dir(root, args.change_request) / "impact-analysis.json", analysis)
    request["status"] = "ANALYZED"; request["updated_at"] = now(); request["analysis_graph_revision"] = graph["revision"]; write(request_path, request)
    print(f"影响分析完成：{len(items)} 个产物，{len(affected)} 个阶段；REBUILD={analysis['summary']['rebuild']}，VERIFY={analysis['summary']['verify']}")


def approve_plan(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); path = cr_dir(root, args.change_request) / "change-request.json"; request = load(path)
    if request["status"] != "ANALYZED": raise SystemExit("变更请求必须先完成影响分析")
    if len(args.approval_quote.strip()) < 2: raise SystemExit("必须记录明确的范围批准原话")
    graph = load(graph_path(root)); analysis = load(cr_dir(root, args.change_request) / "impact-analysis.json")
    if graph["revision"] != analysis["graph_revision"]: raise SystemExit("依赖图在分析后已变化，必须重新分析")
    request["status"] = "APPROVED"; request["approval"] = {"approved_by": args.approved_by, "approval_quote": args.approval_quote, "approved_at": now(), "impact_analysis_sha256": digest(cr_dir(root, args.change_request) / "impact-analysis.json")}; request["updated_at"] = now(); write(path, request)
    print(f"变更范围已批准：{args.change_request}；尚未签发返工工单")


def issue_orders(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); request_path = cr_dir(root, args.change_request) / "change-request.json"; request = load(request_path)
    if request["status"] != "APPROVED": raise SystemExit("只有 APPROVED 变更请求可以签发工单")
    state_path = control(root) / "project-state.json"; state = load(state_path)
    if state.get("active_change_requests"): raise SystemExit(f"已有活动变更请求，必须先关闭：{state['active_change_requests']}")
    analysis_path = cr_dir(root, args.change_request) / "impact-analysis.json"; analysis = load(analysis_path); graph = load(graph_path(root))
    if digest(analysis_path) != request["approval"]["impact_analysis_sha256"] or graph["revision"] != analysis["graph_revision"]: raise SystemExit("批准的影响分析已失效，必须重新分析并批准")
    by_phase: dict[str, list[dict]] = {}
    for item in analysis["impacted_artifacts"]: by_phase.setdefault(item["producer_phase"], []).append(item)
    phase_orders = {phase: f"RW-{args.change_request[3:]}-{index:02d}" for index, phase in enumerate(sorted(by_phase, key=PHASES.index), 1)}
    impacted = {item["artifact_id"] for item in analysis["impacted_artifacts"]}
    registry = load(control(root) / "session-registry.json")
    for phase, items in by_phase.items():
        predecessor_phases = set()
        for item in items:
            for dep in graph["nodes"][item["artifact_id"]].get("depends_on", []):
                dep_id = dep["artifact_id"]
                if dep_id in impacted:
                    dep_phase = graph["nodes"][dep_id]["producer_phase"]
                    if dep_phase != phase: predecessor_phases.add(dep_phase)
        predecessors = [phase_orders[p] for p in sorted(predecessor_phases, key=PHASES.index)]
        entry = next(x for x in registry["stages"] if x["phase"] == phase)
        order_id = phase_orders[phase]
        order = {
            "schema_version": "1.0", "work_order_id": order_id, "change_request_id": args.change_request,
            "phase": phase, "status": "BLOCKED" if predecessors else "READY", "predecessor_orders": predecessors,
            "rebuild_artifacts": [x["artifact_id"] for x in items if x["mode"] == "REBUILD"],
            "verify_artifacts": [x["artifact_id"] for x in items if x["mode"] == "VERIFY"],
            "completed_artifacts": [], "verified_artifacts": {}, "review_items": {}, "authorization": None,
            "assigned_session_name": entry["session_name"], "assigned_session_id": entry["session_id"],
            "attempt": int(entry.get("attempt", 1)), "created_at": now(), "updated_at": now(),
        }
        write(order_dir(root, order_id) / "work-order.json", order)
        (order_dir(root, order_id) / "approval-record.md").write_text(f"# 返工工单审批记录 — {order_id}\n", encoding="utf-8")
        packet = f"# 选择性返工工单 — {order_id}\n\n- 变更请求：{args.change_request}\n- 原阶段：{phase}\n- 指定 Session：{entry['session_name']} / {entry['session_id']}\n- 状态：`{order['status']}`\n- 前置工单：{', '.join(predecessors) or '无'}\n- 必须重建：{', '.join(order['rebuild_artifacts']) or '无'}\n- 仅需回归验证：{', '.join(order['verify_artifacts']) or '无'}\n\n只修改上述范围。读取变更请求、影响分析、依赖图和原阶段最新已验收交接；不得顺带修改未列入工单的产物。完成后逐项更新或验证产物，与用户处理所有反馈，取得明确提交授权后再提交项目经理。\n"
        (order_dir(root, order_id) / "task-packet.md").write_text(packet, encoding="utf-8")
    for item in analysis["impacted_artifacts"]:
        graph["nodes"][item["artifact_id"]]["status"] = "REWORK_REQUIRED" if item["mode"] == "REBUILD" else "VERIFY_REQUIRED"
        graph["nodes"][item["artifact_id"]]["active_change_request"] = args.change_request
    save_graph(root, graph)
    request["status"] = "IN_REWORK"; request["work_orders"] = list(phase_orders.values()); request["project_status_before"] = state.get("project_status", "ACTIVE"); request["updated_at"] = now(); write(request_path, request)
    if args.change_request not in state["active_change_requests"]: state["active_change_requests"].append(args.change_request)
    state["project_status"] = "CHANGE_IN_PROGRESS"
    for phase, order_id in phase_orders.items(): state["rework_orders"][order_id] = {"phase": phase, "status": load(order_dir(root, order_id) / "work-order.json")["status"]}
    state["updated_at"] = now(); write(state_path, state)
    print(f"已签发 {len(phase_orders)} 张选择性返工工单：{', '.join(phase_orders.values())}")


def load_order(root: Path, order_id: str) -> tuple[Path, dict]:
    path = order_dir(root, order_id) / "work-order.json"
    if not path.is_file(): raise SystemExit(f"返工工单不存在：{order_id}")
    return path, load(path)


def set_order(root: Path, path: Path, order: dict) -> None:
    order["updated_at"] = now(); write(path, order)
    state_path = control(root) / "project-state.json"; state = load(state_path)
    state["rework_orders"][order["work_order_id"]]["status"] = order["status"]; state["updated_at"] = now(); write(state_path, state)


def order_prompt(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); _, order = load_order(root, args.work_order)
    text = f"""你是 `{order['assigned_session_name']}`，现在继续处理原阶段 {order['phase']} 的选择性返工工单 `{args.work_order}`。

项目根目录：`{root}`
工单：`{order_dir(root, args.work_order) / 'task-packet.md'}`

读取 explainer-video-generator/SKILL.md、工单、对应变更请求、影响分析、产物依赖图和原阶段最新交接。仅修改工单列出的产物；完成重建和回归验证后，在本 Session 与用户完成审阅，取得“可以提交项目经理”的明确授权，再提交工单。不得重跑无关阶段或覆盖旧版本证据。
"""
    out = order_dir(root, args.work_order) / "session-prompt.md"; out.write_text(text, encoding="utf-8"); print(text)


def assign_order(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); path, order = load_order(root, args.work_order)
    if order["status"] in {"ACCEPTED", "CANCELLED"}: raise SystemExit("已结束工单不能重新分配 Session")
    if args.session_id == "UNASSIGNED": raise SystemExit("必须记录平台返回的真实 Session ID")
    order.setdefault("assignment_history", []).append({
        "session_name": order.get("assigned_session_name"), "session_id": order.get("assigned_session_id"),
        "replaced_at": now(), "reason": args.reason,
    })
    base_name = str(order.get("assigned_session_name") or f"EVG-{order['phase']}").split("-RW-")[0]
    order["assigned_session_name"] = args.session_name or f"{base_name}-RW-{order['change_request_id'][3:]}-A{len(order['assignment_history']) + 1}"
    order["assigned_session_id"] = args.session_id; order["assigned_platform"] = args.platform
    order["attempt"] = int(order.get("attempt", 1)) + 1; set_order(root, path, order)
    print(f"已把 {args.work_order} 分配给 {order['assigned_session_name']} / {args.session_id}")


def start_order(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); path, order = load_order(root, args.work_order)
    if order["status"] != "READY": raise SystemExit(f"工单当前不可启动：{order['status']}")
    order["status"] = "IN_PROGRESS"; set_order(root, path, order); print(f"已启动返工工单：{args.work_order}")


def invalidate_authorization(order: dict) -> None:
    order["authorization"] = None
    if order["status"] in {"SUBMISSION_AUTHORIZED", "WAITING_USER"}: order["status"] = "IN_PROGRESS"


def update_artifact(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); order_path, order = load_order(root, args.work_order)
    if order["status"] not in {"IN_PROGRESS", "WAITING_USER"}: raise SystemExit("工单未处于执行状态")
    if args.artifact_id not in order["rebuild_artifacts"]: raise SystemExit("该产物不在工单的重建范围内")
    graph = load(graph_path(root)); node = graph["nodes"][args.artifact_id]; target, stored = project_path(root, args.path)
    if not target.is_file(): raise SystemExit(f"新产物不存在：{target}")
    if args.version == node.get("version"): raise SystemExit("返工产物必须使用新的版本号")
    new_digest = digest(target)
    if stored == node.get("path") and new_digest != node.get("sha256"):
        raise SystemExit("返工产物不得覆盖旧版本路径；请写入带新版本的文件后再登记")
    node.setdefault("history", []).append({k: node.get(k) for k in ("path", "version", "sha256", "status", "updated_at")})
    node.update({"path": stored, "version": args.version, "sha256": new_digest, "status": "PENDING_REVIEW", "updated_at": now()})
    if args.depends_on is not None: node["depends_on"] = parse_dependencies(args.depends_on)
    save_graph(root, graph)
    if args.artifact_id not in order["completed_artifacts"]: order["completed_artifacts"].append(args.artifact_id)
    invalidate_authorization(order); set_order(root, order_path, order); print(f"已更新返工产物：{args.artifact_id} / {args.version}")


def verify_artifact(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); order_path, order = load_order(root, args.work_order)
    if order["status"] not in {"IN_PROGRESS", "WAITING_USER"}: raise SystemExit("工单未处于执行状态")
    if args.artifact_id not in order["verify_artifacts"]: raise SystemExit("该产物不在工单的验证范围内")
    graph = load(graph_path(root)); node = graph["nodes"][args.artifact_id]; target, _ = project_path(root, node["path"])
    if not target.is_file() or digest(target) != node["sha256"]: raise SystemExit("待验证产物已发生未登记变化，应改为重建并重新分析")
    node["status"] = "PENDING_REVIEW"; node["updated_at"] = now(); save_graph(root, graph)
    order["verified_artifacts"][args.artifact_id] = {"evidence": args.evidence, "verified_at": now()}
    invalidate_authorization(order); set_order(root, order_path, order); print(f"已记录回归验证：{args.artifact_id}")


def record_review(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); path, order = load_order(root, args.work_order)
    if order["status"] not in {"IN_PROGRESS", "WAITING_USER", "SUBMISSION_AUTHORIZED"}: raise SystemExit("工单当前不能记录审阅互动")
    order["review_items"][args.item_id] = {"status": args.status, "message": args.message, "updated_at": now()}
    invalidate_authorization(order); order["status"] = "WAITING_USER" if args.status == "OPEN" else "IN_PROGRESS"; set_order(root, path, order)
    with (order_dir(root, args.work_order) / "approval-record.md").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"\n## 审阅互动 {now()}\n\n- 事项：`{args.item_id}`\n- 状态：`{args.status}`\n- 内容：{args.message}\n")
    print(f"已记录审阅事项：{args.item_id} / {args.status}；此前授权（如有）已失效")


def authorization_snapshot(root: Path, order: dict) -> dict:
    graph = load(graph_path(root)); ids = order["rebuild_artifacts"] + order["verify_artifacts"]
    return {artifact_id: {"version": graph["nodes"][artifact_id]["version"], "sha256": graph["nodes"][artifact_id]["sha256"]} for artifact_id in ids}


def authorize_order(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); path, order = load_order(root, args.work_order)
    if order["status"] not in {"IN_PROGRESS", "WAITING_USER"}: raise SystemExit("工单当前不能取得提交授权")
    if set(order["completed_artifacts"]) != set(order["rebuild_artifacts"]): raise SystemExit("仍有重建产物未完成")
    if set(order["verified_artifacts"]) != set(order["verify_artifacts"]): raise SystemExit("仍有回归验证未完成")
    open_items = [key for key, value in order["review_items"].items() if value["status"] == "OPEN"]
    if open_items: raise SystemExit(f"仍有未关闭事项：{open_items}")
    graph = load(graph_path(root))
    for artifact_id in order["rebuild_artifacts"] + order["verify_artifacts"]:
        if graph["nodes"][artifact_id]["status"] != "PENDING_REVIEW": raise SystemExit(f"产物尚未进入待验收状态：{artifact_id}")
    if len(args.authorization_quote.strip()) < 2: raise SystemExit("必须记录用户明确授权原话")
    order["authorization"] = {"status": "SUBMISSION_AUTHORIZED", "quote": args.authorization_quote, "authorized_by": args.authorized_by, "authorized_at": now(), "snapshot": authorization_snapshot(root, order)}
    order["status"] = "SUBMISSION_AUTHORIZED"; set_order(root, path, order)
    with (order_dir(root, args.work_order) / "approval-record.md").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"\n## 提交授权 {now()}\n\n- 状态：`SUBMISSION_AUTHORIZED`\n- 用户原话：{args.authorization_quote}\n- 未决事项：0\n")
    print(f"已取得返工工单提交授权：{args.work_order}")


def snapshot_valid(root: Path, order: dict) -> bool:
    return bool(order.get("authorization")) and order["authorization"]["snapshot"] == authorization_snapshot(root, order)


def submit_order(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); path, order = load_order(root, args.work_order)
    if order["status"] != "SUBMISSION_AUTHORIZED" or not snapshot_valid(root, order): raise SystemExit("提交授权缺失或授权后的产物发生变化")
    order["status"] = "SUBMITTED"; order["summary"] = args.summary; order["submitted_at"] = now(); set_order(root, path, order); print(f"返工工单已提交项目经理：{args.work_order}")


def accept_order(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); path, order = load_order(root, args.work_order)
    if order["status"] != "SUBMITTED" or not snapshot_valid(root, order): raise SystemExit("工单未提交或提交快照已漂移")
    graph = load(graph_path(root))
    for artifact_id in order["rebuild_artifacts"] + order["verify_artifacts"]:
        node = graph["nodes"][artifact_id]; node["status"] = "VALID"; node.pop("active_change_request", None); node["updated_at"] = now()
    save_graph(root, graph); order["status"] = "ACCEPTED"; order["accepted_at"] = now(); order["acceptance_evidence"] = args.evidence; set_order(root, path, order)
    request = load(cr_dir(root, order["change_request_id"]) / "change-request.json")
    for other_id in request["work_orders"]:
        other_path, other = load_order(root, other_id)
        if other["status"] == "BLOCKED" and all(load_order(root, dep)[1]["status"] == "ACCEPTED" for dep in other["predecessor_orders"]):
            other["status"] = "READY"; set_order(root, other_path, other)
    print(f"返工工单已验收：{args.work_order}；已自动放行满足前置条件的后续工单")


def close_request(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); path = cr_dir(root, args.change_request) / "change-request.json"; request = load(path)
    if request["status"] != "IN_REWORK": raise SystemExit("变更请求不在返工执行状态")
    pending = [order_id for order_id in request["work_orders"] if load_order(root, order_id)[1]["status"] != "ACCEPTED"]
    if pending: raise SystemExit(f"仍有未验收工单：{pending}")
    request["status"] = "CLOSED"; request["closed_at"] = now(); request["closure_evidence"] = args.evidence; request["updated_at"] = now(); write(path, request)
    state_path = control(root) / "project-state.json"; state = load(state_path); state["active_change_requests"] = [x for x in state["active_change_requests"] if x != args.change_request]; state["project_status"] = request.get("project_status_before", "ACTIVE"); state["version"] = int(state.get("version", 1)) + 1; state["updated_at"] = now(); write(state_path, state)
    print(f"变更请求已关闭：{args.change_request}；项目版本={state['version']}")


def status(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); bootstrap(root); graph = load(graph_path(root)); state = load(control(root) / "project-state.json")
    print(f"依赖图 revision={graph['revision']} artifacts={len(graph['nodes'])}")
    print(f"活动变更：{', '.join(state['active_change_requests']) or '无'}")
    for order_id, value in state["rework_orders"].items(): print(f"{order_id} {value['status']:24} {value['phase']}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest="command", required=True)
    x = sub.add_parser("bootstrap"); x.add_argument("root"); x.set_defaults(func=lambda a: (bootstrap(Path(a.root).resolve()), print("变更控制面已就绪")))
    x = sub.add_parser("register-artifact"); x.add_argument("root"); x.add_argument("--artifact-id", required=True); x.add_argument("--path", required=True); x.add_argument("--phase", required=True); x.add_argument("--version", required=True); x.add_argument("--type", default="DOCUMENT"); x.add_argument("--depends-on", action="append"); x.set_defaults(func=register_artifact)
    x = sub.add_parser("import-manifest"); x.add_argument("root"); x.add_argument("--manifest", required=True); x.set_defaults(func=import_manifest)
    x = sub.add_parser("create-request"); x.add_argument("root"); x.add_argument("--title", required=True); x.add_argument("--description", required=True); x.add_argument("--reason", required=True); x.add_argument("--requested-by", required=True); x.add_argument("--request-quote", required=True); x.add_argument("--target", action="append", required=True); x.set_defaults(func=create_request)
    x = sub.add_parser("analyze"); x.add_argument("root"); x.add_argument("change_request"); x.set_defaults(func=analyze)
    x = sub.add_parser("approve-plan"); x.add_argument("root"); x.add_argument("change_request"); x.add_argument("--approved-by", required=True); x.add_argument("--approval-quote", required=True); x.set_defaults(func=approve_plan)
    x = sub.add_parser("issue-orders"); x.add_argument("root"); x.add_argument("change_request"); x.set_defaults(func=issue_orders)
    x = sub.add_parser("order-prompt"); x.add_argument("root"); x.add_argument("work_order"); x.set_defaults(func=order_prompt)
    x = sub.add_parser("assign-order"); x.add_argument("root"); x.add_argument("work_order"); x.add_argument("--session-id", required=True); x.add_argument("--session-name"); x.add_argument("--platform", default="codex"); x.add_argument("--reason", required=True); x.set_defaults(func=assign_order)
    x = sub.add_parser("start-order"); x.add_argument("root"); x.add_argument("work_order"); x.set_defaults(func=start_order)
    x = sub.add_parser("update-artifact"); x.add_argument("root"); x.add_argument("work_order"); x.add_argument("--artifact-id", required=True); x.add_argument("--path", required=True); x.add_argument("--version", required=True); x.add_argument("--depends-on", action="append"); x.set_defaults(func=update_artifact)
    x = sub.add_parser("verify-artifact"); x.add_argument("root"); x.add_argument("work_order"); x.add_argument("--artifact-id", required=True); x.add_argument("--evidence", required=True); x.set_defaults(func=verify_artifact)
    x = sub.add_parser("record-review"); x.add_argument("root"); x.add_argument("work_order"); x.add_argument("--item-id", required=True); x.add_argument("--status", choices=["OPEN", "CLOSED"], required=True); x.add_argument("--message", required=True); x.set_defaults(func=record_review)
    x = sub.add_parser("authorize-order"); x.add_argument("root"); x.add_argument("work_order"); x.add_argument("--authorized-by", required=True); x.add_argument("--authorization-quote", required=True); x.set_defaults(func=authorize_order)
    x = sub.add_parser("submit-order"); x.add_argument("root"); x.add_argument("work_order"); x.add_argument("--summary", required=True); x.set_defaults(func=submit_order)
    x = sub.add_parser("accept-order"); x.add_argument("root"); x.add_argument("work_order"); x.add_argument("--evidence", required=True); x.set_defaults(func=accept_order)
    x = sub.add_parser("close-request"); x.add_argument("root"); x.add_argument("change_request"); x.add_argument("--evidence", required=True); x.set_defaults(func=close_request)
    x = sub.add_parser("status"); x.add_argument("root"); x.set_defaults(func=status)
    return p


if __name__ == "__main__":
    try:
        args = parser().parse_args(); result = args.func(args); raise SystemExit(result if isinstance(result, int) else 0)
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"错误：{exc}", file=sys.stderr); raise SystemExit(2)
