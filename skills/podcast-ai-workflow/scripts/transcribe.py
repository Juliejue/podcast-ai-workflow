#!/usr/bin/env python3
"""
播客工作流｜转写工具

一条命令，把音频变成两份转写稿：
  1. 第N期_转写_带时间戳.txt   给写发布文案、找切片用
  2. 第N期_转写.srt            给剪映导入用

用法：
  python3 tools/transcribe.py episodes/ep05/audio.mp3
  python3 tools/transcribe.py episodes/ep05/audio.mp3 --试跑
  python3 tools/transcribe.py episodes/ep05/audio.mp3 --模型 large-v3

规则：
  - 输出自动放到音频所在的那一期目录里，不用管路径
  - 期数从目录名自动识别
  - 已存在的文件不会被覆盖，会加 _v2 后缀
  - 在播客工作区放 config.json 和 glossary.json；也可用参数显式指定
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ASSETS_DIR = SKILL_DIR / "assets"


def _resolve_settings(filename, example_filename, search_dir=None, explicit=None):
    """Resolve private settings from the user's workspace, never the install dir."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise FileNotFoundError(f"找不到配置文件：{path}")
        return path.resolve()

    roots = []
    if search_dir:
        base = Path(search_dir).expanduser().resolve()
        roots.extend((base, base.parent))
    roots.append(Path.cwd().resolve())
    seen = set()
    for root in roots:
        candidate = root / filename
        if candidate not in seen and candidate.exists():
            return candidate
        seen.add(candidate)
    example = ASSETS_DIR / example_filename
    return example if example.exists() else None


def load_config(search_dir=None, explicit=None):
    """Prefer workspace config.json; otherwise use the bundled anonymous example."""
    path = _resolve_settings("config.json", "config.example.json", search_dir, explicit)
    if not path:
        return {"show_name": "你的播客", "hosts": [], "topics": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_glossary(search_dir=None, explicit=None):
    """读术语表，拍平成 简单替换 + 正则替换 两组。"""
    path = _resolve_settings("glossary.json", "glossary.example.json", search_dir, explicit)
    if not path:
        print("⚠️  找不到 glossary.json 或 glossary.example.json，将不做校正")
        return {}, {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    plain, regex = {}, {}
    for section, entries in raw.items():
        if section.startswith("_") or not isinstance(entries, dict):
            continue
        target = regex if section == "整句校正" else plain
        for wrong, right in entries.items():
            if wrong.startswith("_"):
                continue
            target[wrong] = right
    return plain, regex


def apply_glossary(text, plain, regex):
    """返回 (校正后文本, 本次命中的词表)。"""
    hits = []
    for wrong, right in plain.items():
        if wrong != right and wrong in text:
            hits.append(f"{wrong}→{right}")
            text = text.replace(wrong, right)
    for pattern, repl in regex.items():
        if re.search(pattern, text):
            hits.append(f"[正则] {pattern}")
            text = re.sub(pattern, repl, text)
    return text, hits


def fmt_ts(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def fmt_srt_ts(seconds):
    ms = int((seconds - int(seconds)) * 1000)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def safe_path(path: Path) -> Path:
    """不覆盖已有文件。"""
    if not path.exists():
        return path
    for i in range(2, 100):
        candidate = path.with_name(f"{path.stem}_v{i}{path.suffix}")
        if not candidate.exists():
            print(f"   （{path.name} 已存在，改存为 {candidate.name}）")
            return candidate
    raise RuntimeError("重名文件太多")


def detect_episode(audio: Path) -> str:
    """从路径里认出「第N期」，认不出就用文件名。"""
    for part in [audio.parent.name, audio.stem]:
        m = re.search(r"第[一二三四五六七八九十百零\d]+期", part)
        if m:
            return m.group(0)
    return audio.stem


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("audio", help="音频文件路径")
    ap.add_argument("--模型", dest="model", default="medium",
                    choices=["small", "medium", "large-v3"])
    ap.add_argument("--试跑", dest="trial", action="store_true",
                    help="只转前 3 分钟，用来快速验证效果")
    ap.add_argument("--原始", dest="is_raw", action="store_true",
                    help="标记这是原始录音（还没剪的），文件名会区分开，方便后面做剪辑对比")
    ap.add_argument("--配置", dest="config", help="config.json 路径；相对路径按当前工作目录解析")
    ap.add_argument("--术语表", dest="glossary", help="glossary.json 路径；相对路径按当前工作目录解析")
    ap.add_argument("-h", "--help", action="help", help="看用法")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.is_absolute():
        audio = (Path.cwd() / audio).resolve()
    if not audio.exists():
        sys.exit(f"❌ 找不到音频：{audio}")

    episode = detect_episode(audio)
    outdir = audio.parent
    try:
        plain, regex = load_glossary(audio.parent, args.glossary)
        config = load_config(audio.parent, args.config)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        sys.exit(f"❌ {exc}")

    print(f"🎧 {episode}｜{audio.name}")
    print(f"   模型 {args.model}" + ("｜试跑模式：只转前 3 分钟" if args.trial else ""))
    print(f"   术语表 {len(plain)} 条替换 + {len(regex)} 条正则")
    print(f"   输出目录 {outdir}\n")

    from faster_whisper import WhisperModel

    print("正在加载模型（首次用某个模型需要下载，之后就快了）...")
    t0 = time.time()
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    print(f"   加载完成 {time.time() - t0:.0f}s\n")

    # 把节目名、主播名、主题喂给模型，降低专有名词错误。
    show = config.get("show_name", "你的播客")
    hosts = "、".join(config.get("hosts", []))
    topics = "、".join(config.get("topics", []))
    prompt = f"这是播客《{show}》。"
    if hosts:
        prompt += f"主播是{hosts}。"
    if topics:
        prompt += f"节目聊{topics}。"

    kwargs = dict(language="zh", beam_size=5, vad_filter=True, initial_prompt=prompt)
    if args.trial:
        kwargs["clip_timestamps"] = "0,180"

    print("开始转写，长音频大约需要音频时长的 2/3，中途可以去做别的事...")
    t0 = time.time()
    segments, info = model.transcribe(str(audio), **kwargs)

    lines, srt_blocks, all_hits = [], [], []
    for i, seg in enumerate(segments, 1):
        text, hits = apply_glossary(seg.text.strip(), plain, regex)
        all_hits.extend(hits)
        lines.append(f"[{fmt_ts(seg.start)}] {text}")
        srt_blocks.append(
            f"{i}\n{fmt_srt_ts(seg.start)} --> {fmt_srt_ts(seg.end)}\n{text}\n")
        if i % 30 == 0:
            print(f"   已转写到 {fmt_ts(seg.start)}...")

    elapsed = time.time() - t0
    suffix = ("_原始录音" if args.is_raw else "") + ("_试跑" if args.trial else "")

    txt_path = safe_path(outdir / f"{episode}_转写_带时间戳{suffix}.txt")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    srt_path = safe_path(outdir / f"{episode}_转写{suffix}.srt")
    srt_path.write_text("\n".join(srt_blocks), encoding="utf-8")

    print(f"\n✅ 完成，耗时 {elapsed / 60:.1f} 分钟，共 {len(lines)} 段")
    print(f"   {txt_path.name}   ← 写文案、找切片用这份")
    print(f"   {srt_path.name}   ← 剪映导入用这份")

    if all_hits:
        from collections import Counter
        print(f"\n🔧 术语表自动修正了 {len(all_hits)} 处：")
        for item, n in Counter(all_hits).most_common(12):
            print(f"   {item} ×{n}")
    else:
        print("\n🔧 术语表没有命中（可能是这期没出现那些词）")

    print("\n📌 已知边界：这份转写不区分说话人。")
    print("   谁说的需要人工标，或者剪辑时对着音频听。")
    print("   发现新的听错词，加到工作区的 glossary.json 里，下次自动修。")


if __name__ == "__main__":
    main()
