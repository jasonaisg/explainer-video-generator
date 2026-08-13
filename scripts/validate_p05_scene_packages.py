#!/usr/bin/env python3
"""Validate per-scene P05 motion scripts and their three review images."""

from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path


ROLES = ("ENTRY_ESTABLISHED", "INFORMATION_COMPLETE", "HANDOFF_READY")
REVIEW_STATES = {"PENDING", "APPROVED", "REVISION_REQUIRED"}
REQUIRED_SECTIONS = (
    "## 场景契约", "## 认知与信息", "## 动效类别与信息结构", "## 视觉风格",
    "## 动画时间线", "## 转场与连续性", "## 字幕、声音与素材", "## 三张审阅图",
    "## 用户逐场景审阅",
)
REQUIRED_LABELS = (
    "场景 ID", "P04 切片或候选 ID", "绝对时间区间", "局部时间区间",
    "唯一认知目标", "唯一记忆结果", "主动效类别", "选择理由", "信息层级",
    "元素清单", "DESIGN.md 版本与令牌引用", "色彩与强调规则", "人物模式",
    "入场", "信息递进", "可读停留", "退出或交接", "元素级动作",
    "入场转场", "出场转场", "最终字幕行为", "合成方式",
)
TOLERANCE = 0.001


def project_path(root: Path, value: object, label: str, issues: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.strip(): issues.append(f"{label} 路径为空"); return None
    path = Path(value); path = path if path.is_absolute() else root / path
    path = path.resolve()
    try: path.relative_to(root)
    except ValueError: issues.append(f"{label} 路径越出项目：{value}"); return None
    return path


def image_size(path: Path) -> tuple[int, int] | None:
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
            return struct.unpack(">II", raw[16:24])
        if raw[:2] == b"\xff\xd8":
            index = 2
            while index + 9 < len(raw):
                if raw[index] != 0xFF: index += 1; continue
                marker = raw[index + 1]; length = int.from_bytes(raw[index + 2:index + 4], "big")
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    return int.from_bytes(raw[index + 7:index + 9], "big"), int.from_bytes(raw[index + 5:index + 7], "big")
                index += 2 + length
    except OSError:
        return None
    return None


def validate(root: Path, data: object, final: bool = False) -> list[str]:
    issues: list[str] = []
    if not isinstance(data, dict): return ["根节点必须是 JSON 对象"]
    if data.get("schema_version") != "1.0": issues.append("schema_version 必须为 1.0")
    timing_data: dict = {}
    for key in ("motion_timing_ref", "design_ref"):
        path = project_path(root, data.get(key), key, issues)
        if path is not None and not path.is_file(): issues.append(f"{key} 文件不存在：{path}")
        elif key == "motion_timing_ref" and path is not None:
            try: timing_data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc: issues.append(f"无法读取 motion_timing_ref：{exc}")
    frame_size = data.get("review_frame_size")
    if not isinstance(frame_size, dict): issues.append("review_frame_size 必须是对象"); frame_size = {}
    expected_width, expected_height = frame_size.get("width"), frame_size.get("height")
    if not isinstance(expected_width, int) or isinstance(expected_width, bool) or expected_width <= 0: issues.append("review_frame_size.width 必须为正整数")
    if not isinstance(expected_height, int) or isinstance(expected_height, bool) or expected_height <= 0: issues.append("review_frame_size.height 必须为正整数")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes: return issues + ["scenes 必须是非空数组"]
    expected_ids = [f"A{i:02d}" for i in range(1, len(scenes) + 1)]
    actual_ids = [item.get("scene_id") if isinstance(item, dict) else None for item in scenes]
    if actual_ids != expected_ids: issues.append(f"场景编号必须连续：实际 {actual_ids}，预期 {expected_ids}")
    timing_scenes = timing_data.get("scenes", []) if isinstance(timing_data, dict) else []
    timing_ids = [item.get("scene_id") for item in timing_scenes if isinstance(item, dict)]
    if timing_ids and timing_ids != actual_ids: issues.append(f"场景包索引与 motion-timing 场景顺序不一致：{actual_ids} != {timing_ids}")
    timing_by_id = {item.get("scene_id"): item for item in timing_scenes if isinstance(item, dict)}
    seen_scripts: set[Path] = set(); seen_images: set[Path] = set()
    for index, item in enumerate(scenes):
        label = expected_ids[index]
        if not isinstance(item, dict): issues.append(f"{label} 必须是对象"); continue
        scene_id = str(item.get("scene_id") or label)
        candidate_ids = item.get("candidate_ids")
        if not isinstance(candidate_ids, list) or not candidate_ids or not all(isinstance(x, str) and x.strip() for x in candidate_ids): issues.append(f"{scene_id} candidate_ids 必须是非空字符串数组")
        start, end = item.get("start_seconds"), item.get("end_seconds")
        valid_time = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (start, end)) and end > start
        if not valid_time: issues.append(f"{scene_id} 时间范围无效")
        timing_scene = timing_by_id.get(scene_id)
        if timing_scene:
            if timing_scene.get("candidate_ids") != candidate_ids: issues.append(f"{scene_id} candidate_ids 与 motion-timing 不一致")
            for key, value in (("start_seconds", start), ("end_seconds", end)):
                expected = timing_scene.get(key)
                if not isinstance(expected, (int, float)) or not isinstance(value, (int, float)) or abs(float(expected) - float(value)) > TOLERANCE: issues.append(f"{scene_id} {key} 与 motion-timing 不一致")
        script = project_path(root, item.get("script_path"), f"{scene_id} script_path", issues)
        if script is not None:
            if script in seen_scripts: issues.append(f"{scene_id} 与其他场景共用脚本路径；每个场景必须独立")
            seen_scripts.add(script)
            if not script.is_file(): issues.append(f"{scene_id} 独立动效脚本不存在：{script}")
            else:
                text = script.read_text(encoding="utf-8")
                if not text.startswith(f"# {scene_id} "): issues.append(f"{scene_id} 脚本标题必须绑定自身场景 ID")
                for section in REQUIRED_SECTIONS:
                    if section not in text: issues.append(f"{scene_id} 脚本缺少章节：{section}")
                for field in REQUIRED_LABELS:
                    match = re.search(rf"(?m)^- {re.escape(field)}：\s*(.+?)\s*$", text)
                    if not match: issues.append(f"{scene_id} 脚本字段缺失或未填写：{field}")
                if "人物全屏与字幕 / 卡片 / 流程图 / 时间线 / 对比表" in text:
                    issues.append(f"{scene_id} 主动效类别仍是模板选项，必须选择具体类别")
            if timing_scene and str(timing_scene.get("scene_script_ref", "")).replace("\\", "/") != str(item.get("script_path", "")).replace("\\", "/"):
                issues.append(f"{scene_id} script_path 与 motion-timing.scene_script_ref 不一致")
        if not isinstance(item.get("script_version"), str) or not item["script_version"].strip(): issues.append(f"{scene_id} 缺少 script_version")
        images = item.get("review_images")
        if not isinstance(images, list) or len(images) != 3:
            issues.append(f"{scene_id} 必须且只能有 3 张审阅图"); images = []
        roles = [image.get("role") if isinstance(image, dict) else None for image in images]
        if roles != list(ROLES): issues.append(f"{scene_id} 三张审阅图角色和顺序必须为 {list(ROLES)}")
        for image in images:
            if not isinstance(image, dict): continue
            role = image.get("role") or "?"; path = project_path(root, image.get("path"), f"{scene_id} {role}", issues)
            if path is not None:
                if path in seen_images: issues.append(f"{scene_id} 审阅图路径重复：{path}")
                seen_images.add(path)
                if not path.is_file() or path.stat().st_size == 0: issues.append(f"{scene_id} 审阅图不存在或为空：{path}")
                else:
                    size = image_size(path)
                    if size is None: issues.append(f"{scene_id} 审阅图不是可识别的 PNG/JPEG：{path}")
                    elif isinstance(expected_width, int) and isinstance(expected_height, int) and size != (expected_width, expected_height): issues.append(f"{scene_id} 审阅图尺寸 {size} 与项目审阅尺寸 {(expected_width, expected_height)} 不一致：{path}")
            absolute, local = image.get("absolute_time_seconds"), image.get("local_time_seconds")
            if valid_time:
                if not isinstance(absolute, (int, float)) or isinstance(absolute, bool) or not start - TOLERANCE <= absolute <= end + TOLERANCE: issues.append(f"{scene_id} {role} absolute_time_seconds 必须位于场景内")
                if not isinstance(local, (int, float)) or isinstance(local, bool) or not -TOLERANCE <= local <= end - start + TOLERANCE: issues.append(f"{scene_id} {role} local_time_seconds 必须位于局部场景内")
                if isinstance(absolute, (int, float)) and isinstance(local, (int, float)) and abs((absolute - start) - local) > TOLERANCE: issues.append(f"{scene_id} {role} 绝对时间与局部时间不一致")
        status = item.get("review_status")
        if status not in REVIEW_STATES: issues.append(f"{scene_id} review_status 非法：{status}")
        if final:
            if status != "APPROVED": issues.append(f"{scene_id} 尚未获得用户逐场景批准")
            if not isinstance(item.get("approval_ref"), str) or not item["approval_ref"].strip(): issues.append(f"{scene_id} 缺少逐场景 approval_ref")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root"); parser.add_argument("index"); parser.add_argument("--final", action="store_true")
    args = parser.parse_args(); root = Path(args.root).resolve(); index = Path(args.index)
    if not index.is_absolute(): index = root / index
    if not index.is_file(): print(f"错误：索引不存在：{index}"); return 2
    try: data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: print(f"错误：无法读取索引：{exc}"); return 2
    issues = validate(root, data, args.final)
    if issues:
        print(f"P05 场景包检查未通过，共 {len(issues)} 项：")
        for issue in issues: print(f"- {issue}")
        return 1
    print(f"P05 场景包检查通过：{index}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
