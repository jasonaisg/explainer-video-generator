#!/usr/bin/env python3
"""Probe picture-locked MP4 and canonical MP3 with FFprobe."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def probe(path: Path, ffprobe: str) -> dict:
    result = subprocess.run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode: raise RuntimeError(result.stderr.strip() or f"ffprobe failed: {path}")
    return json.loads(result.stdout)


def duration(data: dict) -> float:
    values = [data.get("format", {}).get("duration")]
    values += [s.get("duration") for s in data.get("streams", [])]
    nums = [float(x) for x in values if x not in (None, "N/A")]
    if not nums: raise RuntimeError("媒体没有可读时长")
    return max(nums)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--video", required=True); p.add_argument("--audio", required=True); p.add_argument("--output", required=True); p.add_argument("--tolerance", type=float, default=0.25); p.add_argument("--ffprobe", default="ffprobe")
    args = p.parse_args(); video = Path(args.video).resolve(); audio = Path(args.audio).resolve()
    if not video.is_file() or not audio.is_file(): raise SystemExit("MP4 或 MP3 不存在")
    try: vp = probe(video, args.ffprobe); ap = probe(audio, args.ffprobe); vd = duration(vp); ad = duration(ap)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc: print(f"ERROR: {exc}"); return 2
    has_video = any(s.get("codec_type") == "video" for s in vp.get("streams", [])); has_audio = any(s.get("codec_type") == "audio" for s in ap.get("streams", []))
    delta = abs(vd - ad); ok = has_video and has_audio and delta <= args.tolerance
    report = {"video_path": str(video), "audio_path": str(audio), "video_duration": vd, "audio_duration": ad, "duration_delta": delta, "tolerance": args.tolerance, "video_stream_present": has_video, "audio_stream_present": has_audio, "duration_check": "PASS" if ok else "FAIL", "note": "时长通过不等于内容同源；P01 仍须检查首尾和内部语音地标。", "video_probe": vp, "audio_probe": ap}
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"媒体探测 {'通过' if ok else '失败'}：delta={delta:.3f}s，报告={out}"); return 0 if ok else 1


if __name__ == "__main__": raise SystemExit(main())
