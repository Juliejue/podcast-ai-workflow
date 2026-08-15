#!/usr/bin/env python3
"""Deterministically validate final Show Notes against style and final-cut timestamps."""

import argparse
import re
import sys
from pathlib import Path


REQUIRED_MARKERS = (
    "高光内容",
    "时间轴",
    "本期互动",
    "关于《稳稳接住》",
)


def final_timestamps(path):
    timestamps = set()
    pattern = re.compile(r"^\[(\d+):(\d{2})\]\s+")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line.strip())
        if match:
            timestamps.add(int(match.group(1)) * 60 + int(match.group(2)))
    return timestamps


def show_note_timestamps(text):
    found = []
    pattern = re.compile(r"^\s*(?:[-*]\s*)?(\d+):(\d{2})\b")
    for number, line in enumerate(text.splitlines(), 1):
        match = pattern.match(line)
        if match and int(match.group(2)) < 60:
            found.append((number, int(match.group(1)) * 60 + int(match.group(2)), match.group(0).strip()))
    return found


def format_time(seconds):
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def validate(show_notes_path, final_path):
    text = show_notes_path.read_text(encoding="utf-8-sig")
    issues = []

    if re.search(r"[\u2014\u2e3a\u2e3b]|——", text):
        issues.append("正文含破折号字符")
    for match in re.finditer(r"不是[^\n。！？]{0,40}?而是", text):
        excerpt = match.group(0)[:60]
        issues.append(f"含禁用对比句式：{excerpt}")

    for marker in REQUIRED_MARKERS:
        if marker not in text:
            issues.append(f"缺少固定部分：{marker}")
    if "小红书" not in text or "稳稳接住" not in text:
        issues.append("缺少同名小红书账号关注提示")

    allowed = final_timestamps(final_path)
    if not allowed:
        issues.append("成片稿没有可读取的 [分:秒] 时间点")
    timeline = show_note_timestamps(text)
    if not timeline:
        issues.append("Show Notes 没有可读取的时间轴")
    for line_number, seconds, label in timeline:
        if seconds not in allowed:
            issues.append(f"第 {line_number} 行时间点 {label} 不在成片稿中")

    return issues, len(timeline)


def main():
    parser = argparse.ArgumentParser(description="检查《稳稳接住》Show Notes 的硬规则和成片时间点")
    parser.add_argument("show_notes", help="待发布的 Show Notes Markdown 或纯文本")
    parser.add_argument("--成片稿", required=True, help="剪辑后带时间戳逐字稿")
    args = parser.parse_args()

    show_notes = Path(args.show_notes).expanduser().resolve()
    final_transcript = Path(args.成片稿).expanduser().resolve()
    for label, path in (("Show Notes", show_notes), ("成片稿", final_transcript)):
        if not path.is_file():
            sys.exit(f"❌ 找不到{label}：{path}")

    issues, timestamp_count = validate(show_notes, final_transcript)
    if issues:
        print(f"❌ 未通过，共 {len(issues)} 个问题：")
        for issue in issues:
            print(f"   - {issue}")
        raise SystemExit(1)

    print("✅ Show Notes 校验通过")
    print(f"   {timestamp_count} 个时间轴节点全部来自成片稿")
    print("   未发现破折号或禁用对比句式")
    print("   固定结构与小红书关注提示完整")


if __name__ == "__main__":
    main()
