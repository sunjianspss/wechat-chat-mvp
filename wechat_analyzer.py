#!/usr/bin/env python3
"""
Local WeChat chat analyzer MVP.

It captures visible WeChat chat screens, OCRs screenshots with macOS Vision,
deduplicates repeated lines, and writes local Markdown/JSON outputs.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
HELPER_SRC = ROOT / "helpers" / "ocr_vision.swift"
HELPER_BIN = ROOT / ".bin" / "ocr_vision"
CONTROL_SRC = ROOT / "helpers" / "mac_control.swift"
CONTROL_BIN = ROOT / ".bin" / "mac_control"
DEFAULT_OUT = ROOT / "runs"
ACCESSIBILITY_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
SCREEN_RECORDING_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"


def is_macos() -> bool:
    return sys.platform == "darwin"


PERMISSION_HELP = """
macOS needs two privacy permissions for automatic capture:

1. Accessibility
   System Settings -> Privacy & Security -> Accessibility
   Enable the terminal app you are using, usually Terminal/iTerm/Warp.
   The tool now uses a native Swift helper first; "osascript" is only a fallback.

2. Screen Recording
   System Settings -> Privacy & Security -> Screen Recording
   Enable the same terminal app.

After changing permissions, quit and reopen the terminal, then run:
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py doctor
""".strip()


@dataclasses.dataclass(frozen=True)
class CaptureRect:
    x: int
    y: int
    width: int
    height: int

    def inset(self, crop: tuple[int, int, int, int]) -> "CaptureRect":
        left, top, right, bottom = crop
        width = max(100, self.width - left - right)
        height = max(100, self.height - top - bottom)
        return CaptureRect(self.x + left, self.y + top, width, height)

    def as_screencapture_rect(self) -> str:
        return f"{self.x},{self.y},{self.width},{self.height}"


def run_command(args: list[str], *, check: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, text=text, capture_output=True)


def timestamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def parse_crop(value: str) -> tuple[int, int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("crop must be left,top,right,bottom")
    try:
        crop = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("crop values must be integers") from exc
    if any(item < 0 for item in crop):
        raise argparse.ArgumentTypeError("crop values must be >= 0")
    return crop  # type: ignore[return-value]


def ensure_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"Missing required tool: {name}")
    return path


def require_macos(feature: str) -> None:
    if not is_macos():
        raise SystemExit(
            f"{feature} is macOS-only in this MVP. "
            "On Windows, use `ocr` with `--ocr-engine tesseract` for screenshots, "
            "or `summarize` on an existing text file."
        )


def apple_script(script: str) -> str:
    ensure_tool("osascript")
    result = run_command(["osascript", "-e", script])
    return result.stdout.strip()


def compile_swift_helper(source: Path, binary: Path, label: str) -> Path:
    require_macos(f"{label} helper")
    ensure_tool("swiftc")
    if not source.exists():
        raise SystemExit(f"Missing {label} helper: {source}")
    binary.parent.mkdir(parents=True, exist_ok=True)
    if not binary.exists() or source.stat().st_mtime > binary.stat().st_mtime:
        print(f"[{label}] compiling Swift helper...")
        module_cache = binary.parent / "module-cache"
        module_cache.mkdir(parents=True, exist_ok=True)
        run_command([
            "swiftc",
            "-module-cache-path",
            str(module_cache),
            str(source),
            "-o",
            str(binary),
        ])
    return binary


def ensure_control_helper() -> Path:
    return compile_swift_helper(CONTROL_SRC, CONTROL_BIN, "control")


def activate_app(app_name: str) -> None:
    helper = ensure_control_helper()
    try:
        run_command([str(helper), "activate", app_name])
    except subprocess.CalledProcessError as exc:
        print(f"[capture] native activate failed, trying open -a fallback: {exc.stderr.strip()}")
    for candidate in [app_name, "WeChat", "微信"]:
        subprocess.run(["open", "-a", candidate], text=True, capture_output=True, check=False)
    time.sleep(0.7)


def get_window_rect(app_name: str) -> CaptureRect:
    helper = ensure_control_helper()
    try:
        raw = run_command([str(helper), "bounds", app_name]).stdout.strip()
        x, y, width, height = [int(part) for part in raw.split(",")]
        return CaptureRect(x, y, width, height)
    except subprocess.CalledProcessError as exc:
        native_error = exc.stderr.strip()

    script = f'''
tell application "System Events"
    if not (exists process "{app_name}") then error "Process not found: {app_name}"
    tell process "{app_name}"
        set frontmost to true
        set win to window 1
        set p to position of win
        set s to size of win
        return (item 1 of p as integer) & "," & (item 2 of p as integer) & "," & (item 1 of s as integer) & "," & (item 2 of s as integer)
    end tell
end tell
'''
    try:
        raw = apple_script(script)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        raise SystemExit(
            "Cannot read WeChat window bounds. Open WeChat, select the target chat, "
            "and allow Accessibility permission in System Settings.\n"
            f"Native helper error: {native_error}\n"
            f"AppleScript fallback error: {stderr}\n\n"
            f"{PERMISSION_HELP}"
        ) from exc
    x, y, width, height = [int(part) for part in raw.split(",")]
    return CaptureRect(x, y, width, height)


def scroll_chat(app_name: str, method: str, amount: int, rect: CaptureRect, focus_click: bool = False) -> None:
    if method == "none":
        return
    activate_app(app_name)
    helper = ensure_control_helper()
    focus_x = rect.x + int(rect.width * 0.55)
    focus_y = rect.y + int(rect.height * 0.50)
    if focus_click:
        try:
            run_command([str(helper), "click", str(focus_x), str(focus_y)])
        except subprocess.CalledProcessError as exc:
            print(f"[capture] focus click failed, continuing: {exc.stderr.strip()}")
    if method in {"pageup", "wheel"}:
        try:
            if method == "wheel":
                run_command([str(helper), "wheelAt", str(focus_x), str(focus_y), str(amount)])
            else:
                run_command([str(helper), method, str(amount)])
            return
        except subprocess.CalledProcessError as exc:
            print(f"[capture] native scroll failed, trying AppleScript fallback: {exc.stderr.strip()}")
    if method == "pageup":
        script = f'''
tell application "System Events"
    repeat {amount} times
        key code 116
        delay 0.05
    end repeat
end tell
'''
    elif method == "wheel":
        script = f'''
tell application "System Events"
    repeat {amount} times
        scroll up
        delay 0.05
    end repeat
end tell
'''
    else:
        raise SystemExit(f"Unknown scroll method: {method}")
    try:
        apple_script(script)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "Cannot scroll WeChat. Check Accessibility permission, or retry with "
            "`--scroll-method pageup` / `--scroll-method none`.\n"
            f"AppleScript error: {exc.stderr.strip()}\n\n"
            f"{PERMISSION_HELP}"
        ) from exc


def capture_screenshot(rect: CaptureRect, output: Path) -> None:
    ensure_tool("screencapture")
    output.parent.mkdir(parents=True, exist_ok=True)
    run_command(["screencapture", "-x", "-R", rect.as_screencapture_rect(), str(output)])


def capture(args: argparse.Namespace) -> Path:
    require_macos("Automatic WeChat capture")
    apply_quality_profile(args)
    run_dir = args.output or (DEFAULT_OUT / timestamp())
    screenshots = run_dir / "screenshots"
    metadata_path = run_dir / "capture_meta.json"
    run_dir.mkdir(parents=True, exist_ok=True)

    activate_app(args.app)
    rect = get_window_rect(args.app).inset(args.crop)
    meta = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "app": args.app,
        "screens": args.screens,
        "delay": args.delay,
        "scroll_method": args.scroll_method,
        "scroll_amount": args.scroll_amount,
        "focus_click": args.focus_click,
        "crop": args.crop,
        "rect": dataclasses.asdict(rect),
    }
    metadata_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    for index in range(1, args.screens + 1):
        activate_app(args.app)
        time.sleep(0.15)
        shot = screenshots / f"screen-{index:04d}.png"
        capture_screenshot(rect, shot)
        print(f"[capture] {shot}")
        if index < args.screens:
            scroll_chat(args.app, args.scroll_method, args.scroll_amount, rect, focus_click=args.focus_click)
            time.sleep(args.delay)

    print(f"[capture] done: {run_dir}")
    return run_dir


def apply_quality_profile(args: argparse.Namespace) -> None:
    profile = getattr(args, "quality", "balanced")
    if profile == "balanced":
        return
    if profile == "precise":
        args.scroll_amount = min(args.scroll_amount, 4)
        args.delay = max(args.delay, 1.2)
        if args.crop == (305, 70, 10, 90):
            args.crop = (320, 70, 10, 100)
        return
    raise SystemExit(f"Unknown quality profile: {profile}")


def ensure_ocr_helper() -> Path:
    return compile_swift_helper(HELPER_SRC, HELPER_BIN, "ocr")


def image_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    patterns = ("*.png", "*.jpg", "*.jpeg", "*.tiff", "*.heic")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path.glob(pattern))
    return sorted(files)


def text_quality(line: dict) -> float:
    text = str(line.get("text", ""))
    confidence = float(line.get("confidence", 0))
    useful = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", text))
    noisy = len(re.findall(r"[^A-Za-z0-9\u4e00-\u9fff\s，。！？、：:；;（）()《》<>\"'./+-]", text))
    return confidence + min(useful, 30) * 0.01 - noisy * 0.04


def merge_ocr_passes(primary: list[dict], secondary: list[dict]) -> list[dict]:
    chosen: list[dict] = []
    for line in primary + secondary:
        matched_index = None
        for index, existing in enumerate(chosen):
            same_row = abs(float(line.get("y", 0)) - float(existing.get("y", 0))) < 0.012
            same_column = abs(float(line.get("x", 0)) - float(existing.get("x", 0))) < 0.08
            if same_row and same_column:
                matched_index = index
                break
        if matched_index is None:
            chosen.append(line)
            continue
        if text_quality(line) > text_quality(chosen[matched_index]):
            chosen[matched_index] = line
    return sorted(chosen, key=lambda item: (-float(item.get("y", 0)), float(item.get("x", 0))))


def run_ocr_helper(helper: Path, image: Path, languages: str, scale: float, mode: str) -> list[dict]:
    try:
        result = run_command([str(helper), str(image), languages, str(scale), mode])
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"OCR failed for {image}\n"
            f"stdout: {exc.stdout.strip()}\n"
            f"stderr: {exc.stderr.strip()}"
        ) from exc
    try:
        lines = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"OCR helper returned invalid JSON for {image}") from exc
    for line in lines:
        line["source"] = str(image)
        line["ocr_mode"] = mode
    return lines


def join_ocr_words(words: list[str]) -> str:
    text = " ".join(word for word in words if word.strip())
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text).strip()


def run_tesseract_ocr(image: Path, languages: str) -> list[dict]:
    ensure_tool("tesseract")
    try:
        result = run_command(["tesseract", str(image), "stdout", "-l", languages, "tsv"])
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"Tesseract OCR failed for {image}\n"
            f"stdout: {exc.stdout.strip()}\n"
            f"stderr: {exc.stderr.strip()}\n\n"
            "On Windows, install Tesseract OCR and the Chinese language data "
            "(`chi_sim`) before using this engine."
        ) from exc

    rows = list(csv.DictReader(result.stdout.splitlines(), delimiter="\t"))
    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    max_right = 1
    max_bottom = 1
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row.get("conf") or -1)
            left = int(float(row.get("left") or 0))
            top = int(float(row.get("top") or 0))
            width = int(float(row.get("width") or 0))
            height = int(float(row.get("height") or 0))
        except ValueError:
            continue
        if confidence < 0:
            continue
        max_right = max(max_right, left + width)
        max_bottom = max(max_bottom, top + height)
        key = (
            row.get("page_num") or "1",
            row.get("block_num") or "0",
            row.get("par_num") or "0",
            row.get("line_num") or "0",
        )
        groups.setdefault(key, []).append({
            "text": text,
            "confidence": confidence / 100.0,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        })

    lines: list[dict] = []
    for words in groups.values():
        words = sorted(words, key=lambda item: (item["top"], item["left"]))
        text = join_ocr_words([str(word["text"]) for word in words])
        if not text:
            continue
        left = min(int(word["left"]) for word in words)
        top = min(int(word["top"]) for word in words)
        right = max(int(word["left"]) + int(word["width"]) for word in words)
        bottom = max(int(word["top"]) + int(word["height"]) for word in words)
        confidence = sum(float(word["confidence"]) for word in words) / len(words)
        lines.append({
            "text": text,
            "confidence": confidence,
            "x": left / max_right,
            "y": 1.0 - (bottom / max_bottom),
            "width": (right - left) / max_right,
            "height": (bottom - top) / max_bottom,
            "source": str(image),
            "ocr_mode": "tesseract",
        })
    return sorted(lines, key=lambda item: (-float(item.get("y", 0)), float(item.get("x", 0))))


def ocr_image(helper: Path, image: Path, languages: str, scale: float, mode: str) -> list[dict]:
    if mode != "best":
        return run_ocr_helper(helper, image, languages, scale, mode)
    enhanced = run_ocr_helper(helper, image, languages, scale, "enhanced")
    raw = run_ocr_helper(helper, image, languages, 1.0, "raw")
    return merge_ocr_passes(enhanced, raw)


def resolve_ocr_engine(engine: str) -> str:
    if engine != "auto":
        return engine
    return "vision" if is_macos() else "tesseract"


def ocr(args: argparse.Namespace) -> Path:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input does not exist: {input_path}")

    if args.output:
        out_dir = args.output
    elif input_path.name == "screenshots":
        out_dir = input_path.parent
    elif input_path.is_dir():
        out_dir = input_path
    else:
        out_dir = input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = resolve_ocr_engine(args.ocr_engine)
    helper = ensure_ocr_helper() if engine == "vision" else None
    images = image_files(input_path)
    if not images:
        raise SystemExit(f"No screenshots found in: {input_path}")

    all_lines: list[dict] = []
    for image in images:
        if engine == "vision":
            assert helper is not None
            lines = ocr_image(helper, image, args.languages, args.ocr_scale, args.ocr_mode)
        else:
            lines = run_tesseract_ocr(image, args.tesseract_langs)
        all_lines.extend(lines)
        print(f"[ocr] {image.name}: {len(lines)} lines")

    raw_path = out_dir / "ocr_raw.json"
    text_path = out_dir / "ocr_raw.txt"
    stats_path = out_dir / "ocr_stats.json"
    raw_path.write_text(json.dumps(all_lines, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text("\n".join(line["text"] for line in all_lines) + "\n", encoding="utf-8")
    stats = {
        "images": len(images),
        "lines": len(all_lines),
        "avg_confidence": (
            sum(float(line.get("confidence", 0)) for line in all_lines) / len(all_lines)
            if all_lines else 0
        ),
        "ocr_mode": args.ocr_mode,
        "ocr_engine": engine,
        "ocr_scale": args.ocr_scale,
        "languages": args.languages if engine == "vision" else args.tesseract_langs,
    }
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ocr] wrote: {raw_path}")
    return out_dir


def raw_lines_from_text(path: Path) -> list[dict]:
    lines: list[dict] = []
    for index, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = text.strip()
        if not text:
            continue
        lines.append({
            "text": text,
            "confidence": 1.0,
            "x": 0.1,
            "y": 0.5,
            "width": 0.8,
            "height": 0.02,
            "source": str(path),
            "line_number": index,
        })
    return lines


NOISE_PATTERNS = [
    r"^\d+:\d+$",
    r"^\d{1,2}:\d{2}$",
    r"^微信$",
    r"^WeChat$",
    r"^搜索$",
    r"^发送$",
    r"^按住说话$",
    r"^.*正在输入.*$",
    r"^[-~./A-Za-z0-9_]+/wechat-chat-mvp/.*$",
    r"^.*ocr_raw\.json$",
    r"^.*summary\.md$",
    r"^%.*$",
    r"^\$.*$",
    r"^\.\/run_wechat\.sh.*$",
    r"^/usr/bin/osascript$",
    r"^\d{2}/\d{2}$",
    r"^[UuVv][0-9oOlI]+/[0-9oOlI]+$",
    r"^[\^•·.。,\-—_~、:：]+$",
    r"^\^?\s*\d+\s*条新消息$",
    r"^加载\s*ing$",
    r"^部推到.*$",
    r"^务器的.*$",
    r"^系统优.*$",
    r"^优化项.*$",
    r"^程序员的乐.*共\d+条$",
]


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("：", ":")
    return text


def useful_char_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", text))


def is_noise(text: str, line: dict | None = None) -> bool:
    if len(text) <= 1:
        return True
    confidence = float(line.get("confidence", 1.0)) if line else 1.0
    useful = useful_char_count(text)
    # Vision often assigns high confidence to sidebar dates or tiny UI labels.
    # Keep low-confidence short lines out of the transcript unless they carry enough content.
    if confidence < 0.35:
        return True
    if confidence < 0.55 and useful < 8:
        return True
    if line:
        x = float(line.get("x", 0.0))
        y = float(line.get("y", 0.0))
        # Left-edge fragments usually come from the WeChat conversation list
        # when crop is too loose. Top/bottom chrome also tends to be UI, not chat.
        if x < 0.045 and useful < 10:
            return True
        if y > 0.965 or y < 0.025:
            return True
    if len(re.sub(r"[A-Za-z0-9\u4e00-\u9fff]", "", text)) > max(12, len(text) * 0.55):
        return True
    return any(re.match(pattern, text, re.IGNORECASE) for pattern in NOISE_PATTERNS)


def line_fingerprint(text: str) -> str:
    normalized = re.sub(r"\W+", "", normalize_text(text).lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def clean_lines(raw_lines: Iterable[dict], fuzzy_window: int = 60) -> list[dict]:
    cleaned: list[dict] = []
    recent: list[str] = []
    for line in raw_lines:
        text = normalize_text(str(line.get("text", "")))
        if is_noise(text, line):
            continue
        fp = line_fingerprint(text)
        if fp in recent:
            continue
        item = dict(line)
        item["text"] = text
        item["fingerprint"] = fp
        cleaned.append(item)
        recent.append(fp)
        if len(recent) > fuzzy_window:
            recent.pop(0)
    return cleaned


def clean_stats(raw_lines: list[dict], cleaned: list[dict]) -> dict:
    raw_count = len(raw_lines)
    avg_raw_conf = (
        sum(float(line.get("confidence", 0)) for line in raw_lines) / raw_count
        if raw_count else 0
    )
    avg_clean_conf = (
        sum(float(line.get("confidence", 0)) for line in cleaned) / len(cleaned)
        if cleaned else 0
    )
    return {
        "raw_lines": raw_count,
        "cleaned_lines": len(cleaned),
        "removed_lines": raw_count - len(cleaned),
        "removed_ratio": (raw_count - len(cleaned)) / raw_count if raw_count else 0,
        "avg_raw_confidence": avg_raw_conf,
        "avg_clean_confidence": avg_clean_conf,
    }


def extract_candidates(lines: list[dict], patterns: list[str]) -> list[str]:
    regex = re.compile("|".join(patterns), re.IGNORECASE)
    hits = []
    for line in lines:
        text = line["text"]
        if regex.search(text):
            hits.append(text)
    return hits[:80]


def keyword_counts(lines: list[dict]) -> list[tuple[str, int]]:
    text = "\n".join(line["text"] for line in lines)
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_+-]{2,}", text)
    stop = {
        "这个", "那个", "然后", "就是", "可以", "不是", "没有", "一下", "已经", "我们",
        "你们", "他们", "今天", "明天", "昨天", "因为", "所以", "如果", "还是", "但是",
        "什么", "怎么", "一个", "现在", "需要", "确认", "微信", "聊天",
    }
    counter = Counter(token for token in tokens if token not in stop)
    return counter.most_common(30)


TOPIC_RULES: list[dict] = [
    {
        "name": "AI 开发工具与技术栈",
        "keywords": ["codex", "agent", "ai", "coding", "claude", "openai", "react", "tailwind", "shadcn", "nextjs", "vite", "vue", "electron", "coze"],
        "min_hits": 5,
    },
    {
        "name": "消息整理/自动总结工具",
        "keywords": ["聊天记录", "消息总结", "钉钉消息总结", "微信本地解析", "本地解析", "导出聊天", "ocr"],
        "min_hits": 2,
    },
    {
        "name": "模型/API 价格与额度",
        "keywords": ["价格", "降价", "token", "额度", "重置", "购买", "支付", "信用卡", "5x", "10x"],
        "min_hits": 4,
    },
    {
        "name": "Mac/硬件配置",
        "keywords": ["黑苹果", "内存", "硬盘", "芯片", "散热", "虚拟机", "32g", "64g", "gpu", "xps", "i9"],
        "min_hits": 5,
    },
]


def topic_digest(lines: list[dict]) -> list[tuple[str, int, list[str]]]:
    results: list[tuple[str, int, list[str]]] = []
    for rule in TOPIC_RULES:
        topic = str(rule["name"])
        keywords = list(rule["keywords"])
        min_hits = int(rule["min_hits"])
        hits: list[str] = []
        for line in lines:
            text = line["text"]
            lowered = text.lower()
            if any(keyword.lower() in lowered for keyword in keywords):
                if text not in hits:
                    hits.append(text)
        if len(hits) >= min_hits:
            results.append((topic, len(hits), hits[:8]))
    return sorted(results, key=lambda item: item[1], reverse=True)


def compact_overview(topics: list[tuple[str, int, list[str]]], keywords: list[tuple[str, int]]) -> list[str]:
    overview: list[str] = []
    for topic, count, examples in topics[:4]:
        sample = "；".join(examples[:2])
        overview.append(f"{topic} 是本次较明显的话题之一，识别到 {count} 条相关线索，例如：{sample}")
    if not overview and keywords:
        top_words = "、".join(word for word, _ in keywords[:8])
        overview.append(f"本次内容较分散，未达到明确话题阈值；高频词包括：{top_words}")
    return overview


def write_markdown(out_dir: Path, lines: list[dict]) -> Path:
    summary_path = out_dir / "summary.md"
    transcript_path = out_dir / "chat_clean.md"
    clean_json_path = out_dir / "chat_clean.json"

    clean_json_path.write_text(json.dumps(lines, ensure_ascii=False, indent=2), encoding="utf-8")
    transcript_path.write_text("\n".join(f"- {line['text']}" for line in lines) + "\n", encoding="utf-8")

    todos = extract_candidates(lines, [
        "待办", "记得", "麻烦", "帮我", "需要", "确认", "安排", "处理", "发我", "给我",
        "尽快", "截止", "deadline", "todo", "follow up",
    ])
    dates = extract_candidates(lines, [
        r"\d{1,2}[月/-]\d{1,2}", "今天", "明天", "后天", "昨天", "周一", "周二", "周三",
        "周四", "周五", "周六", "周日", "星期", "上午", "下午", "晚上", "deadline",
    ])
    questions = [line["text"] for line in lines if "?" in line["text"] or "？" in line["text"]][:80]
    keywords = keyword_counts(lines)
    topics = topic_digest(lines)
    overview = compact_overview(topics, keywords)

    parts = [
        "# 微信聊天记录自动整理",
        "",
        f"- 生成时间: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"- 清洗后文本行数: {len(lines)}",
        "",
        "## 核心摘要",
        "",
    ]
    if overview:
        parts.extend(f"- {item}" for item in overview)
    elif lines:
        parts.append("- 本次采集到的内容较分散，未形成明显单一主题；建议查看下面的主题线索和清洗记录。")
    else:
        parts.append("- 没有识别到可用聊天文本。")

    parts.extend([
        "",
        "## 主要话题",
        "",
    ])
    if topics:
        for topic, count, examples in topics[:6]:
            parts.append(f"### {topic}（{count} 条相关线索）")
            parts.extend(f"- {example}" for example in examples[:5])
            parts.append("")
    else:
        parts.append("- 暂无明显话题聚类")

    parts.extend([
        "## 高频关键词",
        "",
    ])
    if keywords:
        parts.extend(f"- {word}: {count}" for word, count in keywords)
    else:
        parts.append("- 暂无")

    parts.extend(["", "## 可能的待办/承诺", ""])
    parts.extend(f"- {item}" for item in todos) if todos else parts.append("- 暂无明显待办")

    parts.extend(["", "## 时间线线索", ""])
    parts.extend(f"- {item}" for item in dates) if dates else parts.append("- 暂无明显时间信息")

    parts.extend(["", "## 问题与需确认事项", ""])
    parts.extend(f"- {item}" for item in questions) if questions else parts.append("- 暂无明显问题")

    parts.extend([
        "",
        "## 原始清洗记录",
        "",
        f"完整记录见 `{transcript_path.name}`，结构化数据见 `{clean_json_path.name}`。",
        "",
    ])
    summary_path.write_text("\n".join(parts), encoding="utf-8")
    return summary_path


def summarize(args: argparse.Namespace) -> Path:
    input_path = Path(args.input).expanduser().resolve()
    if input_path.is_dir():
        raw_path = input_path / "ocr_raw.json"
        out_dir = input_path
        if not raw_path.exists():
            raise SystemExit(
                f"OCR JSON not found: {raw_path}\n"
                "For Windows/manual use, pass a text file directly: "
                "`python wechat_analyzer.py summarize chat.txt -o runs/manual`."
            )
        raw_lines = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
        if not input_path.exists():
            raise SystemExit(f"Input does not exist: {input_path}")
        if input_path.suffix.lower() == ".json":
            raw_path = input_path
            out_dir = args.output or input_path.parent
            raw_lines = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            out_dir = args.output or (DEFAULT_OUT / timestamp())
            raw_lines = raw_lines_from_text(input_path)
    lines = clean_lines(raw_lines, fuzzy_window=args.dedupe_window)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "clean_stats.json").write_text(
        json.dumps(clean_stats(raw_lines, lines), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path = write_markdown(out_dir, lines)
    print(f"[summarize] wrote: {summary_path}")
    return out_dir


def run_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    dirs = [path for path in root.iterdir() if path.is_dir()]
    return sorted(dirs, key=lambda path: path.stat().st_mtime, reverse=True)


def dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def cleanup(args: argparse.Namespace) -> None:
    root = Path(args.runs_dir).expanduser().resolve()
    dirs = run_dirs(root)
    if not dirs:
        print(f"[cleanup] no run directories found: {root}")
        return

    cutoff = time.time() - args.older_than_days * 86400
    keep = set(dirs[: args.keep_latest])
    candidates = [
        path for path in dirs
        if path not in keep and path.stat().st_mtime < cutoff
    ]

    total = sum(dir_size(path) for path in candidates)
    action = "deleting" if args.yes else "would delete"
    print(f"[cleanup] runs dir: {root}")
    print(f"[cleanup] keeping latest: {args.keep_latest}, older than days: {args.older_than_days}")
    print(f"[cleanup] {action}: {len(candidates)} dirs, {format_bytes(total)}")

    for path in candidates:
        age_days = (time.time() - path.stat().st_mtime) / 86400
        print(f"- {path.name} ({age_days:.1f} days, {format_bytes(dir_size(path))})")
        if args.yes:
            shutil.rmtree(path)

    if not args.yes:
        print("[cleanup] dry run only. Add --yes to actually delete these directories.")


def doctor(args: argparse.Namespace) -> None:
    print(f"[doctor] platform: {sys.platform}")
    print("[doctor] checking local tools")
    tools = ["uv"]
    tools.extend(["screencapture", "osascript", "swiftc"] if is_macos() else ["tesseract"])
    for tool in tools:
        path = shutil.which(tool)
        status = path or "missing"
        print(f"- {tool}: {status}")

    if not is_macos():
        print("[doctor] Windows/Linux mode: automatic WeChat capture is not available")
        print("- use: python wechat_analyzer.py summarize chat.txt -o runs/manual")
        print("- optional OCR: install Tesseract, then run `ocr --ocr-engine tesseract`")
        return

    print("[doctor] checking OCR helper")
    try:
        helper = ensure_ocr_helper()
        print(f"- ocr helper: {helper}")
    except Exception as exc:  # noqa: BLE001 - diagnostic command should print any local failure.
        print(f"- ocr helper: failed: {exc}")

    print("[doctor] checking control helper")
    try:
        helper = ensure_control_helper()
        print(f"- control helper: {helper}")
    except Exception as exc:  # noqa: BLE001 - diagnostic command should print any local failure.
        print(f"- control helper: failed: {exc}")

    print(f"[doctor] checking app window: {args.app}")
    try:
        rect = get_window_rect(args.app)
        print(f"- window: x={rect.x}, y={rect.y}, width={rect.width}, height={rect.height}")
    except SystemExit as exc:
        print(f"- window: failed: {exc}")
        print("- hint: run `python wechat_analyzer.py permissions --open` to open the settings pages")


def permissions(args: argparse.Namespace) -> None:
    require_macos("macOS privacy permissions")
    print(PERMISSION_HELP)
    if args.open:
        ensure_tool("open")
        for url in [ACCESSIBILITY_URL, SCREEN_RECORDING_URL]:
            subprocess.run(["open", url], check=False)
        print("\n[permissions] opened Accessibility and Screen Recording settings pages")


def run_all(args: argparse.Namespace) -> Path:
    run_dir = capture(args)
    ocr_args = argparse.Namespace(
        input=run_dir / "screenshots",
        output=run_dir,
        languages=args.languages,
        tesseract_langs=args.tesseract_langs,
        ocr_scale=args.ocr_scale,
        ocr_mode=args.ocr_mode,
        ocr_engine=args.ocr_engine,
    )
    ocr(ocr_args)
    summarize_args = argparse.Namespace(input=run_dir, output=run_dir, dedupe_window=args.dedupe_window)
    summarize(summarize_args)
    print(f"[run] done: {run_dir}")
    return run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local WeChat screenshot/OCR analyzer MVP")
    sub = parser.add_subparsers(dest="command", required=True)

    capture_parser = sub.add_parser("capture", help="Capture the visible WeChat chat and scroll upward")
    add_capture_args(capture_parser)
    capture_parser.set_defaults(func=capture)

    ocr_parser = sub.add_parser("ocr", help="OCR a screenshot file or folder")
    ocr_parser.add_argument("input", help="Screenshot file/folder, or a run/screenshots folder")
    ocr_parser.add_argument("-o", "--output", type=Path, help="Output directory")
    ocr_parser.add_argument("--ocr-engine", choices=["auto", "vision", "tesseract"], default="auto", help="OCR engine. auto uses macOS Vision on macOS and Tesseract elsewhere")
    ocr_parser.add_argument("--languages", default="zh-Hans,en-US", help="Vision OCR languages, or auto")
    ocr_parser.add_argument("--tesseract-langs", default="chi_sim+eng", help="Tesseract language set, for example chi_sim+eng")
    ocr_parser.add_argument("--ocr-scale", type=float, default=1.5, help="Upscale factor before OCR")
    ocr_parser.add_argument("--ocr-mode", choices=["best", "enhanced", "raw"], default="best", help="Image preprocessing mode")
    ocr_parser.set_defaults(func=ocr)

    summarize_parser = sub.add_parser("summarize", help="Clean OCR JSON and write summary Markdown")
    summarize_parser.add_argument("input", help="Run directory or ocr_raw.json")
    summarize_parser.add_argument("-o", "--output", type=Path, help="Output directory")
    summarize_parser.add_argument("--dedupe-window", type=int, default=60, help="Recent-line dedupe window")
    summarize_parser.set_defaults(func=summarize)

    cleanup_parser = sub.add_parser("cleanup", help="Delete old run directories with a dry-run by default")
    cleanup_parser.add_argument("--runs-dir", type=Path, default=DEFAULT_OUT, help="Runs directory to clean")
    cleanup_parser.add_argument("--older-than-days", type=int, default=14, help="Delete runs older than this many days")
    cleanup_parser.add_argument("--keep-latest", type=int, default=10, help="Always keep this many newest runs")
    cleanup_parser.add_argument("--yes", action="store_true", help="Actually delete matched run directories")
    cleanup_parser.set_defaults(func=cleanup)

    doctor_parser = sub.add_parser("doctor", help="Check local tools, OCR helper, and WeChat window access")
    doctor_parser.add_argument("--app", default="微信", help="macOS app/process name")
    doctor_parser.set_defaults(func=doctor)

    permissions_parser = sub.add_parser("permissions", help="Show or open required macOS privacy settings")
    permissions_parser.add_argument("--open", action="store_true", help="Open Accessibility and Screen Recording settings")
    permissions_parser.set_defaults(func=permissions)

    run_parser = sub.add_parser("run", help="Capture, OCR, clean, and summarize in one command")
    add_capture_args(run_parser)
    run_parser.add_argument("--ocr-engine", choices=["auto", "vision", "tesseract"], default="auto", help="OCR engine. macOS capture normally uses Vision")
    run_parser.add_argument("--languages", default="zh-Hans,en-US", help="Vision OCR languages, or auto")
    run_parser.add_argument("--tesseract-langs", default="chi_sim+eng", help="Tesseract language set when using --ocr-engine tesseract")
    run_parser.add_argument("--ocr-scale", type=float, default=1.5, help="Upscale factor before OCR")
    run_parser.add_argument("--ocr-mode", choices=["best", "enhanced", "raw"], default="best", help="Image preprocessing mode")
    run_parser.add_argument("--dedupe-window", type=int, default=60, help="Recent-line dedupe window")
    run_parser.set_defaults(func=run_all)
    return parser


def add_capture_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app", default="微信", help="macOS app/process name")
    parser.add_argument("--screens", type=int, default=20, help="Number of screens to capture")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay after each scroll")
    parser.add_argument("--scroll-method", choices=["pageup", "wheel", "none"], default="wheel")
    parser.add_argument("--scroll-amount", type=int, default=5, help="PageUp presses or wheel ticks per screen")
    parser.add_argument(
        "--quality",
        choices=["balanced", "precise"],
        default="balanced",
        help="Capture profile. precise uses smaller scrolls and more overlap.",
    )
    parser.add_argument(
        "--focus-click",
        action="store_true",
        help="Click the chat area before scrolling. Off by default to avoid opening images/videos.",
    )
    parser.add_argument(
        "--crop",
        type=parse_crop,
        default=(305, 70, 10, 90),
        help="Crop inside WeChat window as left,top,right,bottom",
    )
    parser.add_argument("-o", "--output", type=Path, help="Run output directory")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
