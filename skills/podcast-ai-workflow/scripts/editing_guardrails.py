#!/usr/bin/env python3
"""Build an evidence-first editing guardrail card from raw and rough-cut transcripts."""

import argparse
import json
import sys
from pathlib import Path

from analysis_metrics import parse_clock
from compare_edits import 计算一期, 时间, 结构类型


STRONG_PRODUCTION_PHRASES = (
    "正式开始", "再试一次", "录完了吗", "关掉吧", "开始录了吗",
    "结束录制", "关录制", "录上了吗", "后面都剪掉",
)

PRODUCTION_MARKERS = (
    "麦克风", "设备", "耳机", "回声", "音量", "一二三", "录制",
)

TYPE_RATIONALES = {
    "录制事务": (
        "可能属于听众不需要的制作过程，适合优先回听确认。",
        "自然开场和两位主播的关系感有时也会出现在准备阶段，仍需确认边界。",
    ),
    "具体经历": (
        "如果相同经历已经有更具体的一版，这一段可能可以缩短。",
        "具体经历常承担人物可信度、情绪递进和节目辨识度，误删风险较高。",
    ),
    "互动问答": (
        "连续追问若没有推动主问题，可能形成一句一接的乒乓感。",
        "追问、复述和情绪承接可能正是两位主播互相接住的时刻。",
    ),
    "观点判断": (
        "同一观点如果出现多次，可以比较哪一版最具体、最有转折。",
        "这段可能承担本期核心论点或后文成立所需的解释。",
    ),
    "过渡铺垫": (
        "铺垫过长时可能延迟主问题进入。",
        "删掉铺垫可能让后文显得突然，或让听众失去理解所需的上下文。",
    ),
    "其他表达": (
        "它没有被关键词分类，需要结合上下文判断是否偏离主线。",
        "无法分类不等于没有价值，它可能包含节目风格、关系感或意外发现。",
    ),
}


def resolve_path(value, episode_dir):
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    episode_candidate = episode_dir / path
    return episode_candidate if episode_candidate.exists() else Path.cwd() / path


def load_intent(path):
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("创作意图需要是 JSON 对象")
    return data


def safe_output(path):
    if not path.exists():
        return path
    for index in range(2, 100):
        candidate = path.with_name(f"{path.stem}_v{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("同名护栏卡太多，请整理后重试")


def overlap(start, end, protected_start, protected_end):
    return start < protected_end and end > protected_start


def protection_matches(segment, intent):
    matches = []
    for item in intent.get("must_keep", []):
        if not isinstance(item, dict) or not item.get("start"):
            continue
        start = parse_clock(item["start"])
        end = parse_clock(item.get("end", item["start"]))
        end = max(end, start + 1)
        if overlap(segment["起"], segment["止"], start, end):
            matches.append(item.get("label") or f"必留区间 {item['start']}")
    for keyword in intent.get("protected_keywords", []):
        if keyword and str(keyword) in segment["文本"]:
            matches.append(f"保护词：{keyword}")
    return matches


def classify(segment, intent):
    protected = protection_matches(segment, intent)
    segment_type = 结构类型(segment["文本"])
    if protected:
        return "红色｜受保护", segment_type, protected
    strong_match = any(phrase in segment["文本"] for phrase in STRONG_PRODUCTION_PHRASES)
    marker_count = sum(1 for marker in PRODUCTION_MARKERS if marker in segment["文本"])
    if strong_match or marker_count >= 2:
        return "绿色｜低编辑风险", segment_type, []
    return "黄色｜需结合上下文", segment_type, []


def markdown_escape(text):
    return text.replace("|", "／").replace("\n", " ")


def build_card(data, intent, history_path=None):
    segments = data["片段"]
    rows = []
    for segment in segments:
        risk, segment_type, protected = classify(segment, intent)
        shorten_reason, keep_reason = TYPE_RATIONALES.get(segment_type, TYPE_RATIONALES["其他表达"])
        if protected:
            shorten_reason = "受创作意图保护，不生成删除建议。"
            keep_reason = "；".join(protected)
        elif risk.startswith("绿色"):
            shorten_reason = "片段含明显制作流程线索，听众通常不需要这部分信息。"
            keep_reason = "仍需确认候选边界没有带入自然开场、正式结尾或有价值的关系互动。"
        rows.append({
            "segment": segment,
            "risk": risk,
            "type": segment_type,
            "protected": protected,
            "shorten": shorten_reason,
            "keep": keep_reason,
            "source": "创作意图 + 当前转写对比" if protected else "当前原始稿与粗剪稿",
        })

    lines = []
    add = lines.append
    add(f"# {data['期目录'].name} 剪辑护栏卡")
    add("")
    add("> 这是一份粗剪后的证据卡。它不自动删除内容，不承诺流量结果，最终决定由主播回听后填写。")
    add("")
    add("## 本期创作意图")
    add("")
    intent_fields = (
        ("本期问题", "episode_question"),
        ("听众带走什么", "listener_takeaway"),
        ("主要叙事者", "lead_host"),
        ("希望保留的感受", "desired_feeling"),
        ("本期唯一实验", "experiment"),
    )
    for label, key in intent_fields:
        add(f"- **{label}**：{intent.get(key) or '未填写'}")
    add("")
    if intent.get("signature_digressions"):
        add("**节目风格中需要保护的发散**")
        add("")
        for item in intent["signature_digressions"]:
            add(f"- {item}")
        add("")

    add("## 证据总览")
    add("")
    add(f"- 原始稿：`{data['原始路径'].name}`，时间轴覆盖 {时间(data['原始总长'])}")
    add(f"- 粗剪稿：`{data['成片路径'].name}`，时间轴覆盖 {时间(data['成片总长'])}")
    add(f"- 逐字对齐率：{data['对齐率']:.1%}")
    add(f"- 疑似删除候选：{len(rows)} 段")
    add(f"- 历史复盘：`{history_path.name}`" if history_path else "- 历史复盘：未提供，本卡不引用跨期表现结论")
    add("")

    add("## 候选清单")
    add("")
    add("| 原始时间 | 类型 | 风险 | 证据来源 | 置信度 | 考虑缩短的理由 | 考虑保留的理由 | 人工决定 |")
    add("|---|---|---|---|---|---|---|---|")
    for row in rows:
        segment = row["segment"]
        decision = "□保留　□回听" if row["risk"].startswith("红色") else "□保留　□缩短　□删除　□回听"
        add(
            f"| {时间(segment['起'])}–{时间(segment['止'])} | {row['type']} | {row['risk']} | {row['source']} | "
            f"{segment['置信']} | {markdown_escape(row['shorten'])} | {markdown_escape(row['keep'])} | "
            f"{decision} |"
        )
    add("")

    add("## 回听详情")
    add("")
    for index, row in enumerate(rows, 1):
        segment = row["segment"]
        add(f"### {index}. {时间(segment['起'])}–{时间(segment['止'])}｜{row['risk']}")
        add("")
        add(f"- 片段作用线索：{row['type']}")
        add(f"- 证据来源：{row['source']}")
        add(f"- 考虑缩短：{row['shorten']}")
        add(f"- 考虑保留：{row['keep']}")
        add(f"- 对齐置信度：{segment['置信']}，误差覆盖 {segment['误差覆盖']:.1%}")
        add("")
        add(f"> {segment['文本'][:500]}{'……' if len(segment['文本']) > 500 else ''}")
        add("")

    add("## 最终检查")
    add("")
    add("- 红色片段只能标记保留或回听，不能由工具建议直接删除。")
    add("- 黄色片段必须同时考虑删后收益和上下文损失。")
    add("- 绿色片段仍需确认边界没有包含正式内容。")
    add("- 本期只验证一个实验，其他观察留到发布后复盘。")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="从原始稿和粗剪稿生成证据优先的剪辑护栏卡")
    parser.add_argument("episode", help="单集目录")
    parser.add_argument("--原始稿", required=True, help="完整原始录音转写")
    parser.add_argument("--粗剪稿", required=True, help="第一轮粗剪转写")
    parser.add_argument("--创作意图", dest="intent", help="editing_intent.json")
    parser.add_argument("--历史复盘", dest="history", help="可选的跨期复盘文件")
    parser.add_argument("--输出", dest="output", help="输出 Markdown 路径")
    args = parser.parse_args()

    episode_dir = Path(args.episode).expanduser()
    if not episode_dir.is_absolute():
        episode_dir = Path.cwd() / episode_dir
    episode_dir = episode_dir.resolve()
    if not episode_dir.is_dir():
        sys.exit(f"❌ 找不到单集目录：{episode_dir}")

    raw_path = resolve_path(args.原始稿, episode_dir)
    rough_path = resolve_path(args.粗剪稿, episode_dir)
    intent_path = resolve_path(args.intent, episode_dir)
    history_path = resolve_path(args.history, episode_dir)
    for label, path in (("原始稿", raw_path), ("粗剪稿", rough_path)):
        if not path or not path.is_file():
            sys.exit(f"❌ 找不到{label}：{path}")
    for label, path in (("创作意图", intent_path), ("历史复盘", history_path)):
        if path and not path.is_file():
            sys.exit(f"❌ 找不到{label}：{path}")

    try:
        intent = load_intent(intent_path)
        data = 计算一期(episode_dir, str(raw_path), str(rough_path))
    except (ValueError, json.JSONDecodeError) as exc:
        sys.exit(f"❌ {exc}")

    output = Path(args.output).expanduser() if args.output else episode_dir / f"{episode_dir.name}_剪辑护栏卡.md"
    if not output.is_absolute():
        output = Path.cwd() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output = safe_output(output)
    output.write_text(build_card(data, intent, history_path), encoding="utf-8")
    print(f"✅ 完成：{output}")
    print("📌 卡片同时展示缩短与保留理由，不会修改音频，也不承诺流量结果。")


if __name__ == "__main__":
    main()
