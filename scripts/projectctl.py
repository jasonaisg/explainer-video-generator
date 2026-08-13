#!/usr/bin/env python3
"""Initialize and coordinate a sequential 15-session explainer-video project."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PHASES = [
    ("P00", "项目初始化与输入契约"), ("P01", "媒体校验与同步"),
    ("P02", "转录校对与主时间轴"), ("P03", "事实与内容锁定"),
    ("P04", "动画筛选与人物布局"), ("P05", "导演脚本与视觉系统"),
    ("P06", "制作前对抗式审查"), ("P07", "三页静态审阅图"),
    ("P08", "真实素材集成样片"), ("P09", "全场景与关键帧实现"),
    ("P10", "全片低质量初稿"), ("P11", "受控精修与回归"),
    ("P12", "最终高质量渲染"), ("P13", "成片对抗式质检"),
    ("P14", "交付归档与复现"),
]
PHASE_NAMES = dict(PHASES)
USER_GATES = {"P00", "P04", "P05", "P07", "P08", "P10", "P14"}
GOVERNANCE_SCHEMA = "1.3"
GOVERNANCE_FILES = ("content-advice.json", "owner-decisions.json", "review-items.json", "stage-issues.json")
OBJECTIVE_ISSUE_CATEGORIES = {
    "INPUT_MISSING", "FILE_INTEGRITY", "HASH_DRIFT", "MEDIA_DECODE", "MEDIA_SYNC",
    "CONFIG_CONFORMANCE", "RENDER_FAILURE", "RIGHTS_EVIDENCE", "OUTPUT_MISSING",
    "TECHNICAL_VALIDATION", "USER_DECISION_PENDING", "LEGACY_OBJECTIVE_REVIEW",
}
STANDARD_FILES = (
    "task-packet.md", "stage-result.json", "deliverables-manifest.json",
    "handoff.md", "open-issues.md", "approval-record.md",
)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff-]+", "-", value.strip()).strip("-")
    return value[:48] or "explainer-video"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def root_paths(root: Path) -> tuple[Path, Path, Path]:
    control = root / "00_control"
    return control / "project-state.json", control / "session-registry.json", control / "project-config.json"


def phase_dir(root: Path, phase: str) -> Path:
    require_phase(phase)
    return root / "stages" / phase


def schema_at_least(value: object, major: int, minor: int) -> bool:
    try:
        parts = str(value).split(".")
        return (int(parts[0]), int(parts[1])) >= (major, minor)
    except (ValueError, IndexError):
        return False


def governance_enabled(root: Path) -> bool:
    state_path, _, _ = root_paths(root)
    return state_path.is_file() and schema_at_least(load_json(state_path).get("schema_version"), 1, 3)


def governance_path(root: Path, phase: str, filename: str) -> Path:
    return phase_dir(root, phase) / filename


def empty_governance(phase: str) -> dict[str, dict]:
    return {
        "content-advice.json": {"schema_version": "1.0", "phase": phase, "items": {}},
        "owner-decisions.json": {"schema_version": "1.0", "phase": phase, "decisions": {}},
        "review-items.json": {"schema_version": "1.0", "phase": phase, "items": {}},
        "stage-issues.json": {"schema_version": "1.0", "phase": phase, "items": {}},
    }


def require_governance(root: Path, phase: str) -> None:
    if not governance_enabled(root):
        raise SystemExit("该项目尚未启用 1.3 通用内容权威模型；请先运行 migrate-governance")
    missing = [name for name in GOVERNANCE_FILES if not governance_path(root, phase, name).is_file()]
    if missing: raise SystemExit(f"阶段治理文件缺失：{missing}")


def open_review_items(root: Path, phase: str) -> list[str]:
    if not governance_enabled(root): return []
    data = load_json(governance_path(root, phase, "review-items.json"))
    return [key for key, item in data.get("items", {}).items() if item.get("status") == "OPEN"]


def open_blocking_issues(root: Path, phase: str) -> list[str]:
    if not governance_enabled(root): return []
    data = load_json(governance_path(root, phase, "stage-issues.json"))
    return [key for key, item in data.get("items", {}).items() if item.get("status") == "OPEN" and item.get("gate_effect") == "BLOCKING"]


def sync_issue_summary(root: Path, phase: str) -> None:
    if not governance_enabled(root): return
    issues = load_json(governance_path(root, phase, "stage-issues.json")).get("items", {})
    counts = {level: 0 for level in ("BLOCKER", "HIGH", "MEDIUM", "LOW")}
    for item in issues.values():
        if item.get("status") == "OPEN" and item.get("severity") in counts:
            counts[item["severity"]] += 1
    result_path = governance_path(root, phase, "stage-result.json")
    result = load_json(result_path); result["issues"] = counts; write_json(result_path, result)


def render_open_issues(root: Path, phase: str) -> None:
    if not governance_enabled(root): return
    items = load_json(governance_path(root, phase, "stage-issues.json")).get("items", {})
    lines = [f"# 未决问题 — {phase}", "", "本文件由 `stage-issues.json` 生成；Agent 内容建议不属于项目问题。", ""]
    for issue_id, item in items.items():
        if item.get("status") != "OPEN": continue
        lines.extend([
            f"## {issue_id}", "", f"- 等级：`{item['severity']}`", f"- 类别：`{item['category']}`",
            f"- 门禁：`{item['gate_effect']}`", f"- 说明：{item['description']}", "",
        ])
    if len(lines) == 4: lines.extend(["无开放的客观执行问题。", ""])
    governance_path(root, phase, "open-issues.md").write_text("\n".join(lines), encoding="utf-8")


def stage_requires_authorization(root: Path, phase: str) -> bool:
    if phase in USER_GATES: return True
    result = load_json(governance_path(root, phase, "stage-result.json"))
    return bool(result.get("requires_submission_authorization"))


def mark_interaction_required(root: Path, phase: str) -> None:
    result_path = governance_path(root, phase, "stage-result.json")
    result = load_json(result_path); result["requires_submission_authorization"] = True; write_json(result_path, result)


def require_phase(phase: str) -> None:
    if phase not in PHASE_NAMES:
        raise SystemExit(f"未知阶段：{phase}；应为 P00–P14")


def append_md(path: Path, heading: str, body: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"\n## {heading}\n\n{body.rstrip()}\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def latest_interaction_event(text: str) -> tuple[str, str]:
    matches = list(re.finditer(r"(?m)^##\s+(审阅互动|内容意见|提交授权)\b[^\n]*$", text))
    if not matches: return "", ""
    match = matches[-1]
    return match.group(1), text[match.start():]


def manifest_integrity(root: Path, phase: str) -> tuple[bool, str]:
    path = phase_dir(root, phase) / "deliverables-manifest.json"
    if not path.is_file(): return False, "缺少 deliverables-manifest.json"
    manifest = load_json(path)
    if not manifest.get("files"): return False, "交付清单为空"
    for item in manifest["files"]:
        rel = item.get("path", ""); expected = str(item.get("sha256", "")).lower()
        target = (root / rel).resolve()
        try: target.relative_to(root)
        except ValueError: return False, f"交付路径越出项目：{rel}"
        if not target.is_file(): return False, f"交付文件不存在：{rel}"
        if not expected or sha256(target) != expected: return False, f"交付文件哈希不匹配：{rel}"
    return True, ""


def governance_snapshot(root: Path, phase: str) -> str:
    digest = hashlib.sha256()
    for filename in ("owner-decisions.json", "review-items.json", "stage-issues.json"):
        path = governance_path(root, phase, filename)
        digest.update(filename.encode("utf-8")); digest.update(b"\0"); digest.update(path.read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def submission_authorization_is_valid(root: Path, phase: str) -> tuple[bool, str]:
    """Check that the latest interaction is explicit authorization of an unchanged final package."""
    path = phase_dir(root, phase) / "approval-record.md"
    if not path.is_file(): return False, "缺少 approval-record.md"
    text = path.read_text(encoding="utf-8")
    event, latest = latest_interaction_event(text)
    if event != "提交授权": return False, "最新互动事件不是提交授权；文件批注、问答或内容认可不能提交"
    required = ("授权状态：`SUBMISSION_AUTHORIZED`", "最终产物：", "最终版本：", "提交范围：", "用户授权原话：", "未决事项：0", "附加条件状态：`CLOSED`", "问答状态：`COMPLETE`", "交付清单 SHA-256：", "记录时间：")
    missing = [item for item in required if item not in latest]
    if missing: return False, f"提交授权字段不完整：{missing}"
    match = re.search(r"交付清单 SHA-256：`?([0-9a-fA-F]{64})`?", latest)
    manifest = phase_dir(root, phase) / "deliverables-manifest.json"
    if not match or not manifest.is_file() or sha256(manifest) != match.group(1).lower():
        return False, "提交授权后的交付清单发生变化，必须重新取得授权"
    if governance_enabled(root):
        governance_hash = re.search(r"治理快照 SHA-256：`?([0-9a-fA-F]{64})`?", latest)
        if not governance_hash or governance_snapshot(root, phase) != governance_hash.group(1).lower():
            return False, "提交授权后的用户决定、用户要求或客观问题发生变化，必须重新取得授权"
    valid, reason = manifest_integrity(root, phase)
    if not valid: return False, f"提交授权后的产物发生变化：{reason}"
    return True, ""


def init_project(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    if (root / "00_control" / "project-state.json").exists():
        raise SystemExit(f"项目已经初始化：{root}")
    dirs = [
        "00_control/approvals", "00_control/change-requests", "00_control/rework-orders",
        "01_inputs/video", "01_inputs/audio", "01_inputs/script",
        "01_inputs/config", "01_inputs/fact-sources", "01_inputs/assets", "01_inputs/music",
        "01_inputs/sfx", "02_media_analysis", "03_content_plan", "04_design", "05_reviews",
        "06_hyperframes/src", "06_hyperframes/compositions", "06_hyperframes/media",
        "06_hyperframes/data", "07_previews/storyboards", "07_previews/pilot",
        "07_previews/keyframes", "07_previews/draft", "08_renders/draft", "08_renders/final",
        "08_renders/variants", "09_captions", "10_delivery",
    ]
    for item in dirs:
        (root / item).mkdir(parents=True, exist_ok=True)
    stamp = now()
    slug = slugify(args.name)
    config = {
        "schema_version": GOVERNANCE_SCHEMA, "project_name": args.name, "status": "DRAFT",
        "source": {"video_mp4": "", "audio_mp3": "", "script": "", "original_config": "",
                   "picture_locked": True, "canonical_audio": "audio_mp3", "language": "zh"},
        "video": {"width": None, "height": None, "fps": None, "sync_tolerance_seconds": 0.25},
        "safe_areas": {},
        "presenter": {"always_visible": True, "modes": ["V1_PRESENTER_FULL", "V2_PRESENTER_OVERLAY", "V3_ANIMATION_WITH_PIP"]},
        "captions": {"enabled": True, "mode": "sentence", "sidecars": ["srt", "vtt"]},
        "enhancements": {"external_assets": False, "bgm": False, "sfx": False},
        "environment": {"discovery": "AUTO", "report": "00_control/environment-report.json"},
        "backend": {"name": "hyperframes", "launcher": "", "version": "", "discovery": "AUTO"},
        "delivery": {"captioned_master": True, "clean_master": False},
    }
    state = {
        "schema_version": GOVERNANCE_SCHEMA, "project_id": slug, "project_name": args.name,
        "project_status": "ACTIVE", "current_phase": "P00", "version": 1,
        "created_at": stamp, "updated_at": stamp,
        "active_change_requests": [], "rework_orders": {},
        "phase_status": {p: ("READY" if p == "P00" else "NOT_STARTED") for p, _ in PHASES},
    }
    pm_id = args.pm_session_id or "UNASSIGNED"
    registry = {
        "schema_version": GOVERNANCE_SCHEMA, "updated_at": stamp,
        "pm": {"role": "PM", "session_name": f"EVG-PM-{slug}", "session_id": pm_id,
               "platform": args.platform, "status": "ACTIVE" if pm_id != "UNASSIGNED" else "PLANNED",
               "created_at": stamp, "last_seen_at": stamp},
        "stages": [{"role": "STAGE", "phase": p, "session_name": f"EVG-{p}-{slug}",
                    "session_id": "UNASSIGNED", "platform": "", "status": "PLANNED",
                    "attempt": 1, "input_version": 1, "predecessor": PHASES[i-1][0] if i else None,
                    "successor": PHASES[i+1][0] if i + 1 < len(PHASES) else None,
                    "prompt_path": f"stages/{p}/session-prompt.md", "created_at": None,
                    "last_seen_at": None} for i, (p, _) in enumerate(PHASES)],
    }
    state_path, registry_path, config_path = root_paths(root)
    write_json(config_path, config); write_json(state_path, state); write_json(registry_path, registry)
    write_json(root / "00_control" / "artifact-dependency-graph.json", {
        "schema_version": "1.0", "revision": 0, "updated_at": stamp, "nodes": {},
    })
    write_json(root / "00_control" / "change-control-state.json", {
        "schema_version": "1.0", "next_change_request": 1, "updated_at": stamp,
    })
    for filename, title in (("decision-log.md", "项目决策日志"), ("issue-register.md", "项目问题登记册")):
        (root / "00_control" / filename).write_text(f"# {title}\n", encoding="utf-8")
    for phase, name in PHASES:
        folder = phase_dir(root, phase); folder.mkdir(parents=True, exist_ok=True)
        (folder / "task-packet.md").write_text(f"# 阶段任务包 — {phase} {name}\n\n状态：尚未准备（`NOT_PREPARED`）\n", encoding="utf-8")
        write_json(folder / "stage-result.json", {"phase": phase, "status": "NOT_STARTED", "summary": "", "checks": [], "issues": {"BLOCKER": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}, "requires_submission_authorization": False})
        write_json(folder / "deliverables-manifest.json", {"phase": phase, "version": 1, "files": []})
        for filename, data in empty_governance(phase).items(): write_json(folder / filename, data)
        for filename, title in (("handoff.md", "阶段交接"), ("open-issues.md", "未决问题"), ("approval-record.md", "审批记录")):
            (folder / filename).write_text(f"# {title} — {phase}\n", encoding="utf-8")
        render_open_issues(root, phase)
    print(f"已初始化：{root}")
    print(f"PM Session：{registry['pm']['session_name']} / {pm_id}")
    print("下一步：填写 00_control/project-config.json，然后 prepare P00。")


def migrate_governance(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); state_path, registry_path, config_path = root_paths(root)
    state = load_json(state_path); registry = load_json(registry_path); config = load_json(config_path); previous_schema = str(state.get("schema_version", "1.0"))
    if governance_enabled(root): print("项目已经启用 1.3 通用内容权威模型"); return
    legacy: list[tuple[str, str, int]] = []
    for phase, _ in PHASES:
        result = load_json(governance_path(root, phase, "stage-result.json"))
        for severity, count in result.get("issues", {}).items():
            if severity in {"BLOCKER", "HIGH", "MEDIUM", "LOW"} and int(count or 0) > 0:
                legacy.append((phase, severity, int(count)))
    phase_classification: dict[str, str] = {}
    for value in args.legacy_phase_classification or []:
        phase, sep, classification = value.partition("=")
        if not sep or phase not in PHASE_NAMES or classification not in {"ADVISORY", "OBJECTIVE"}: raise SystemExit("--legacy-phase-classification 使用 Pxx=ADVISORY|OBJECTIVE")
        if phase in phase_classification: raise SystemExit(f"阶段重复分类：{phase}")
        phase_classification[phase] = classification
    missing_classification = sorted({phase for phase, _, _ in legacy if phase not in phase_classification and not args.legacy_items_as})
    if missing_classification:
        raise SystemExit(f"旧项目存在无法自动判断的问题计数；请逐阶段使用 --legacy-phase-classification Pxx=ADVISORY|OBJECTIVE，未分类：{missing_classification}")
    for phase, _ in PHASES:
        defaults = empty_governance(phase)
        for filename, data in defaults.items():
            path = governance_path(root, phase, filename)
            if not path.exists(): write_json(path, data)
        result_path = governance_path(root, phase, "stage-result.json"); result = load_json(result_path)
        result.setdefault("requires_submission_authorization", False); write_json(result_path, result)
        if state.get("phase_status", {}).get(phase) == "ACCEPTED":
            result["accepted_under_schema"] = previous_schema; write_json(result_path, result)
    for phase, severity, count in legacy:
        classification = phase_classification.get(phase, args.legacy_items_as)
        if classification == "ADVISORY":
            path = governance_path(root, phase, "content-advice.json"); data = load_json(path)
            for index in range(1, count + 1):
                advice_id = f"LEGACY-{severity}-{index:03d}"
                data["items"][advice_id] = {
                    "advice_id": advice_id, "priority": severity, "topic": "旧协议迁移项",
                    "recommendation": "旧协议仅保存了数量，原建议内容请查阅历史阶段记录。",
                    "rationale": "按迁移选择归类为 Agent 内容参考，不产生项目门禁。",
                    "references": [], "status": "NOTED", "gate_effect": "NONE", "created_at": now(),
                }
            write_json(path, data)
        elif classification == "OBJECTIVE":
            path = governance_path(root, phase, "stage-issues.json"); data = load_json(path)
            for index in range(1, count + 1):
                issue_id = f"LEGACY-{severity}-{index:03d}"
                data["items"][issue_id] = {
                    "issue_id": issue_id, "severity": severity, "category": "LEGACY_OBJECTIVE_REVIEW",
                    "description": "旧协议迁移的客观问题；必须依据历史记录补充证据并处理。",
                    "status": "OPEN", "gate_effect": "BLOCKING" if severity in {"BLOCKER", "HIGH"} else "NON_BLOCKING",
                    "evidence": [], "created_at": now(),
                }
            write_json(path, data)
    for data, path in ((state, state_path), (registry, registry_path), (config, config_path)):
        data["schema_version"] = GOVERNANCE_SCHEMA; data["updated_at"] = now(); write_json(path, data)
    for phase, _ in PHASES: sync_issue_summary(root, phase); render_open_issues(root, phase)
    summary = ", ".join(f"{phase}={value}" for phase, value in sorted(phase_classification.items())) or args.legacy_items_as or "无历史问题"
    print(f"已迁移到 1.3 通用内容权威模型；旧问题归类={summary}")


def prepare(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); phase = args.phase; require_phase(phase)
    state_path, _, _ = root_paths(root); state = load_json(state_path)
    index = [p for p, _ in PHASES].index(phase)
    if index and state["phase_status"][PHASES[index - 1][0]] != "ACCEPTED":
        raise SystemExit(f"前置阶段 {PHASES[index - 1][0]} 尚未 ACCEPTED")
    state["phase_status"][phase] = "READY"; state["current_phase"] = phase; state["updated_at"] = now()
    write_json(state_path, state)
    refs = "references/phase-specifications.md，以及本任务包指定的按需参考文件"
    interaction = (f"本阶段属于用户互动门。文件批注、问答、内容认可和附条件批准均不能触发提交。必须完成用户提出的开放事项、自检并冻结最终版本，再单独询问是否授权提交项目经理。Agent 对内容的判断只能用 `record-advice` 记录为非阻断参考，不得写入 stage-issues 或影响推进。只有 `projectctl.py authorize-submit` 记录的 `SUBMISSION_AUTHORIZED` 才允许提交；授权后发生用户新要求、客观问题或文件变化都必须重新授权。" if phase in USER_GATES else "本阶段默认可自主执行；Agent 内容判断只能作为非阻断参考。遇到需要用户选择或授权的事项时进入用户互动，并以用户最新明确决定为最终内容权威。")
    packet = f"""# 阶段任务包 — {phase} {PHASE_NAMES[phase]}

状态：已准备（`READY`）
输入版本：{state['version']}
负责人：已登记的 {phase} 阶段 Session

## 必读文件

- explainer-video-generator/SKILL.md
- 00_control/project-config.json
- 00_control/project-state.json
- 上一个已验收阶段的交接文件（如果存在）
- {refs}

## 写入范围

- stages/{phase}/
- {phase} 阶段执行卡明确要求的输出目录

## 禁止事项

- 编辑源 MP4/MP3 或改变其时间
- 自行验收本阶段或推进全局状态
- 未经变更申请修改已审批的上游产物
- 启动其他阶段

## 完成要求

{interaction}

满足 {phase} 阶段执行卡的门禁，更新标准五件套交接文件，运行规定验证，然后提交项目经理验收。
提交后优先直接通知项目经理；无法跨 Session 通知时，明确提示用户返回项目经理 Session 执行验收和下一阶段调度。
"""
    (phase_dir(root, phase) / "task-packet.md").write_text(packet, encoding="utf-8")
    print(f"已准备 {phase}：{phase_dir(root, phase) / 'task-packet.md'}")


def register(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    _, registry_path, _ = root_paths(root); registry = load_json(registry_path)
    entry = next(x for x in registry["stages"] if x["phase"] == args.phase)
    if args.session_id == "UNASSIGNED": raise SystemExit("必须记录平台返回的真实 Session ID")
    entry.update({"session_id": args.session_id, "platform": args.platform, "status": "CREATED",
                  "created_at": entry["created_at"] or now(), "last_seen_at": now()})
    registry["updated_at"] = now(); write_json(registry_path, registry)
    print(f"已登记 {entry['session_name']} / {args.session_id}")


def set_pm(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); _, registry_path, _ = root_paths(root); registry = load_json(registry_path)
    if args.session_id == "UNASSIGNED": raise SystemExit("必须记录平台返回的真实 PM Session ID")
    registry["pm"].update({"session_id": args.session_id, "platform": args.platform, "status": "ACTIVE", "last_seen_at": now()})
    registry["updated_at"] = now(); write_json(registry_path, registry); print(f"已登记 PM：{registry['pm']['session_name']} / {args.session_id}")


def invalidate(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    start_index = [p for p, _ in PHASES].index(args.phase)
    for phase, _ in PHASES[start_index:]:
        if state["phase_status"][phase] != "NOT_STARTED": state["phase_status"][phase] = "STALE"
        entry = next(x for x in registry["stages"] if x["phase"] == phase)
        if entry["status"] not in {"PLANNED", "SUPERSEDED"}: entry["status"] = "SUPERSEDED"
    state["phase_status"][args.phase] = "READY"; state["current_phase"] = args.phase; state["version"] += 1; state["updated_at"] = now()
    append_md(root / "00_control" / "decision-log.md", f"变更影响失效处理 {now()}", f"- 最早受影响阶段：{args.phase}\n- 新输入版本：{state['version']}\n- 原因：{args.reason}")
    write_json(state_path, state); write_json(registry_path, registry); print(f"已从 {args.phase} 失效下游，输入版本={state['version']}")


def prompt(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    _, registry_path, _ = root_paths(root); registry = load_json(registry_path)
    entry = next(x for x in registry["stages"] if x["phase"] == args.phase)
    text = f"""你是 `{entry['session_name']}`，只负责 {args.phase}（{PHASE_NAMES[args.phase]}）。

项目根目录：`{root}`
Skill：`explainer-video-generator`
任务包：`{phase_dir(root, args.phase) / 'task-packet.md'}`

启动后必须读取 Skill、任务包、项目配置/状态和任务包列出的上游交接；先输出阶段启动报告，再执行。只写任务包授权路径。阶段成果与具体修改必须在本 Session 中和用户讨论。完成门禁后更新标准五件套并提交项目经理；提交后通知项目经理，无法跨 Session 通知时引导用户返回项目经理 Session。不得自验收、推进项目或启动下一阶段。
"""
    out = phase_dir(root, args.phase) / "session-prompt.md"; out.write_text(text, encoding="utf-8")
    print(text); print(f"提示词已写入：{out}")


def start(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    entry = next(x for x in registry["stages"] if x["phase"] == args.phase)
    if entry["session_id"] == "UNASSIGNED": raise SystemExit("先登记真实 Session ID")
    if state["phase_status"][args.phase] not in {"READY", "REVISION_REQUIRED", "STALE"}: raise SystemExit("阶段当前不可启动")
    state["phase_status"][args.phase] = "IN_PROGRESS"; state["current_phase"] = args.phase; state["updated_at"] = now()
    entry["status"] = "ACTIVE"; entry["last_seen_at"] = now()
    write_json(state_path, state); write_json(registry_path, registry); print(f"{args.phase} 已启动")


def record_advice(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase); require_governance(root, args.phase)
    path = governance_path(root, args.phase, "content-advice.json"); data = load_json(path)
    if args.advice_id in data["items"]: raise SystemExit(f"内容建议编号已存在：{args.advice_id}")
    data["items"][args.advice_id] = {
        "advice_id": args.advice_id, "priority": args.priority, "topic": args.topic,
        "recommendation": args.recommendation, "rationale": args.rationale,
        "references": args.reference or [], "status": "PRESENTED", "gate_effect": "NONE",
        "created_at": now(), "created_by": args.recorded_by,
    }
    write_json(path, data)
    print(f"已记录非阻断内容建议：{args.advice_id}；项目状态与提交授权均未改变")


def record_owner_decision(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase); require_governance(root, args.phase)
    if len(args.decision_quote.strip()) < 2: raise SystemExit("必须记录用户决定原话")
    path = governance_path(root, args.phase, "owner-decisions.json"); data = load_json(path)
    if args.decision_id in data["decisions"]: raise SystemExit(f"用户决定编号已存在：{args.decision_id}")
    advice_ids = args.advice_id or []
    resolved_issue_ids = args.resolve_issue or []
    if advice_ids and not args.advice_disposition: raise SystemExit("关联内容建议时必须提供 --advice-disposition")
    advice_path = governance_path(root, args.phase, "content-advice.json"); advice = load_json(advice_path)
    if advice_ids:
        missing = [item for item in advice_ids if item not in advice["items"]]
        if missing: raise SystemExit(f"内容建议不存在：{missing}")
    issue_path = governance_path(root, args.phase, "stage-issues.json"); issues = load_json(issue_path)
    if resolved_issue_ids:
        missing = [item for item in resolved_issue_ids if item not in issues["items"]]
        if missing: raise SystemExit(f"待决定事项不存在：{missing}")
        invalid = [item for item in resolved_issue_ids if issues["items"][item].get("category") != "USER_DECISION_PENDING"]
        if invalid: raise SystemExit(f"用户内容决定只能关闭 USER_DECISION_PENDING，不能关闭客观技术问题：{invalid}")
    decision = {
        "decision_id": args.decision_id, "decision": args.decision, "scope": args.scope,
        "decision_quote": args.decision_quote, "decided_by": args.decided_by,
        "advice_ids": advice_ids, "status": "BINDING", "decided_at": now(),
    }
    for item in advice_ids:
        advice["items"][item].update({"status": args.advice_disposition, "decision_id": args.decision_id, "decided_at": now()})
    data["decisions"][args.decision_id] = decision
    if resolved_issue_ids:
        for item in resolved_issue_ids:
            issues["items"][item].update({"status": "CLOSED", "resolution": "USER_DECISION_RECORDED", "resolution_evidence": args.decision_quote, "closed_at": now(), "closed_by": args.decided_by})
    write_json(advice_path, advice); write_json(path, data); write_json(issue_path, issues); mark_interaction_required(root, args.phase)
    sync_issue_summary(root, args.phase); render_open_issues(root, args.phase)
    body = (
        f"- 决定编号：`{args.decision_id}`\n- 最终决定：`{args.decision}`\n- 作用范围：{args.scope}\n"
        f"- 用户原话：{args.decision_quote}\n- 关联参考建议：{', '.join(advice_ids) or '无'}\n- 已关闭待决定事项：{', '.join(resolved_issue_ids) or '无'}\n"
        "- 权威效果：该决定对阶段 Session、项目经理和下游阶段均有约束力；不得因 Agent 内容意见重新阻断。\n"
        f"- 记录时间：{now()}\n- 记录人：{args.recorded_by}"
    )
    append_md(governance_path(root, args.phase, "approval-record.md"), f"用户最终决定 {now()}", body)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    state["phase_status"][args.phase] = "USER_REVIEW"; state["updated_at"] = now()
    entry = next(x for x in registry["stages"] if x["phase"] == args.phase); entry["status"] = "ACTIVE"; entry["last_seen_at"] = now()
    registry["updated_at"] = now(); write_json(state_path, state); write_json(registry_path, registry)
    print(f"已记录具有约束力的用户最终决定：{args.decision_id}；此前提交授权（如有）已失效")


def record_issue(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase); require_governance(root, args.phase)
    path = governance_path(root, args.phase, "stage-issues.json"); data = load_json(path)
    if args.issue_id in data["items"]: raise SystemExit(f"客观问题编号已存在：{args.issue_id}")
    if args.category not in OBJECTIVE_ISSUE_CATEGORIES: raise SystemExit("内容正确性、措辞、审美或专业判断不得登记为项目问题")
    data["items"][args.issue_id] = {
        "issue_id": args.issue_id, "severity": args.severity, "category": args.category,
        "description": args.description, "status": "OPEN",
        "gate_effect": "BLOCKING" if args.severity in {"BLOCKER", "HIGH"} else "NON_BLOCKING",
        "evidence": args.evidence or [], "created_at": now(), "created_by": args.recorded_by,
    }
    write_json(path, data); sync_issue_summary(root, args.phase); render_open_issues(root, args.phase)
    append_md(governance_path(root, args.phase, "approval-record.md"), f"审阅互动 {now()}", f"- 事件：`OBJECTIVE_ISSUE_OPENED`\n- 事项：`{args.issue_id}`\n- 说明：{args.description}\n- 处理状态：`OPEN`")
    print(f"已记录客观执行问题：{args.issue_id} / {args.severity}")


def resolve_issue(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase); require_governance(root, args.phase)
    path = governance_path(root, args.phase, "stage-issues.json"); data = load_json(path)
    if args.issue_id not in data["items"]: raise SystemExit(f"客观问题不存在：{args.issue_id}")
    item = data["items"][args.issue_id]
    item.update({"status": "CLOSED", "resolution": args.resolution, "resolution_evidence": args.evidence, "closed_at": now(), "closed_by": args.recorded_by})
    write_json(path, data); sync_issue_summary(root, args.phase); render_open_issues(root, args.phase)
    append_md(governance_path(root, args.phase, "approval-record.md"), f"审阅互动 {now()}", f"- 事件：`OBJECTIVE_ISSUE_CLOSED`\n- 事项：`{args.issue_id}`\n- 处理：`{args.resolution}`\n- 证据：{args.evidence}\n- 处理状态：`CLOSED`")
    print(f"已关闭客观执行问题：{args.issue_id}")


def submit(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    entry = next(x for x in registry["stages"] if x["phase"] == args.phase)
    if entry["session_id"] == "UNASSIGNED": raise SystemExit("未登记真实 Session ID，不能提交")
    if governance_enabled(root):
        blocking = open_blocking_issues(root, args.phase); reviews = open_review_items(root, args.phase)
        if blocking: raise SystemExit(f"仍有开放的客观阻断问题：{blocking}")
        if reviews: raise SystemExit(f"仍有未完成的用户要求：{reviews}")
        if args.blocker or args.high: raise SystemExit("1.3 项目不得通过 submit 参数写入问题计数；请使用 record-issue")
        sync_issue_summary(root, args.phase)
    if stage_requires_authorization(root, args.phase):
        if state["phase_status"][args.phase] != "SUBMISSION_AUTHORIZED": raise SystemExit(f"{args.phase} 尚未处于 SUBMISSION_AUTHORIZED，不能提交")
        valid, reason = submission_authorization_is_valid(root, args.phase)
        if not valid: raise SystemExit(f"{args.phase} 是用户互动阶段，不能提交：{reason}")
    result_path = phase_dir(root, args.phase) / "stage-result.json"; result = load_json(result_path)
    result.update({"status": "SUBMITTED", "summary": args.summary, "submitted_at": now()})
    if not governance_enabled(root): result["issues"].update({"BLOCKER": args.blocker, "HIGH": args.high})
    write_json(result_path, result); state["phase_status"][args.phase] = "SUBMITTED"; state["updated_at"] = now()
    entry["status"] = "SUBMITTED"; entry["last_seen_at"] = now()
    write_json(state_path, state); write_json(registry_path, registry)
    print(f"{args.phase} 已提交项目经理验收。请通知项目经理；若平台不能跨 Session 通知，请提示用户返回项目经理 Session。")


def accept(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    result = load_json(phase_dir(root, args.phase) / "stage-result.json")
    if result.get("status") != "SUBMITTED": raise SystemExit("阶段尚未提交")
    if governance_enabled(root):
        blocking = open_blocking_issues(root, args.phase); reviews = open_review_items(root, args.phase)
        if blocking: raise SystemExit(f"仍有开放的客观阻断问题：{blocking}")
        if reviews: raise SystemExit(f"仍有未完成的用户要求：{reviews}")
    elif result["issues"].get("BLOCKER", 0) or result["issues"].get("HIGH", 0): raise SystemExit("仍有 BLOCKER/HIGH 问题")
    if stage_requires_authorization(root, args.phase):
        valid, reason = submission_authorization_is_valid(root, args.phase)
        if not valid: raise SystemExit(f"该阶段缺少有效最终提交授权：{reason}")
        if not args.approval_ref: raise SystemExit("该阶段必须提供 --approval-ref")
    state["phase_status"][args.phase] = "ACCEPTED"; state["updated_at"] = now()
    result["status"] = "ACCEPTED"; result["accepted_at"] = now(); result["accepted_under_schema"] = str(state.get("schema_version", "1.0")); write_json(governance_path(root, args.phase, "stage-result.json"), result)
    entry = next(x for x in registry["stages"] if x["phase"] == args.phase); entry["status"] = "ACCEPTED"; entry["last_seen_at"] = now()
    append_md(phase_dir(root, args.phase) / "approval-record.md", now(), f"- 决定：已验收（`ACCEPTED`）\n- 审批依据：{args.approval_ref or '项目经理技术门禁'}")
    index = [p for p, _ in PHASES].index(args.phase)
    if index + 1 < len(PHASES):
        nxt = PHASES[index + 1][0]; state["phase_status"][nxt] = "READY"; state["current_phase"] = nxt
    else: state["project_status"] = "COMPLETE"; state["current_phase"] = None
    write_json(state_path, state); write_json(registry_path, registry); print(f"{args.phase} 已验收")


def return_phase(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    state["phase_status"][args.phase] = "REVISION_REQUIRED"; state["updated_at"] = now()
    entry = next(x for x in registry["stages"] if x["phase"] == args.phase); entry["status"] = "REVISION_REQUIRED"; entry["attempt"] += 1
    if governance_enabled(root):
        issue_args = argparse.Namespace(root=args.root, phase=args.phase, issue_id=args.issue_id or f"PM-RETURN-{datetime.now().strftime('%Y%m%d%H%M%S')}", severity=args.severity, category=args.category, description=args.reason, evidence=[args.reason], recorded_by="项目经理")
        record_issue(issue_args)
    else: append_md(phase_dir(root, args.phase) / "open-issues.md", now(), f"- 等级：{args.severity}\n- 状态：未关闭（`OPEN`）\n- 必须修改：{args.reason}")
    write_json(state_path, state); write_json(registry_path, registry); print(f"{args.phase} 已退回：{args.reason}")


def record_approval(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    if governance_enabled(root): mark_interaction_required(root, args.phase)
    elif args.phase not in USER_GATES: raise SystemExit(f"{args.phase} 不是规定的用户审批阶段")
    body = (
        f"- 决定：`{args.decision}`\n"
        f"- 产物：{args.artifact}\n"
        f"- 产物版本：{args.version}\n"
        f"- 审批范围：{args.scope}\n"
        f"- 用户反馈：{args.feedback}\n"
        f"- 附加条件：{args.conditions or '无'}\n"
        f"- 记录时间：{now()}\n"
        f"- 记录人：{args.recorded_by}"
    )
    append_md(phase_dir(root, args.phase) / "approval-record.md", f"内容意见 {now()}", body)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    if args.decision == "REVISION_REQUIRED":
        state["phase_status"][args.phase] = "REVISION_REQUIRED"
        entry = next(x for x in registry["stages"] if x["phase"] == args.phase); entry["status"] = "REVISION_REQUIRED"
    else:
        state["phase_status"][args.phase] = "USER_REVIEW"
        entry = next(x for x in registry["stages"] if x["phase"] == args.phase); entry["status"] = "ACTIVE"
    state["updated_at"] = now(); registry["updated_at"] = now(); write_json(state_path, state); write_json(registry_path, registry)
    print(f"已记录 {args.phase} 内容意见：{args.decision}；此记录不授权提交项目经理")


def record_review(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    if governance_enabled(root):
        require_governance(root, args.phase); mark_interaction_required(root, args.phase)
        path = governance_path(root, args.phase, "review-items.json"); data = load_json(path)
        item_id = args.item_id or f"REVIEW-{len(data['items']) + 1:03d}"
        data["items"][item_id] = {"item_id": item_id, "event": args.event, "artifact": args.artifact, "version": args.version, "message": args.message, "status": args.resolution_status, "updated_at": now(), "recorded_by": args.recorded_by}
        write_json(path, data)
    elif args.phase not in USER_GATES: raise SystemExit(f"{args.phase} 不是规定的用户互动阶段")
    body = (
        f"- 事件：`{args.event}`\n"
        f"- 产物：{args.artifact}\n"
        f"- 产物版本：{args.version}\n"
        f"- 用户原话或忠实摘要：{args.message}\n"
        f"- 处理状态：`{args.resolution_status}`\n"
        f"- 记录时间：{now()}\n"
        f"- 记录人：{args.recorded_by}"
    )
    append_md(phase_dir(root, args.phase) / "approval-record.md", f"审阅互动 {now()}", body)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    state["phase_status"][args.phase] = "USER_REVIEW"; state["updated_at"] = now()
    entry = next(x for x in registry["stages"] if x["phase"] == args.phase); entry["status"] = "WAITING_USER" if args.resolution_status == "OPEN" else "ACTIVE"; entry["last_seen_at"] = now()
    registry["updated_at"] = now(); write_json(state_path, state); write_json(registry_path, registry)
    print(f"已记录 {args.phase} 审阅互动：{args.event}；此前提交授权（如有）已失效")


def authorize_submit(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    if governance_enabled(root):
        require_governance(root, args.phase)
        blocking = open_blocking_issues(root, args.phase); reviews = open_review_items(root, args.phase)
        if blocking: raise SystemExit(f"仍有开放的客观阻断问题：{blocking}")
        if reviews: raise SystemExit(f"仍有未完成的用户要求：{reviews}")
        mark_interaction_required(root, args.phase)
    elif args.phase not in USER_GATES: raise SystemExit(f"{args.phase} 不是规定的用户互动阶段")
    if args.open_items != 0: raise SystemExit("未决事项必须为 0，不能授权提交")
    if len(args.authorization_quote.strip()) < 2: raise SystemExit("必须记录用户明确授权原话")
    result = load_json(phase_dir(root, args.phase) / "stage-result.json")
    if not governance_enabled(root) and (result.get("issues", {}).get("BLOCKER", 0) or result.get("issues", {}).get("HIGH", 0)):
        raise SystemExit("仍有 BLOCKER/HIGH 问题，不能请求或记录提交授权")
    issues_text = (phase_dir(root, args.phase) / "open-issues.md").read_text(encoding="utf-8")
    if not governance_enabled(root) and re.search(r"(?:状态：未关闭|`OPEN`|Status:\s*OPEN)", issues_text, re.IGNORECASE):
        raise SystemExit("open-issues.md 仍含未关闭事项，不能记录提交授权")
    valid, reason = manifest_integrity(root, args.phase)
    if not valid: raise SystemExit(f"授权前交付物校验失败：{reason}")
    manifest = phase_dir(root, args.phase) / "deliverables-manifest.json"
    manifest_data = load_json(manifest)
    mutable = {f"stages/{args.phase}/{name}" for name in ("approval-record.md", "stage-result.json", "open-issues.md", *GOVERNANCE_FILES)}
    listed = {str(item.get("path", "")).replace("\\", "/") for item in manifest_data.get("files", [])}
    if mutable & listed: raise SystemExit("交付清单不得包含审批、建议、用户决定、问题或阶段状态等控制记录")
    governance_line = f"- 治理快照 SHA-256：`{governance_snapshot(root, args.phase)}`\n" if governance_enabled(root) else ""
    body = (
        "- 授权状态：`SUBMISSION_AUTHORIZED`\n"
        f"- 最终产物：{args.artifact}\n"
        f"- 最终版本：{args.version}\n"
        f"- 提交范围：{args.scope}\n"
        f"- 用户授权原话：{args.authorization_quote}\n"
        f"- 未决事项：{args.open_items}\n"
        f"- 附加条件状态：`{args.conditions_status}`\n"
        f"- 问答状态：`{args.qa_status}`\n"
        f"- 交付清单 SHA-256：`{sha256(manifest)}`\n"
        f"{governance_line}"
        f"- 记录时间：{now()}\n"
        f"- 记录人：{args.recorded_by}"
    )
    append_md(phase_dir(root, args.phase) / "approval-record.md", f"提交授权 {now()}", body)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    state["phase_status"][args.phase] = "SUBMISSION_AUTHORIZED"; state["updated_at"] = now()
    entry = next(x for x in registry["stages"] if x["phase"] == args.phase); entry["status"] = "SUBMISSION_AUTHORIZED"; entry["last_seen_at"] = now()
    registry["updated_at"] = now(); write_json(state_path, state); write_json(registry_path, registry)
    print(f"已记录 {args.phase} 最终提交授权；只有产物保持不变时才能提交项目经理")


def status(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); state_path, registry_path, _ = root_paths(root)
    state = load_json(state_path); registry = load_json(registry_path)
    print(f"{state['project_name']} | {state['project_status']} | current={state['current_phase']}")
    for phase, name in PHASES:
        entry = next(x for x in registry["stages"] if x["phase"] == phase)
        print(f"{phase} {state['phase_status'][phase]:17} {entry['session_id']:20} {name}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest="command", required=True)
    x = sub.add_parser("init"); x.add_argument("root"); x.add_argument("--name", required=True); x.add_argument("--pm-session-id"); x.add_argument("--platform", default="codex"); x.set_defaults(func=init_project)
    x = sub.add_parser("migrate-governance"); x.add_argument("root"); x.add_argument("--legacy-items-as", choices=["ADVISORY", "OBJECTIVE"]); x.add_argument("--legacy-phase-classification", action="append"); x.set_defaults(func=migrate_governance)
    for command, func in (("prepare", prepare), ("prompt", prompt), ("start", start), ("submit", submit), ("accept", accept), ("return", return_phase)):
        x = sub.add_parser(command); x.add_argument("root"); x.add_argument("phase")
        if command == "submit": x.add_argument("--summary", required=True); x.add_argument("--blocker", type=int, default=0); x.add_argument("--high", type=int, default=0)
        if command == "accept": x.add_argument("--approval-ref")
        if command == "return": x.add_argument("--severity", choices=["BLOCKER", "HIGH", "MEDIUM", "LOW"], default="HIGH"); x.add_argument("--category", choices=sorted(OBJECTIVE_ISSUE_CATEGORIES), default="TECHNICAL_VALIDATION"); x.add_argument("--issue-id"); x.add_argument("--reason", required=True)
        x.set_defaults(func=func)
    x = sub.add_parser("register"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--session-id", required=True); x.add_argument("--platform", default="codex"); x.set_defaults(func=register)
    x = sub.add_parser("set-pm"); x.add_argument("root"); x.add_argument("--session-id", required=True); x.add_argument("--platform", default="codex"); x.set_defaults(func=set_pm)
    x = sub.add_parser("invalidate"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--reason", required=True); x.set_defaults(func=invalidate)
    x = sub.add_parser("record-approval"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--decision", required=True, choices=["APPROVED", "APPROVED_WITH_CONDITIONS", "REVISION_REQUIRED"]); x.add_argument("--artifact", required=True); x.add_argument("--version", required=True); x.add_argument("--scope", required=True); x.add_argument("--feedback", required=True); x.add_argument("--conditions"); x.add_argument("--recorded-by", default="阶段 Session"); x.set_defaults(func=record_approval)
    x = sub.add_parser("record-review"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--item-id"); x.add_argument("--event", required=True, choices=["COMMENT", "QUESTION", "CHANGE_REQUEST", "ANSWER", "REQUIREMENT"]); x.add_argument("--artifact", required=True); x.add_argument("--version", required=True); x.add_argument("--message", required=True); x.add_argument("--resolution-status", choices=["OPEN", "CLOSED"], default="OPEN"); x.add_argument("--recorded-by", default="阶段 Session"); x.set_defaults(func=record_review)
    x = sub.add_parser("authorize-submit"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--artifact", required=True); x.add_argument("--version", required=True); x.add_argument("--scope", required=True); x.add_argument("--authorization-quote", required=True); x.add_argument("--open-items", type=int, required=True); x.add_argument("--conditions-status", required=True, choices=["CLOSED"]); x.add_argument("--qa-status", required=True, choices=["COMPLETE"]); x.add_argument("--recorded-by", default="阶段 Session"); x.set_defaults(func=authorize_submit)
    x = sub.add_parser("record-advice"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--advice-id", required=True); x.add_argument("--priority", choices=["HIGH", "MEDIUM", "LOW"], default="MEDIUM"); x.add_argument("--topic", required=True); x.add_argument("--recommendation", required=True); x.add_argument("--rationale", required=True); x.add_argument("--reference", action="append"); x.add_argument("--recorded-by", default="阶段 Session"); x.set_defaults(func=record_advice)
    x = sub.add_parser("record-owner-decision"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--decision-id", required=True); x.add_argument("--decision", required=True, choices=["KEEP_ORIGINAL", "ACCEPT_ADVICE", "PARTIAL", "CUSTOM"]); x.add_argument("--scope", required=True); x.add_argument("--decision-quote", required=True); x.add_argument("--decided-by", default="用户"); x.add_argument("--advice-id", action="append"); x.add_argument("--advice-disposition", choices=["ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "NOTED"]); x.add_argument("--resolve-issue", action="append"); x.add_argument("--recorded-by", default="阶段 Session"); x.set_defaults(func=record_owner_decision)
    x = sub.add_parser("record-issue"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--issue-id", required=True); x.add_argument("--severity", required=True, choices=["BLOCKER", "HIGH", "MEDIUM", "LOW"]); x.add_argument("--category", required=True, choices=sorted(OBJECTIVE_ISSUE_CATEGORIES)); x.add_argument("--description", required=True); x.add_argument("--evidence", action="append"); x.add_argument("--recorded-by", default="阶段 Session"); x.set_defaults(func=record_issue)
    x = sub.add_parser("resolve-issue"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--issue-id", required=True); x.add_argument("--resolution", required=True, choices=["FIXED", "NOT_APPLICABLE", "CONFIG_CHANGED", "USER_DECISION_RECORDED"]); x.add_argument("--evidence", required=True); x.add_argument("--recorded-by", default="阶段 Session"); x.set_defaults(func=resolve_issue)
    x = sub.add_parser("status"); x.add_argument("root"); x.set_defaults(func=status)
    return p


if __name__ == "__main__":
    try:
        arguments = parser().parse_args()
        raise SystemExit(arguments.func(arguments))
    except (OSError, json.JSONDecodeError, KeyError) as exc: print(f"错误：{exc}", file=sys.stderr); raise SystemExit(2)
