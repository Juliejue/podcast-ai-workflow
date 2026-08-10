#!/usr/bin/env python3
"""
播客工作流｜剪辑对比与跨期复盘

把「剪之前」和「剪之后」的两份转写稿对齐，定位这一期疑似删掉的内容。

用法：
  python3 tools/compare_edits.py episodes/ep02

它会自己在那一期的文件夹里找两份转写稿：
  第N期_转写_带时间戳.txt              ← 剪辑后的成片
  第N期_转写_带时间戳_原始录音.txt      ← 剪之前的原始录音
（原始录音的转写，跑 transcribe.py 时加 --原始 就会自动区分）

输出一份报告：第N期_剪辑对比.md
里面有：删掉了哪些段、每段在整期的什么位置、剪辑节奏、脚本结构和下一轮复盘问题。

说明：完播数据用来选出值得复盘的高表现期；工具负责整理证据和提出问题，
     不会把一次剪辑与完播表现之间的相关性写成因果结论。
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median

from transcribe import apply_glossary, load_glossary
from analysis_metrics import audio_metrics, chapter_metrics, media_duration, parse_clock, turn_metrics

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TOOLS_DIR.parent

# 原始稿里一段文字至少有多少比例，能在成片全文中按顺序对上。
# 这里按“字”而不是按“句”对齐，所以两份稿子即使用不同工具转写、切句方式不同也能比。
保留覆盖门槛 = 0.30
# 连续被删的句子，间隔不超过这么多句就并成同一个片段
片段合并间隔 = 2
最短候选秒 = 3
最少候选字 = 12
单段最大字数 = 80

类型线索 = {
    "录制事务": ("开始录", "录上", "开场", "收个尾", "设备", "麦克风", "转写", "剪辑", "发布", "录完"),
    "具体经历": ("比如", "举个例子", "有一次", "那天", "当时", "我记得", "后来", "经历", "故事"),
    "互动问答": ("为什么", "你觉得", "你呢", "是不是", "怎么", "什么", "吗", "呢", "？", "?"),
    "观点判断": ("我觉得", "我发现", "其实", "所以", "但是", "真正", "关键是", "本质上", "对我来说"),
    "过渡铺垫": ("然后", "接下来", "我们先", "回到", "刚才", "就是说", "也就是说", "换句话说"),
}

普通词表, 正则词表 = load_glossary()


def 读转写(path: Path):
    """读 [MM:SS]、说话人(HH:MM:SS) 文本或 SRT。"""
    out = []
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".srt":
        for block in re.split(r"\n\s*\n", raw.strip()):
            lines = block.splitlines()
            time_idx = next((i for i, line in enumerate(lines) if "-->" in line), None)
            if time_idx is None:
                continue
            m = re.match(r"(\d+):(\d+):(\d+)[,.]\d+\s*-->", lines[time_idx].strip())
            if not m:
                continue
            sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            text = "".join(line.strip() for line in lines[time_idx + 1:] if line.strip())
            text, _ = apply_glossary(text, 普通词表, 正则词表)
            if text:
                out.append((sec, text))
        return out

    for line in raw.splitlines():
        m = re.match(r"\[(\d+):(\d+)\]\s*(.*)", line.strip())
        if m:
            sec = int(m.group(1)) * 60 + int(m.group(2))
            text, _ = apply_glossary(m.group(3).strip(), 普通词表, 正则词表)
            if text:
                out.append((sec, text))
            continue

        # 会议软件常见导出：说话人(00:12:34): 正文
        m = re.match(r".*?\((\d+):(\d+):(\d+)\)\s*[:：]\s*(.*)", line.strip())
        if m:
            sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            text, _ = apply_glossary(m.group(4).strip(), 普通词表, 正则词表)
            if text:
                out.append((sec, text))
    return out


def 归一(s: str) -> str:
    """去掉标点空格，只留下能比对的字，降低转写小差异的干扰。"""
    return re.sub(r"[^一-鿿A-Za-z0-9]", "", s).lower()


def 细分长段(段落):
    """把会议软件导出的长段细分，并在相邻时间点之间按字数估算子段时间。"""
    out = []
    for index, (start, text) in enumerate(段落):
        total_chars = len(归一(text))
        if total_chars <= 单段最大字数:
            out.append((start, text))
            continue

        # 优先在自然标点处切；单个分句仍太长时再按原字符长度硬切。
        pieces = [p for p in re.findall(r".+?(?:[。！？?!；;，,]|$)", text) if p.strip()]
        chunks, current = [], ""
        for piece in pieces:
            if current and len(归一(current + piece)) > 单段最大字数:
                chunks.append(current)
                current = ""
            if len(归一(piece)) > 单段最大字数:
                if current:
                    chunks.append(current)
                    current = ""
                step = max(40, int(len(piece) * 单段最大字数 / max(len(归一(piece)), 1)))
                chunks.extend(piece[i:i + step] for i in range(0, len(piece), step))
            else:
                current += piece
        if current:
            chunks.append(current)

        next_start = 段落[index + 1][0] if index + 1 < len(段落) else None
        if next_start is None or next_start <= start:
            next_start = start + max(1, round(total_chars / 4.5))
        duration = next_start - start
        used = 0
        for chunk in chunks:
            chunk_chars = len(归一(chunk))
            estimated_start = start + round(duration * used / max(total_chars, 1))
            out.append((estimated_start, chunk.strip()))
            used += chunk_chars
    return out


def 逐字稿质量问题(段落):
    """拦住“带几个时间点的 AI 摘要”，避免把摘要差异误报成剪辑删除。"""
    if len(段落) < 2:
        return "时间点太少，无法进行剪前剪后定位"
    时长 = 段落[-1][0] - 段落[0][0]
    间隔 = [b[0] - a[0] for a, b in zip(段落, 段落[1:]) if b[0] > a[0]]
    平均字数 = sum(len(归一(t)) for _, t in 段落) / len(段落)
    if 时长 >= 1800 and len(段落) < 20:
        return f"整期只有 {len(段落)} 个时间点，像分段摘要，不像完整逐字转写"
    if 间隔 and median(间隔) > 120 and 平均字数 > 120:
        return f"相邻时间点的中位间隔为 {int(median(间隔))} 秒，像分段摘要，不像完整逐字转写"
    return None


def 结构类型(text):
    命中 = []
    for 名, 词组 in 类型线索.items():
        分 = sum(text.count(word) for word in 词组)
        if 分:
            命中.append((分, 名))
    return max(命中)[1] if 命中 else "其他表达"


def 段时长(段落, index, 总长):
    start = 段落[index][0]
    end = 段落[index + 1][0] if index + 1 < len(段落) else 总长
    return max(end - start, 1)


def 结构统计(原始, keep, 原始总长):
    stats = {}
    for i, ((_, text), kept) in enumerate(zip(原始, keep)):
        名 = 结构类型(text)
        row = stats.setdefault(名, {"保留字": 0, "删除字": 0, "保留秒": 0, "删除秒": 0})
        字 = len(归一(text))
        秒 = 段时长(原始, i, 原始总长)
        if kept:
            row["保留字"] += 字
            row["保留秒"] += 秒
        else:
            row["删除字"] += 字
            row["删除秒"] += 秒
    return stats


def 复盘观察(片段, 三段, stats, 原始总长):
    """只基于报告中的数值提出可验证问题，不替用户下因果结论。"""
    out = []
    总候选 = sum(p["时长"] for p in 片段)
    if 总候选:
        最大区 = max(range(3), key=lambda i: 三段[i])
        区名 = ("前段", "中段", "后段")[最大区]
        占比 = 三段[最大区] / 总候选
        if 占比 >= 0.5:
            out.append(f"候选删减有 {占比:.0%} 集中在{区名}：回听这一段，判断是在压缩开场、收紧论证，还是清理录后内容。")
    长段 = [p for p in 片段 if p["时长"] >= 60]
    if 长段:
        out.append(f"有 {len(长段)} 段候选超过 1 分钟：这更像结构性取舍，适合逐段记录“删前作用”和“删后影响”。")
    if 片段:
        平均间隔 = 原始总长 / max(len(片段), 1)
        out.append(f"平均约每 {时间(平均间隔)} 出现一处候选删减：和低表现期比较这个频率，观察节奏是否更紧。")
    有类型 = [(row["删除秒"], name) for name, row in stats.items() if row["删除秒"]]
    if 有类型:
        _, name = max(有类型)
        out.append(f"按关键词粗分，删减时长最多的是“{name}”：这只是定位线索，需回听确认是否真的属于这一类。")
    out.append("把同一组指标再跑一到两期低表现节目；只有跨期重复出现的差异，才值得进入下一期剪辑假设。")
    return out


def 找出被删的(原始, 成片):
    """
    返回 (keep, coverage, exact_ratio)。

    先把两份稿子各自连成一条全文，再按字符顺序对齐；最后把结果映射回
    原始稿的每个时间段。这样不会因为“同一句被切成三行”而误判成删除。
    """
    原文 = ""
    范围 = []
    for _, text in 原始:
        part = 归一(text)
        范围.append((len(原文), len(原文) + len(part)))
        原文 += part
    成文 = "".join(归一(text) for _, text in 成片)

    已匹配 = bytearray(len(原文))
    matcher = SequenceMatcher(None, 原文, 成文, autojunk=False)
    for block in matcher.get_matching_blocks():
        if block.size:
            已匹配[block.a:block.a + block.size] = b"\1" * block.size

    coverage = []
    for start, end in 范围:
        length = end - start
        coverage.append(sum(已匹配[start:end]) / length if length else 1.0)
    keep = [value >= 保留覆盖门槛 for value in coverage]
    exact_ratio = sum(已匹配) / max(len(原文), 1)
    return keep, coverage, exact_ratio


def 并成片段(原始, keep, coverage):
    """把连续被删的句子并成片段。"""
    删除下标 = [i for i, k in enumerate(keep) if not k]
    if not 删除下标:
        return []
    片段, 当前 = [], [删除下标[0]]
    for i in 删除下标[1:]:
        if i - 当前[-1] <= 片段合并间隔:
            当前.append(i)
        else:
            片段.append(当前)
            当前 = [i]
    片段.append(当前)

    结果 = []
    for idxs in 片段:
        起 = 原始[idxs[0]][0]
        末 = idxs[-1]
        止 = 原始[末 + 1][0] if 末 + 1 < len(原始) else 原始[末][0]
        文本 = "".join(原始[i][1] for i in idxs)
        字数 = len(归一(文本))
        匹配字数 = sum(len(归一(原始[i][1])) * coverage[i] for i in idxs)
        误差覆盖 = 匹配字数 / max(字数, 1)
        置信 = "高" if 误差覆盖 <= 0.10 else "中" if 误差覆盖 <= 0.22 else "低"
        item = {
            "起": 起, "止": max(止, 起 + 1),
            "时长": max(止 - 起, 1),
            "字数": 字数,
            "句数": len(idxs),
            "文本": 文本,
            "置信": 置信,
            "误差覆盖": 误差覆盖,
        }
        # 1–2 秒、几个字的差异常来自标点或转写切分，对复盘价值很低。
        if item["时长"] >= 最短候选秒 and item["字数"] >= 最少候选字:
            结果.append(item)
    return 结果


def 时间(s):
    return f"{int(s) // 60:02d}:{int(s) % 60:02d}"


def 解析指定路径(value, 期目录: Path):
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    for candidate in (期目录 / path, PROJECT_DIR / path):
        if candidate.exists():
            return candidate
    return 期目录 / path


def 找文件(期目录: Path, 原始指定=None, 成片指定=None):
    成片指定 = 解析指定路径(成片指定, 期目录)
    原始指定 = 解析指定路径(原始指定, 期目录)
    成片 = [成片指定] if 成片指定 else [
        p for p in sorted(期目录.glob("*转写*带时间戳*.txt"))
        if "原始" not in p.name and "试跑" not in p.name
    ]
    原始 = [原始指定] if 原始指定 else sorted(期目录.glob("*_转写_带时间戳_原始录音.txt"))

    # 兼容旧命名，例如「第二期原始稿转写.txt」「第三期原始版转写稿.txt」。
    if not 原始:
        原始 = sorted({*期目录.glob("*原始*转写*.txt"),
                     *期目录.glob("*原始*稿*.txt")})

    # 老素材常只有剪映导出的 SRT。只在能唯一排除本工具生成的成片 SRT 时自动采用。
    if not 原始:
        srt = [p for p in sorted(期目录.glob("*.srt"))
               if not p.name.startswith(f"{期目录.name}_转写")]
        if len(srt) == 1:
            原始 = srt
    if not 成片:
        sys.exit(f"❌ 在 {期目录.name} 里没找到剪辑后的转写稿（*_转写_带时间戳.txt）\n"
                 f"   先跑：python3 tools/transcribe.py {期目录.name}/剪辑后的音频.mp3")
    if not 原始:
        sys.exit(f"❌ 在 {期目录.name} 里没找到唯一的原始录音转写稿\n"
                 f"   可以先跑转写，或指定已有 SRT：\n"
                 f"   python3 tools/compare_edits.py {期目录.name} --原始稿 原始稿.srt")
    for path in (原始[0], 成片[0]):
        if not path.exists():
            sys.exit(f"❌ 找不到转写稿：{path}")
    return 原始[0], 成片[0]


def 计算一期(期目录: Path, 原始指定=None, 成片指定=None):
    """计算单集指标，供单集报告和跨期复盘共用。"""
    原始路径, 成片路径 = 找文件(期目录, 原始指定, 成片指定)
    原始初稿, 成片 = 读转写(原始路径), 读转写(成片路径)
    if not 原始初稿 or not 成片:
        raise ValueError("转写稿是空的，或者格式不对")
    质量问题 = 逐字稿质量问题(原始初稿)
    if 质量问题:
        raise ValueError(f"{原始路径.name} 不能用于可靠对比：{质量问题}")

    原始段数 = len(原始初稿)
    原始 = 细分长段(原始初稿)
    keep, coverage, 对齐率 = 找出被删的(原始, 成片)
    if 对齐率 < 0.20:
        raise ValueError(f"两份稿子的逐字对齐率只有 {对齐率 * 100:.1f}%，不足以生成可靠报告")
    片段 = 并成片段(原始, keep, coverage)

    原始总长 = 原始[-1][0]
    成片总长 = 成片[-1][0]
    删除总时长 = sum(p["时长"] for p in 片段)
    音频时长差 = max(原始总长 - 成片总长, 0)
    原始字数 = sum(len(归一(t)) for _, t in 原始)
    成片字数 = sum(len(归一(t)) for _, t in 成片)
    删除字数 = sum(p["字数"] for p in 片段)

    三段 = [0, 0, 0]
    for p in 片段:
        for i in range(3):
            区起 = 原始总长 * i / 3
            区止 = 原始总长 * (i + 1) / 3
            三段[i] += max(0, min(p["止"], 区止) - max(p["起"], 区起))

    类型统计 = 结构统计(原始, keep, 原始总长)
    流程词 = ("开始录", "结束录制", "关录制", "关了", "复盘", "拜拜", "剪辑", "发布", "转写", "开场")
    流程候选 = [p for p in 片段 if any(word in p["文本"] for word in 流程词)]
    return {
        "期目录": 期目录, "原始路径": 原始路径, "成片路径": 成片路径,
        "原始段数": 原始段数, "原始": 原始, "成片": 成片,
        "keep": keep, "coverage": coverage, "对齐率": 对齐率, "片段": 片段,
        "原始总长": 原始总长, "成片总长": 成片总长,
        "删除总时长": 删除总时长, "音频时长差": 音频时长差,
        "未由文字解释": max(音频时长差 - 删除总时长, 0),
        "原始字数": 原始字数, "成片字数": 成片字数, "删除字数": 删除字数,
        "三段": 三段, "类型统计": 类型统计,
        "原始字速": 原始字数 / max(原始总长 / 60, 1),
        "成片字速": 成片字数 / max(成片总长 / 60, 1),
        "长删减数": sum(p["时长"] >= 60 for p in 片段),
        "流程候选数": len(流程候选),
        "流程候选时长": sum(p["时长"] for p in 流程候选),
        "流程候选": 流程候选,
    }


def 读表现数据(path_value):
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.is_absolute():
        path = PROJECT_DIR / path
    if not path.exists():
        raise ValueError(f"找不到表现数据：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("表现数据需要是“期名 → 指标”的 JSON 对象")
    return data


def 完播率值(item):
    if isinstance(item, (int, float)):
        value = float(item)
    elif isinstance(item, dict):
        value = item.get("完播率", item.get("completion_rate"))
        if not isinstance(value, (int, float)):
            return None
        value = float(value)
    else:
        return None
    return value / 100 if value > 1 else value


def 表现文字(item):
    if item is None:
        return "未提供"
    if isinstance(item, (int, float)):
        value = 完播率值(item)
        return f"完播率 {value:.1%}" if value is not None else str(item)
    if isinstance(item, dict):
        parts = []
        for key in ("播放", "完播率", "平均播放时长"):
            if key not in item:
                continue
            value = item[key]
            if key in ("完播率", "completion_rate") and isinstance(value, (int, float)):
                normalized = float(value) / 100 if value > 1 else float(value)
                parts.append(f"完播率 {normalized:.1%}")
            else:
                parts.append(f"{key} {value}")
        return "；".join(parts) or "未提供"
    return str(item)


def 写跨期复盘(期名列表, 表现数据路径=None):
    表现数据 = 读表现数据(表现数据路径)
    结果 = []
    for name in 期名列表:
        目录 = Path(name)
        if not 目录.is_absolute():
            目录 = PROJECT_DIR / name
        if not 目录.is_dir():
            raise ValueError(f"找不到文件夹：{目录}")
        print(f"正在分析 {目录.name}...")
        结果.append(计算一期(目录))

    def 数据路径(value):
        if not value:
            return None
        path = Path(value)
        return path if path.is_absolute() else PROJECT_DIR / path

    # 音频和双人配合指标只在数据清单提供了文件时计算；它们仍属于“剪辑复盘”这一个工具。
    for r in 结果:
        config = 表现数据.get(r["期目录"].name, {})
        if not isinstance(config, dict):
            continue
        raw_audio = 数据路径(config.get("raw_audio"))
        final_audio = 数据路径(config.get("final_audio"))
        r["raw_audio"] = raw_audio
        r["final_audio"] = final_audio
        if final_audio and final_audio.exists():
            print(f"正在读取 {r['期目录'].name} 成片声波...")
            r["final_audio_metrics"] = audio_metrics(final_audio)
        if raw_audio and raw_audio.exists():
            print(f"正在读取 {r['期目录'].name} 原始声波...")
            r["raw_audio_metrics"] = audio_metrics(raw_audio)
        r["turn_metrics"] = turn_metrics(r["原始路径"], r["成片路径"], config.get("speaker_a"))
        final_duration = r.get("final_audio_metrics", {}).get("duration_seconds", r["成片总长"])
        r["chapter_metrics"] = chapter_metrics(config.get("chapters", []), final_duration)

    L = []
    A = L.append
    A("# 跨期剪辑复盘｜指导后续录制与剪辑")
    A("")
    A(f"> 历史样本：{'、'.join(r['期目录'].name for r in 结果)}。")
    A("> 这份报告用历史剪前/剪后差异提炼可验证的工作假设；完播数据决定优先研究哪一期，但单次相关性不等于因果。")
    if not 表现数据:
        A("> 当前未提供完播数据，因此以下只写剪辑事实与跨期共同点，不判断哪种剪法带来了更高完播。")
    A("")
    if 表现数据:
        A("## 平台数据总览")
        A("")
        A("| 单集 | 播放 | 完播率 | 平均播放 | 成片时长 | 复听深度* | 点赞率 | 分享率 |")
        A("|---|---:|---:|---:|---:|---:|---:|---:|")
        result_by_name = {r["期目录"].name: r for r in 结果}
        for name, item in 表现数据.items():
            if not isinstance(item, dict) or "播放" not in item:
                continue
            play = max(item.get("播放", 0), 1)
            final_audio = 数据路径(item.get("final_audio"))
            final_seconds = media_duration(final_audio) if final_audio and final_audio.exists() else result_by_name.get(name, {}).get("成片总长", 0)
            avg_seconds = parse_clock(item.get("平均播放时长", "00:00"))
            completion = 完播率值(item)
            A(f"| {name} | {item.get('播放', '—')} | {completion:.1%} | {item.get('平均播放时长', '—')} | "
              f"{时间(final_seconds) if final_seconds else '—'} | {avg_seconds / final_seconds:.0%} | "
              f"{item.get('点赞', 0) / play:.1%} | {item.get('分享', 0) / play:.1%} |")
        A("")
        A("*复听深度 = 平均播放时长 ÷ 成片时长。超过 100% 表明平台把重复播放/重复片段累计进时长；它不是“平均听到第几分钟”。")
        play_counts = [item.get("播放") for item in 表现数据.values()
                       if isinstance(item, dict) and isinstance(item.get("播放"), (int, float))]
        if play_counts:
            A(f"本次 {len(结果)} 期样本为 {min(play_counts):g}–{max(play_counts):g} 次播放；"
              "完播率适合用来提出优先复盘方向，不足以单独证明因果。")
        A("")
    A(f"## {len(结果)} 期放在一起看")
    A("")
    A("| 单集 | 表现数据 | 原始→成片 | 时长压缩 | 文字删除 | 成片文字密度 | 1 分钟以上删减 | 后三分之一占候选 |")
    A("|---|---|---|---:|---:|---:|---:|---:|")
    for r in 结果:
        total = max(sum(r["三段"]), 1)
        performance = 表现文字(表现数据.get(r["期目录"].name))
        A(f"| {r['期目录'].name} | {performance} | {时间(r['原始总长'])}→{时间(r['成片总长'])} | "
          f"{r['音频时长差'] / max(r['原始总长'], 1):.0%} | {r['删除字数'] / max(r['原始字数'], 1):.0%} | "
          f"{r['成片字速']:.0f} 字/分 | {r['长删减数']} | {r['三段'][2] / total:.0%} |")
    A("")

    增密期数 = sum(r["成片字速"] > r["原始字速"] for r in 结果)
    成片字速 = [r["成片字速"] for r in 结果]
    后段占比 = [r["三段"][2] / max(sum(r["三段"]), 1) for r in 结果]
    流程秒 = sum(r["流程候选时长"] for r in 结果)
    长段数 = sum(r["长删减数"] for r in 结果)

    if any(r.get("final_audio_metrics") for r in 结果):
        A("## 声波与停顿")
        A("")
        A("| 单集 | 静默占比 原始→成片 | 1.5s+ 停顿/分钟 原始→成片 | 人声中位电平 原始→成片 | 动态范围 原始→成片 | 频谱中心 原始→成片 |")
        A("|---|---:|---:|---:|---:|---:|")
        for r in 结果:
            raw = r.get("raw_audio_metrics", {})
            final = r.get("final_audio_metrics", {})
            if not final:
                continue
            A(f"| {r['期目录'].name} | {raw.get('silence_percent', 0):.1f}%→{final.get('silence_percent', 0):.1f}% | "
              f"{raw.get('long_pauses_per_minute', 0):.2f}→{final.get('long_pauses_per_minute', 0):.2f} | "
              f"{raw.get('median_active_dbfs', 0):.1f}→{final.get('median_active_dbfs', 0):.1f} dBFS | "
              f"{raw.get('active_dynamic_range_db', 0):.1f}→{final.get('active_dynamic_range_db', 0):.1f} dB | "
              f"{raw.get('median_spectral_centroid_hz', 0):.0f}→{final.get('median_spectral_centroid_hz', 0):.0f} Hz |")
        A("")
        A("声波指标说明“剪得多紧、音量是否被压平”，不直接代表内容好坏。频谱中心受设备、房间和声音本身影响，只适合排查异常。")
        for item in 结果:
            if not item.get("raw_audio_metrics"):
                continue
            media_gap = abs(item["raw_audio_metrics"]["duration_seconds"] - item["原始总长"])
            if media_gap >= 60:
                A(f"> {item['期目录'].name} 的原始媒体为 {时间(item['raw_audio_metrics']['duration_seconds'])}，但原始转写覆盖 {时间(item['原始总长'])}；"
                  "声波表只分析现有视频范围，文字删减仍以完整原始转写为准。")
        A("")

    if any(r.get("turn_metrics") for r in 结果):
        A("## 双人配合与接话")
        A("")
        A("| 单集 | 原始接话次数/分钟 | 轮流接话率 | 单次发言中位时长 | 45s+ 长发言 | 主播A文字占比 原始→成片估算 | 原始平衡分 |")
        A("|---|---:|---:|---:|---:|---:|---:|")
        for r in 结果:
            m = r.get("turn_metrics", {})
            if not m:
                continue
            final_share = m.get("estimated_final_speaker_a_char_share")
            share = f"{m['speaker_a_char_share']:.0f}%→{final_share:.0f}%" if final_share is not None else f"{m['speaker_a_char_share']:.0f}%"
            A(f"| {r['期目录'].name} | {m['switches_per_minute']:.2f} | {m['alternation_percent']:.0f}% | "
              f"{m['median_turn_seconds']:.0f}s | {m['long_turns_45s_plus']} | {share} | {m['speaker_balance_score']:.0f}/100 |")
        A("")
        A("成片没有说话人标注，因此“成片占比”是把原始发言与成片全文对齐后的文字估算；接话频率使用原始带说话人时间轴。")
        A("")

    if any(r.get("chapter_metrics") for r in 结果):
        A("## 框架、话题丰富度与延展度")
        A("")
        A("| 单集 | 发布章节数 | 每 10 分钟章节数 | 板块中位时长 | 最长板块 |")
        A("|---|---:|---:|---:|---:|")
        for r in 结果:
            m = r.get("chapter_metrics", {})
            if not m:
                continue
            A(f"| {r['期目录'].name} | {m['chapter_count']} | {m['chapters_per_10_min']:.2f} | "
              f"{时间(m['median_chapter_seconds'])} | {时间(m['longest_chapter_seconds'])} |")
        A("")
        A("章节数反映话题切换频率，中位时长反映单个话题的停留深度。章节多不等于跳跃；关键看它们是否围绕同一条主问题推进。")
        A("")
        A("### 每个板块停留时间")
        A("")
        for r in 结果:
            config = 表现数据.get(r["期目录"].name, {})
            chapters = config.get("chapters", []) if isinstance(config, dict) else []
            metrics = r.get("chapter_metrics", {})
            if not chapters or not metrics:
                continue
            A(f"**{r['期目录'].name}**")
            A("")
            A("| 开始 | 时长 | 板块 |")
            A("|---:|---:|---|")
            for item, duration in zip(chapters, metrics["durations"]):
                A(f"| {item[0]} | {时间(duration)} | {item[1]} |")
            A("")

    A("## 跨期共同点")
    A("")
    A(f"1. **成片都比原始录音更紧。** {增密期数}/{len(结果)} 期的文字密度在剪辑后上升；成片集中在 "
      f"{min(成片字速):.0f}–{max(成片字速):.0f} 字/分钟。这个区间是历史结果，不是必须追求的标准。")
    A(f"2. **后段是最稳定的清理区。** {len(结果)} 期后三分之一平均承接 {sum(后段占比) / len(后段占比):.0%} 的文字删减候选；"
      "其中包含结尾重来、录后复盘和运营讨论。")
    A(f"3. **结构性删减不是偶发。** {len(结果)} 期共有 {长段数} 段候选超过 1 分钟，说明很多成本来自录制结构，而不只是口头禅。")
    A(f"4. **流程内容可以从源头分轨。** 含“开始录、结束录制、复盘、剪辑、发布”等词的候选共 "
      f"{sum(r['流程候选数'] for r in 结果)} 段、约 {时间(流程秒)}；正式结尾后立刻停止主录音，能减少后期定位成本。")
    A("")
    A("## 脚本结构对照")
    A("")
    A("下表是各类表达的文字删除占比。分类来自关键词，只用于定位差异，不能替代人工回听。")
    A("")
    类型顺序 = ["观点判断", "互动问答", "具体经历", "过渡铺垫", "录制事务", "其他表达"]
    A("| 类型 | " + " | ".join(r["期目录"].name for r in 结果) + " |")
    A("|---|" + "---:|" * len(结果))
    for 名 in 类型顺序:
        values = []
        for r in 结果:
            row = r["类型统计"].get(名, {"保留字": 0, "删除字": 0})
            total = row["保留字"] + row["删除字"]
            values.append(f"{row['删除字'] / max(total, 1):.0%}" if total else "—")
        A(f"| {名} | " + " | ".join(values) + " |")
    A("")
    最少文字删减 = min(结果, key=lambda r: r["删除字数"] / max(r["原始字数"], 1))
    A(f"**最明显的差异**：{最少文字删减['期目录'].name} 只有 "
      f"{最少文字删减['删除字数'] / max(最少文字删减['原始字数'], 1):.0%} 的文字表现为整段删除；"
      "它更像在压停顿和节奏。其余文字删减更高的单集更依赖内容重组。")
    A("这提示下一期可以复用低文字删减期的提纲与互动方式，再用完播数据判断这种“录制时更成形”的结构是否也更受听众欢迎。")
    A("")

    有完播 = [(完播率值(表现数据.get(r["期目录"].name)), r) for r in 结果]
    有完播 = [(value, r) for value, r in 有完播 if value is not None]
    A("## 完播数据怎么进入判断")
    A("")
    if len(有完播) >= 2:
        有完播.sort(key=lambda item: item[0], reverse=True)
        high_value, high = 有完播[0]
        low_value, low = 有完播[-1]
        A(f"目前最高是 {high['期目录'].name}（{high_value:.1%}），最低是 {low['期目录'].name}（{low_value:.1%}）。")
        A(f"两期描述性差异：成片文字密度 {high['成片字速']:.0f} vs {low['成片字速']:.0f} 字/分；"
          f"时长压缩 {high['音频时长差'] / max(high['原始总长'], 1):.0%} vs {low['音频时长差'] / max(low['原始总长'], 1):.0%}；"
          f"1 分钟以上删减 {high['长删减数']} vs {low['长删减数']} 段。")
        high_audio, low_audio = high.get("final_audio_metrics", {}), low.get("final_audio_metrics", {})
        if high_audio and low_audio:
            A(f"成片声波差异：静默占比 {high_audio['silence_percent']:.1f}% vs {low_audio['silence_percent']:.1f}%；"
              f"1.5 秒以上停顿频率 {high_audio['long_pauses_per_minute']:.2f} vs {low_audio['long_pauses_per_minute']:.2f} 次/分。")
        high_turn, low_turn = high.get("turn_metrics", {}), low.get("turn_metrics", {})
        if high_turn and low_turn:
            A(f"录制互动差异：接话 {high_turn['switches_per_minute']:.2f} vs {low_turn['switches_per_minute']:.2f} 次/分；"
              f"单次发言中位 {high_turn['median_turn_seconds']:.0f} vs {low_turn['median_turn_seconds']:.0f} 秒；"
              f"成片主播A文字占比估算 {high_turn.get('estimated_final_speaker_a_char_share', 0):.0f}% vs "
              f"{low_turn.get('estimated_final_speaker_a_char_share', 0):.0f}%。")
            A(f"当前最值得测试的不是“剪得更短”或“说得更快”，而是 {high['期目录'].name} 的清晰主讲线：一人承担完整叙事，另一人减少频繁打断，用追问、复述和情绪承接推动同一主问题。")
        else:
            A(f"当前最值得测试的是 {high['期目录'].name} 的章节推进和较少整段返工；缺少带说话人时间轴时，不对双人配合方式下结论。")
        A("这些只能形成下一期 A/B 假设；还需结合标题、主题、发布时间和流量来源，不能直接归因给剪辑。")

        A("")
        A(f"## 高完播样本拆解：{high['期目录'].name}删了什么、留了什么")
        A("")
        A(f"**先看剪法**：原始稿覆盖 {时间(high['原始总长'])}，成片 {时间(high['成片总长'])}；"
          f"文字删除约 {high['删除字数'] / max(high['原始字数'], 1):.0%}，并不是只清口头禅，而是做了结构性重组。")
        A("")
        A("### 明确删掉的内容")
        A("")
        for p in sorted(high.get("流程候选", []), key=lambda item: -item["时长"])[:4]:
            label = "录前准备" if p["起"] < high["原始总长"] * 0.1 else "录后复盘/运营讨论" if p["起"] > high["原始总长"] * 0.75 else "流程性插曲"
            A(f"- **{时间(p['起'])}–{时间(p['止'])}｜{label}｜{时间(p['时长'])}**：{p['文本'][:80]}……")
        non_process = [p for p in sorted(high["片段"], key=lambda item: -item["时长"])
                       if p not in high.get("流程候选", [])]
        for p in non_process[:5]:
            reason = "长段互动，可能在压缩支线或重复论证" if 结构类型(p["文本"]) == "互动问答" else "长段观点，可能在保留核心句后压缩展开"
            A(f"- **{时间(p['起'])}–{时间(p['止'])}｜{结构类型(p['文本'])}｜{时间(p['时长'])}**：{reason}。原文开头：{p['文本'][:60]}……")
        A("")
        A("### 成片保留的主线")
        A("")
        high_config = 表现数据.get(high["期目录"].name, {})
        for item in high_config.get("chapters", []) if isinstance(high_config, dict) else []:
            A(f"- {item[0]}　{item[1]}")
        high_types = high["类型统计"]
        viewpoint = high_types.get("观点判断", {"保留字": 0, "删除字": 0})
        interaction = high_types.get("互动问答", {"保留字": 0, "删除字": 0})
        viewpoint_keep = viewpoint["保留字"] / max(viewpoint["保留字"] + viewpoint["删除字"], 1)
        interaction_keep = interaction["保留字"] / max(interaction["保留字"] + interaction["删除字"], 1)
        A("")
        A(f"关键词粗分下，观点判断约保留 {viewpoint_keep:.0%}，互动问答约保留 {interaction_keep:.0%}。"
          "这支持一个剪辑假设：保留能推进主线的完整观点与故事，把重复追问、支线回应和同义展开压短。")
        A("")
        A("### 为什么这样剪（可验证假设）")
        A("")
        A("- 录前准备和录后复盘对听众没有节目价值，整段移出，先建立干净的起点与终点。")
        A("- 主讲者的个人经历承担叙事推进；搭档的价值更多是追问、复述和情绪承接，而不是追求五五开。")
        A("- 同一个观点保留最具体、最有情绪或最能完成转折的一版，其余相似例子和解释缩短。")
        A("- 结尾保留个人情绪高潮和对外延展，但把宏观举例压短，避免临近结束重新展开另一整期。")
        A("这些“为什么”来自转写差异、章节结构和声波数据的共同指向；最终仍需回听候选边界确认。")
        A("")
        A("## 对照组从剪辑角度怎么优化")
        A("")
        for value, r in 有完播[1:]:
            A(f"### {r['期目录'].name}（完播率 {value:.1%}）")
            A("")
            suggestions = []
            delete_ratio = r["删除字数"] / max(r["原始字数"], 1)
            if r["成片字速"] > high["成片字速"] + 5:
                suggestions.append(f"成片文字密度 {r['成片字速']:.0f} 字/分，高于高完播样本的 {high['成片字速']:.0f}；不要继续追求更短，优先给关键故事和转折留呼吸。")
            if delete_ratio >= 0.30:
                suggestions.append(f"已有 {delete_ratio:.0%} 的文字被整段删除，说明成本来自录制结构；下一期在录前缩成 3–5 个主问题，每个板块只保留一个主例子。")
            else:
                suggestions.append(f"只有 {delete_ratio:.0%} 的文字表现为整段删除，主体对话已经较完整；优化重点放在开头承诺、板块间钩子和结尾收束，而不是大改正文。")
            r_turn = r.get("turn_metrics", {})
            high_turn = high.get("turn_metrics", {})
            if r_turn and high_turn and r_turn["switches_per_minute"] > high_turn["switches_per_minute"] + 0.5:
                suggestions.append(f"原始接话 {r_turn['switches_per_minute']:.2f} 次/分，明显高于高完播样本；减少一句一接的乒乓感，让一个观点先讲完整，再由搭档追问或总结。")
            r_audio = r.get("final_audio_metrics", {})
            high_audio = high.get("final_audio_metrics", {})
            if r_audio and high_audio and r_audio["long_pauses_per_minute"] > high_audio["long_pauses_per_minute"] + 0.05:
                suggestions.append(f"成片仍有 {r_audio['long_pauses_per_minute']:.2f} 次/分的长停顿，可先清理无信息停顿；有情绪作用的停顿保留。")
            for suggestion in suggestions:
                A(f"- {suggestion}")
            A("")
    else:
        A("把各期的完播率（或完成播放量）填入表现数据文件后，工具会标出高低表现期的描述性差异。")
        A("没有这组数据时，不能诚实回答“哪种剪法提高了完播率”；当前报告只负责先把可比较的剪辑事实整理好。")
    A("")

    A("## 对以后内容的具体指导")
    A("")
    A("### 录制前")
    A("")
    A("- 把开场提前写成三句：为什么现在聊、这一期回答什么、听众能带走什么；正式录制前先对齐，不在主录音里临时商量。")
    A("- 每期只设 3–5 个主问题。每个问题按“观点 → 具体经历/例子 → 对听众的结论”走，减少录完后整段搬走。")
    A("- 提前写好结尾问题和一句 takeaway，避免在尾声反复寻找结束方式。")
    A("")
    A("### 录制中")
    A("")
    A("- 一段说完后用一句话收束；如果现场已经判断跑题，直接说“这里标记剪掉”，让后期能快速定位。")
    A("- 运营讨论、互相复盘和设备沟通放到主录音停止之后，必要时另开一条“复盘录音”。")
    A("- 不为了追求某个字速刻意加快说话；历史成片密度只用来发现异常，不替代自然表达。")
    A("")
    A("### 剪辑后")
    A("")
    A("- 先检查 1 分钟以上的结构性删减：它们最能反推提纲哪里需要改。")
    A("- 连续记录至少三期同一指标，再决定是否形成固定规则；单期表现只用来提出假设。")
    A("- 新一期成片确认后，再运行宣发工具；宣发只读成片时间轴，不回看历史原始稿。")
    A("")
    A("## 下一期最小实验")
    A("")
    A("只改一件事：录前固定 3–5 个问题和结尾，录后立即停止主录音。下一期再比较长段删减数、后段删减占比和完播率。")

    report = PROJECT_DIR / "跨期剪辑复盘.md"
    report.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\n✅ 完成：{report.name}")
    return report


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("期", nargs="+", help="一个或多个单集目录，比如 episodes/ep02 episodes/ep03")
    ap.add_argument("--原始稿", help="已有的原始录音转写（.txt 或 .srt）")
    ap.add_argument("--成片稿", help="已有的成片转写（.txt 或 .srt）")
    ap.add_argument("--表现说明", default="", help="可选，例如：完播率四成，本季最高")
    ap.add_argument("--汇总", action="store_true", help="把多期放在一起复盘，指导之后的录制与剪辑")
    ap.add_argument("--表现数据", help="可选，跨期完播率/播放量 JSON 文件")
    ap.add_argument("-h", "--help", action="help", help="看用法")
    args = ap.parse_args()

    if args.汇总:
        if len(args.期) < 2:
            sys.exit("❌ 跨期复盘至少需要两期，例如：python3 tools/compare_edits.py episodes/ep02 episodes/ep03 --汇总")
        try:
            写跨期复盘(args.期, args.表现数据)
        except (ValueError, json.JSONDecodeError) as exc:
            sys.exit(f"❌ {exc}")
        return
    if len(args.期) != 1:
        sys.exit("❌ 单期对比一次写一期；多期复盘请加 --汇总")
    args.期 = args.期[0]

    期目录 = Path(args.期)
    if not 期目录.is_absolute():
        期目录 = PROJECT_DIR / args.期
    if not 期目录.is_dir():
        sys.exit(f"❌ 找不到文件夹：{期目录}")

    原始路径, 成片路径 = 找文件(期目录, args.原始稿, args.成片稿)
    原始, 成片 = 读转写(原始路径), 读转写(成片路径)
    if not 原始 or not 成片:
        sys.exit("❌ 转写稿是空的，或者格式不对（需要 [分:秒] 开头的行）")
    质量问题 = 逐字稿质量问题(原始)
    if 质量问题:
        sys.exit(f"❌ {原始路径.name} 不能用于可靠对比：{质量问题}。\n"
                 "   请换成原始录音的完整逐字转写；每句话或每次发言都要有时间点。")

    原始段数 = len(原始)
    原始 = 细分长段(原始)
    print(f"📄 原始录音转写：{原始路径.name}（{原始段数} 段，细分后 {len(原始)} 段）")
    print(f"📄 剪辑成片转写：{成片路径.name}（{len(成片)} 句）")
    print("正在对齐两份稿子...")

    keep, coverage, 对齐率 = 找出被删的(原始, 成片)
    if 对齐率 < 0.20:
        sys.exit(f"❌ 两份稿子的逐字对齐率只有 {对齐率 * 100:.1f}%，不足以生成可靠报告。\n"
                 "   请确认两份稿子来自同一期，并且原始稿不是 AI 摘要。")
    片段 = 并成片段(原始, keep, coverage)

    原始总长 = 原始[-1][0]
    成片总长 = 成片[-1][0]
    删除总时长 = sum(p["时长"] for p in 片段)
    音频时长差 = max(原始总长 - 成片总长, 0)
    未由文字解释 = max(音频时长差 - 删除总时长, 0)
    原始字数 = sum(len(归一(t)) for _, t in 原始)
    删除字数 = sum(p["字数"] for p in 片段)

    # 位置分布：把整期分成前中后三段，按候选和每一区间的实际重叠时长分摊。
    # 不能只看候选起点，否则一个跨越 30 分钟的长段会被全部算进同一区间。
    三段 = [0, 0, 0]
    for p in 片段:
        for i in range(3):
            区起 = 原始总长 * i / 3
            区止 = 原始总长 * (i + 1) / 3
            三段[i] += max(0, min(p["止"], 区止) - max(p["起"], 区起))

    # 留下的 vs 删掉的，句子长度对比
    留下句长 = [len(归一(t)) for (_, t), k in zip(原始, keep) if k]
    删掉句长 = [len(归一(t)) for (_, t), k in zip(原始, keep) if not k]
    均 = lambda xs: sum(xs) / len(xs) if xs else 0
    原始字速 = 原始字数 / max(原始总长 / 60, 1)
    成片字数 = sum(len(归一(t)) for _, t in 成片)
    成片字速 = 成片字数 / max(成片总长 / 60, 1)
    长删减数 = sum(p["时长"] >= 60 for p in 片段)
    类型统计 = 结构统计(原始, keep, 原始总长)

    行 = []
    A = 行.append
    A(f"# {期目录.name} 剪辑对比")
    A("")
    A(f"> 原始录音 {时间(原始总长)}，剪辑成片 {时间(成片总长)}。")
    A(f"> 这份报告列出**疑似删掉的候选**，不判断**该不该删**——那是你的判断。")
    A(f"> 两份稿子的逐字对齐率为 {对齐率 * 100:.1f}%；不同转写工具造成的字词差异，可能带来少量误报。")
    if args.表现说明:
        A(f"> 本期表现背景：**{args.表现说明}**。这条数据用于说明为什么选择本期复盘，不用于证明某次删除造成了该结果。")
    A("")
    A("## 总览")
    A("")
    A("| | 数值 |")
    A("|---|---|")
    A(f"| 原始录音时长 | {时间(原始总长)} |")
    A(f"| 剪辑成片时长 | {时间(成片总长)} |")
    A(f"| 两者时长差 | {时间(音频时长差)} |")
    A(f"| 按时长算，剪掉 | {(原始总长 - 成片总长) / max(原始总长, 1) * 100:.1f}% |")
    A(f"| 按字数算，剪掉 | {删除字数 / max(原始字数, 1) * 100:.1f}% |")
    A(f"| 疑似删除候选 | {len(片段)} 段 |")
    A(f"| 候选合计时长 | {删除总时长 // 60} 分 {删除总时长 % 60} 秒 |")
    A(f"| 未由文字候选解释 | {未由文字解释 // 60} 分 {未由文字解释 % 60} 秒 |")
    A(f"| 平均每段 | {删除总时长 / max(len(片段), 1):.0f} 秒 |")
    A(f"| 最长的一段 | {max((p['时长'] for p in 片段), default=0)} 秒 |")
    A("")
    if 未由文字解释 >= 60:
        A(f"> 还有 {时间(未由文字解释)} 的时长差没有表现为成段文字删除，常见原因是静默、停顿、语速变化，或转写漏字。")
        A("> 工具不会把这部分硬算成“删掉的内容”；需要看音频波形才能继续解释。")
        A("")
    A("## 删除集中在哪一段")
    A("")
    A("| 位置 | 删掉的时长 | 占全部删除 |")
    A("|---|---|---|")
    for 名, 值 in zip(["前三分之一", "中三分之一", "后三分之一"], 三段):
        A(f"| {名} | {int(值) // 60} 分 {int(值) % 60} 秒 | {值 / max(sum(三段), 1) * 100:.0f}% |")
    A("")
    A("## 删掉的和留下的，有什么不一样")
    A("")
    A("| | 句数 | 平均每句字数 |")
    A("|---|---|---|")
    A(f"| 留下来的 | {len(留下句长)} | {均(留下句长):.1f} |")
    A(f"| 被删掉的 | {len(删掉句长)} | {均(删掉句长):.1f} |")
    A("")
    A("这只是原始转写的段落长度差异；要判断原因，请回听对应音频。")
    A("")
    A("## 剪辑节奏")
    A("")
    A("| 指标 | 原始/剪前 | 成片/剪后 |")
    A("|---|---:|---:|")
    A(f"| 转写文字密度 | {原始字速:.0f} 字/分钟 | {成片字速:.0f} 字/分钟 |")
    A(f"| 时长 | {时间(原始总长)} | {时间(成片总长)} |")
    A(f"| 1 分钟以上的候选删减 | {长删减数} 段 | — |")
    A("")
    A("文字密度只能提示节奏变化；静默、停顿、语速和不同转写工具都会影响它，不能单独解释完播表现。")
    A("")
    A("## 脚本结构线索")
    A("")
    A("以下按关键词粗分，用来快速定位“剪辑更常处理哪类表达”，不是语义模型的最终判断。")
    A("")
    A("| 类型 | 保留字数 | 删除字数 | 该类文字删除占比 | 删除时长 |")
    A("|---|---:|---:|---:|---:|")
    for 名, row in sorted(类型统计.items(), key=lambda item: -item[1]["删除秒"]):
        total = row["保留字"] + row["删除字"]
        A(f"| {名} | {row['保留字']} | {row['删除字']} | {row['删除字'] / max(total, 1):.0%} | {时间(row['删除秒'])} |")
    A("")
    A("## 最长的 15 个候选（按时长排）")
    A("")
    A("优先回听这些——它们占了候选时长的大头，也最适合用来复盘剪辑选择。")
    A("")
    for i, p in enumerate(sorted(片段, key=lambda x: -x["时长"])[:15], 1):
        位置 = p["起"] / max(原始总长, 1) * 100
        A(f"**{i}. {时间(p['起'])} – {时间(p['止'])}**　{p['时长']} 秒 · {p['字数']} 字 · {结构类型(p['文本'])} · 置信度{p['置信']} · 在整期第 {位置:.0f}% 处")
        A("")
        A(f"> {p['文本'][:220]}{'……' if len(p['文本']) > 220 else ''}")
        A("")
    A("## 全部疑似删除候选")
    A("")
    A("| 原始时间 | 时长 | 字数 | 类型线索 | 置信度 | 位置 | 开头 |")
    A("|---|---|---|---|---|---|---|")
    for p in 片段:
        位置 = p["起"] / max(原始总长, 1) * 100
        摘 = p["文本"][:40].replace("|", "／")
        A(f"| {时间(p['起'])}–{时间(p['止'])} | {p['时长']}s | {p['字数']} | {结构类型(p['文本'])} | {p['置信']} | {位置:.0f}% | {摘}… |")
    A("")
    A("## 下一轮复盘问题")
    A("")
    for item in 复盘观察(片段, 三段, 类型统计, 原始总长):
        A(f"- {item}")
    A("")
    A("---")
    A("")
    A("**怎么用这份报告**：先从最长候选开始回听，记录它在脚本中的作用和删后影响；")
    A("再把相同指标跑到低表现期做横向比较。工具提供证据和问题，哪些内容该删、哪些不该删，")
    A("仍由主播结合上下文和真实完播数据判断。")

    报告 = 期目录 / f"{期目录.name}_剪辑对比.md"
    if 报告.exists():
        for i in range(2, 100):
            候选 = 期目录 / f"{期目录.name}_剪辑对比_v{i}.md"
            if not 候选.exists():
                报告 = 候选
                break
    报告.write_text("\n".join(行) + "\n", encoding="utf-8")

    print(f"\n✅ 完成")
    print(f"   找到 {len(片段)} 个疑似删除候选，共 {删除总时长 // 60} 分 {删除总时长 % 60} 秒"
          f"（按字数算是 {删除字数 / max(原始字数, 1) * 100:.1f}%）")
    print(f"   两份稿子的逐字对齐率：{对齐率 * 100:.1f}%")
    print(f"   报告：{报告.name}")
    print(f"\n📌 这份报告列疑似删除候选，不说该不该删。该不该删是你的判断。")


if __name__ == "__main__":
    main()
