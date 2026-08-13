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
        "schema_version": "1.2", "project_name": args.name, "status": "DRAFT",
        "source": {"video_mp4": "", "audio_mp3": "", "script": "", "original_config": "",
                   "picture_locked": True, "canonical_audio": "audio_mp3", "language": "zh"},
        "video": {"width": None, "height": None, "fps": None, "sync_tolerance_seconds": 0.25},
        "safe_areas": {},
        "presenter": {"always_visible": True, "modes": ["V1_PRESENTER_FULL", "V2_PRESENTER_OVERLAY", "V3_ANIMATION_WITH_PIP"]},
        "captions": {"enabled": True, "mode": "sentence", "sidecars": ["srt", "vtt"]},
        "enhancements": {"external_assets": False, "bgm": False, "sfx": False},
        "backend": {"name": "hyperframes", "launcher": "scripts/hyperframes-local.cmd"},
        "delivery": {"captioned_master": True, "clean_master": False},
    }
    state = {
        "schema_version": "1.2", "project_id": slug, "project_name": args.name,
        "project_status": "ACTIVE", "current_phase": "P00", "version": 1,
        "created_at": stamp, "updated_at": stamp,
        "active_change_requests": [], "rework_orders": {},
        "phase_status": {p: ("READY" if p == "P00" else "NOT_STARTED") for p, _ in PHASES},
    }
    pm_id = args.pm_session_id or "UNASSIGNED"
    registry = {
        "schema_version": "1.2", "updated_at": stamp,
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
        write_json(folder / "stage-result.json", {"phase": phase, "status": "NOT_STARTED", "summary": "", "checks": [], "issues": {"BLOCKER": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}})
        write_json(folder / "deliverables-manifest.json", {"phase": phase, "version": 1, "files": []})
        for filename, title in (("handoff.md", "阶段交接"), ("open-issues.md", "未决问题"), ("approval-record.md", "审批记录")):
            (folder / filename).write_text(f"# {title} — {phase}\n", encoding="utf-8")
    print(f"已初始化：{root}")
    print(f"PM Session：{registry['pm']['session_name']} / {pm_id}")
    print("下一步：填写 00_control/project-config.json，然后 prepare P00。")


def prepare(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); phase = args.phase; require_phase(phase)
    state_path, _, _ = root_paths(root); state = load_json(state_path)
    index = [p for p, _ in PHASES].index(phase)
    if index and state["phase_status"][PHASES[index - 1][0]] != "ACCEPTED":
        raise SystemExit(f"前置阶段 {PHASES[index - 1][0]} 尚未 ACCEPTED")
    state["phase_status"][phase] = "READY"; state["current_phase"] = phase; state["updated_at"] = now()
    write_json(state_path, state)
    refs = "references/phase-specifications.md，以及本任务包指定的按需参考文件"
    interaction = (f"本阶段属于用户互动门。文件批注、问答、内容认可和附条件批准均不能触发提交。必须完成全部互动与修改、自检并冻结最终版本，向用户展示零未决事项汇总，再单独询问是否授权提交项目经理。只有 `projectctl.py authorize-submit` 记录的 `SUBMISSION_AUTHORIZED` 才允许提交；授权后发生任何新互动或文件变化都必须重新授权。" if phase in USER_GATES else "本阶段默认可自主执行；但遇到需要用户解释、选择或授权的事项时，必须暂停并进入用户互动，不得猜测。")
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


def submit(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    entry = next(x for x in registry["stages"] if x["phase"] == args.phase)
    if entry["session_id"] == "UNASSIGNED": raise SystemExit("未登记真实 Session ID，不能提交")
    if args.phase in USER_GATES:
        if state["phase_status"][args.phase] != "SUBMISSION_AUTHORIZED": raise SystemExit(f"{args.phase} 尚未处于 SUBMISSION_AUTHORIZED，不能提交")
        valid, reason = submission_authorization_is_valid(root, args.phase)
        if not valid: raise SystemExit(f"{args.phase} 是用户互动阶段，不能提交：{reason}")
    result_path = phase_dir(root, args.phase) / "stage-result.json"; result = load_json(result_path)
    result.update({"status": "SUBMITTED", "summary": args.summary, "submitted_at": now()})
    result["issues"].update({"BLOCKER": args.blocker, "HIGH": args.high})
    write_json(result_path, result); state["phase_status"][args.phase] = "SUBMITTED"; state["updated_at"] = now()
    entry["status"] = "SUBMITTED"; entry["last_seen_at"] = now()
    write_json(state_path, state); write_json(registry_path, registry)
    print(f"{args.phase} 已提交项目经理验收。请通知项目经理；若平台不能跨 Session 通知，请提示用户返回项目经理 Session。")


def accept(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    state_path, registry_path, _ = root_paths(root); state = load_json(state_path); registry = load_json(registry_path)
    result = load_json(phase_dir(root, args.phase) / "stage-result.json")
    if result.get("status") != "SUBMITTED": raise SystemExit("阶段尚未提交")
    if result["issues"].get("BLOCKER", 0) or result["issues"].get("HIGH", 0): raise SystemExit("仍有 BLOCKER/HIGH 问题")
    if args.phase in USER_GATES:
        valid, reason = submission_authorization_is_valid(root, args.phase)
        if not valid: raise SystemExit(f"该阶段缺少有效最终提交授权：{reason}")
        if not args.approval_ref: raise SystemExit("该阶段必须提供 --approval-ref")
    state["phase_status"][args.phase] = "ACCEPTED"; state["updated_at"] = now()
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
    append_md(phase_dir(root, args.phase) / "open-issues.md", now(), f"- 等级：{args.severity}\n- 状态：未关闭（`OPEN`）\n- 必须修改：{args.reason}")
    write_json(state_path, state); write_json(registry_path, registry); print(f"{args.phase} 已退回：{args.reason}")


def record_approval(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve(); require_phase(args.phase)
    if args.phase not in USER_GATES: raise SystemExit(f"{args.phase} 不是规定的用户审批阶段")
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
    if args.phase not in USER_GATES: raise SystemExit(f"{args.phase} 不是规定的用户互动阶段")
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
    if args.phase not in USER_GATES: raise SystemExit(f"{args.phase} 不是规定的用户互动阶段")
    if args.open_items != 0: raise SystemExit("未决事项必须为 0，不能授权提交")
    if len(args.authorization_quote.strip()) < 2: raise SystemExit("必须记录用户明确授权原话")
    result = load_json(phase_dir(root, args.phase) / "stage-result.json")
    if result.get("issues", {}).get("BLOCKER", 0) or result.get("issues", {}).get("HIGH", 0):
        raise SystemExit("仍有 BLOCKER/HIGH 问题，不能请求或记录提交授权")
    issues_text = (phase_dir(root, args.phase) / "open-issues.md").read_text(encoding="utf-8")
    if re.search(r"(?:状态：未关闭|`OPEN`|Status:\s*OPEN)", issues_text, re.IGNORECASE):
        raise SystemExit("open-issues.md 仍含未关闭事项，不能记录提交授权")
    valid, reason = manifest_integrity(root, args.phase)
    if not valid: raise SystemExit(f"授权前交付物校验失败：{reason}")
    manifest = phase_dir(root, args.phase) / "deliverables-manifest.json"
    manifest_data = load_json(manifest)
    mutable = {f"stages/{args.phase}/approval-record.md", f"stages/{args.phase}/stage-result.json"}
    listed = {str(item.get("path", "")).replace("\\", "/") for item in manifest_data.get("files", [])}
    if mutable & listed: raise SystemExit("交付清单不得包含授权后仍会更新的 approval-record.md 或 stage-result.json")
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
    for command, func in (("prepare", prepare), ("prompt", prompt), ("start", start), ("submit", submit), ("accept", accept), ("return", return_phase)):
        x = sub.add_parser(command); x.add_argument("root"); x.add_argument("phase")
        if command == "submit": x.add_argument("--summary", required=True); x.add_argument("--blocker", type=int, default=0); x.add_argument("--high", type=int, default=0)
        if command == "accept": x.add_argument("--approval-ref")
        if command == "return": x.add_argument("--severity", choices=["BLOCKER", "HIGH", "MEDIUM", "LOW"], default="HIGH"); x.add_argument("--reason", required=True)
        x.set_defaults(func=func)
    x = sub.add_parser("register"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--session-id", required=True); x.add_argument("--platform", default="codex"); x.set_defaults(func=register)
    x = sub.add_parser("set-pm"); x.add_argument("root"); x.add_argument("--session-id", required=True); x.add_argument("--platform", default="codex"); x.set_defaults(func=set_pm)
    x = sub.add_parser("invalidate"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--reason", required=True); x.set_defaults(func=invalidate)
    x = sub.add_parser("record-approval"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--decision", required=True, choices=["APPROVED", "APPROVED_WITH_CONDITIONS", "REVISION_REQUIRED"]); x.add_argument("--artifact", required=True); x.add_argument("--version", required=True); x.add_argument("--scope", required=True); x.add_argument("--feedback", required=True); x.add_argument("--conditions"); x.add_argument("--recorded-by", default="阶段 Session"); x.set_defaults(func=record_approval)
    x = sub.add_parser("record-review"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--event", required=True, choices=["COMMENT", "QUESTION", "CHANGE_REQUEST", "ANSWER", "REQUIREMENT"]); x.add_argument("--artifact", required=True); x.add_argument("--version", required=True); x.add_argument("--message", required=True); x.add_argument("--resolution-status", choices=["OPEN", "CLOSED"], default="OPEN"); x.add_argument("--recorded-by", default="阶段 Session"); x.set_defaults(func=record_review)
    x = sub.add_parser("authorize-submit"); x.add_argument("root"); x.add_argument("phase"); x.add_argument("--artifact", required=True); x.add_argument("--version", required=True); x.add_argument("--scope", required=True); x.add_argument("--authorization-quote", required=True); x.add_argument("--open-items", type=int, required=True); x.add_argument("--conditions-status", required=True, choices=["CLOSED"]); x.add_argument("--qa-status", required=True, choices=["COMPLETE"]); x.add_argument("--recorded-by", default="阶段 Session"); x.set_defaults(func=authorize_submit)
    x = sub.add_parser("status"); x.add_argument("root"); x.set_defaults(func=status)
    return p


if __name__ == "__main__":
    try:
        arguments = parser().parse_args()
        raise SystemExit(arguments.func(arguments))
    except (OSError, json.JSONDecodeError, KeyError) as exc: print(f"错误：{exc}", file=sys.stderr); raise SystemExit(2)
