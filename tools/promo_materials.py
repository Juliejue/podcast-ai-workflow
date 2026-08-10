#!/usr/bin/env python3
"""
播客工作流｜宣发物料

从剪辑后的转写稿，生成两份可以直接用的素材：
  1. Show Notes 素材   → 发布用（简介初稿 + 章节时间点与标题）
  2. 切片候选          → 短视频用（时间段 + 每条宣传文案初稿）

用法：
  python3 tools/promo_materials.py episodes/ep04

两个 .md 文件已经包含可修改的初稿，也附带进一步润色用的现成指令。
不需要 API；需要更自然的语气时，再把整份粘贴到任意 AI 即可。

为什么时间点是准的：
  这里所有时间点都来自**剪辑后的成片**转写稿，不是原始录音。
  所以不会出现「写了个时间点结果对不上」或者「把剪掉的内容写进文案」这两种老问题。

说明：工具给出可修改的初稿和候选，不替主播做最终编辑判断。
     哪条留、哪条删、按什么顺序排，仍由主播决定。
"""

import argparse
import re
import sys
from pathlib import Path

from transcribe import apply_glossary, load_config, load_glossary

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TOOLS_DIR.parent

目标章节数 = 7
章节最短秒 = 150
切片长度 = (40, 95)      # 小红书切片的合理时长范围（秒）
切片候选数 = 12
切片最小间隔 = 20        # 两条候选之间至少留一点距离，避免选成连续切块

# 观点句常见的开头，用来给候选片段打分。不判断内容好坏，只标记「这里像是在下判断」。
观点词 = ["我觉得", "我发现", "我一直", "其实", "但是", "可是", "所以", "最怕",
          "最难", "真正", "关键是", "问题在于", "我以为", "后来才", "反而",
          "说白了", "本质上", "对我来说", "我承认", "我不想"]
具体词 = ["比如", "举个例子", "那天", "当时", "有一次", "我记得"]
完整句尾 = ("。", "！", "？", "!", "?")
好开头 = ("我觉得", "我发现", "其实", "但是", "后来", "有一次", "我记得",
          "对我来说", "那天", "当时", "最难", "真正", "关键是", "问题在于")
弱开头 = ("啊", "嗯", "哦", "那个", "这个", "去", "和", "以及", "一些")
拖尾词 = ("比如说", "就是", "因为", "但是", "然后", "所以", "的话", "一个")

普通词表, 正则词表 = load_glossary()


def 读转写(path: Path):
    out, hits = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\[(\d+):(\d+)\]\s*(.*)", line.strip())
        if m and m.group(3).strip():
            text, corrected = apply_glossary(m.group(3).strip(), 普通词表, 正则词表)
            hits.extend(corrected)
            out.append((int(m.group(1)) * 60 + int(m.group(2)), text))
    return out, hits


def 时间(s):
    return f"{int(s) // 60:02d}:{int(s) % 60:02d}"


def 断句(text):
    return [s.strip() for s in re.findall(r".+?(?:[。！？?!]|$)", text) if s.strip()]


def 标题初稿(text, max_len=20):
    """从原话里抽一条能独立成立的短句；不补写逐字稿里没有的事实。"""
    choices = []
    for sentence in re.findall(r".+?(?:[，,。！？?!；;]|$)", text):
        clean = sentence.strip(" ，,。！？?!：:；;")
        if len(clean) < 6:
            continue
        if any(word in clean for word in ("大家好", "这里是《", "我的搭档")):
            continue
        score = 0
        score += 3 if any(word in clean for word in 观点词) else 0
        score += 2 if sentence.endswith(("？", "?")) else 0
        score += 1 if any(word in clean for word in 具体词) else 0
        score += 4 if 8 <= len(clean) <= max_len + 4 else 1 if len(clean) <= 36 else 0
        score -= 3 if clean.startswith(弱开头) else 0
        score -= max(len(clean) - 36, 0) / 18
        choices.append((score, clean))
    source = max(choices, default=(0, text.strip()), key=lambda item: item[0])[1]
    if len(source) <= max_len:
        return source
    return source[:max_len - 1].rstrip("，,。！？?!：:；;") + "…"


def 金句初稿(text, max_len=48):
    """为发布文案抽一句原话，返回值始终来自成片逐字稿。"""
    sentences = []
    for sentence in 断句(text):
        clean = sentence.strip()
        if 12 <= len(clean) <= max_len:
            score = sum(2 for word in 观点词 if word in clean)
            score += sum(1 for word in 具体词 if word in clean)
            score += 1 if clean.endswith(完整句尾) else 0
            sentences.append((score, clean))
    if sentences:
        return max(sentences, key=lambda item: item[0])[1]
    clean = text.strip()
    return clean[:max_len].rstrip("，,") + ("……" if len(clean) > max_len else "")


def 简介初稿(章节):
    titles = [标题初稿(c["文本"], 24) for c in 章节]
    usable = [t for t in titles if t][:3]
    if not usable:
        return "以下章节与文字均来自剪辑后的成片逐字稿。"
    if len(usable) == 1:
        return f"这期从「{usable[0]}」聊开，以下章节时间点均来自剪辑后的成片。"
    head = "、".join(f"「{t}」" for t in usable[:-1])
    return f"这期从{head}聊到「{usable[-1]}」。以下章节时间点均来自剪辑后的成片。"


def 切章节(句子, 总长):
    """
    按「句子之间的空档」找章节边界。
    空档 = 下一句开始时间 - 这一句开始时间 - 这句大概说了多久。
    话题要换的时候，中间通常会有一个明显的停顿。
    """
    # 长节目保持至少 150 秒；短 demo/预告片按总长自动缩小，但不低于 60 秒。
    最短间隔 = min(章节最短秒, max(60, 总长 // max(目标章节数, 1)))
    候选 = []
    for i in range(len(句子) - 1):
        起, 文 = 句子[i]
        下起 = 句子[i + 1][0]
        说话时长 = len(re.sub(r"[^一-鿿A-Za-z0-9]", "", 文)) / 5.0  # 中文口播约 5 字/秒
        空档 = (下起 - 起) - 说话时长
        候选.append((空档, i + 1, 下起))

    候选.sort(reverse=True)
    边界 = [0]
    for _, idx, 秒 in 候选:
        if all(abs(秒 - 句子[b][0]) >= 最短间隔 for b in 边界) and 总长 - 秒 >= 最短间隔:
            边界.append(idx)
        if len(边界) >= 目标章节数:
            break
    边界.sort()

    章 = []
    for k, b in enumerate(边界):
        止 = 边界[k + 1] if k + 1 < len(边界) else len(句子)
        文本 = "".join(t for _, t in 句子[b:止])
        章.append({"起": 句子[b][0], "首句": 句子[b][1], "字数": len(文本),
                 "预览": 文本[:120], "文本": 文本})
    return 章


def 挑切片(句子, 总长):
    """滑动窗口找 40–95 秒的片段，按「像不像一段能独立成立的话」打分。"""
    候选 = []
    for i in range(len(句子)):
        最佳 = None
        for j in range(i + 1, len(句子)):
            长度 = 句子[j][0] - 句子[i][0]
            if 长度 < 切片长度[0]:
                continue
            if 长度 > 切片长度[1]:
                break
            文本 = "".join(t for _, t in 句子[i:j])
            字数 = len(re.sub(r"[^一-鿿A-Za-z0-9]", "", 文本))
            if 字数 < 60:
                continue

            分 = 0
            # 命中数封顶：不封顶的话，长片段只因为更长就赢，选出来的会全是 95 秒
            分 += min(sum(1 for w in 观点词 if w in 文本), 3) * 3
            分 += min(sum(1 for w in 具体词 if w in 文本), 2) * 2
            语速 = 字数 / max(长度, 1)
            分 += 4 if 3.5 <= 语速 <= 6.5 else 0        # 语速正常，不是念稿也不是卡壳
            开头 = 句子[i][1].strip()
            前句 = 句子[i - 1][1].strip() if i else ""
            结尾 = 句子[j - 1][1].strip()
            下句 = 句子[j][1].strip() if j < len(句子) else ""

            # 候选要尽量像一段完整的话，而不是从上一句中间截进来、在下一句中间截断。
            分 += 5 if i == 0 or 前句.endswith(完整句尾) else -3
            分 += 4 if 开头.startswith(好开头) else 0
            分 -= 5 if 开头.startswith(弱开头) else 0
            分 += 6 if 结尾.endswith(完整句尾) else -5
            分 -= 4 if 结尾.rstrip("，,").endswith(拖尾词) else 0
            分 += 2 if 下句.startswith(("那", "接下来", "然后", "所以", "但是", "其实")) else 0
            分 += 3 if 开头[:2] not in ("对啊", "嗯嗯", "是的") else -3
            分 += 2 if 60 <= 长度 <= 80 else 0           # 小红书切片比较顺的长度
            分 -= 5 if 句子[i][0] < 90 else 0            # 避开开场白
            分 -= 3 if 句子[i][0] > 总长 - 60 else 0     # 避开片尾
            if 最佳 is None or 分 > 最佳["分"]:
                最佳 = {"起": 句子[i][0], "止": 句子[j][0], "长": 长度,
                        "字数": 字数, "分": 分, "文本": 文本,
                        "完整开头": i == 0 or 前句.endswith(完整句尾),
                        "完整结尾": 结尾.endswith(完整句尾)}
        if 最佳:
            候选.append(最佳)

    # 把整期分成几段，每段限量取——否则高分片段会全挤在前半集，
    # 选出来像是顺序切块，而不是从整期里挑出来的。
    候选.sort(key=lambda x: -x["分"])
    区间数 = 6
    每区上限 = max(2, 切片候选数 // 区间数)
    区间计数 = [0] * 区间数
    选中 = []
    for c in 候选:
        区 = min(int(c["起"] / max(总长, 1) * 区间数), 区间数 - 1)
        if 区间计数[区] >= 每区上限:
            continue
        if all(c["起"] >= s["止"] + 切片最小间隔 or
               c["止"] + 切片最小间隔 <= s["起"] for s in 选中):
            选中.append(c)
            区间计数[区] += 1
        if len(选中) >= 切片候选数:
            break
    return sorted(选中, key=lambda x: x["起"])


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("期", help="单集目录，比如 episodes/ep04")
    ap.add_argument("-h", "--help", action="help", help="看用法")
    args = ap.parse_args()

    期目录 = Path(args.期)
    if not 期目录.is_absolute():
        期目录 = PROJECT_DIR / args.期
    if not 期目录.is_dir():
        sys.exit(f"❌ 找不到文件夹：{期目录}")

    稿 = sorted(期目录.glob("*转写*带时间戳*.txt"))
    稿 = [p for p in 稿 if "原始" not in p.name and "试跑" not in p.name]
    if not 稿:
        sys.exit(f"❌ 在 {期目录.name} 里没找到剪辑后的转写稿\n"
                 f"   先跑：python3 tools/transcribe.py {期目录.name}/剪辑后的音频.mp3")

    句子, 术语修正 = 读转写(稿[0])
    if not 句子:
        sys.exit("❌ 转写稿是空的，或者格式不对")
    总长 = 句子[-1][0]
    全文 = "\n".join(f"[{时间(s)}] {t}" for s, t in 句子)
    config = load_config()
    节目名 = config.get("show_name", "你的播客")
    主题 = "、".join(config.get("topics", [])) or "这一期的话题"
    听众 = config.get("audience", "这档播客的目标听众")

    print(f"📄 用的是剪辑后的成片转写：{稿[0].name}（{len(句子)} 句，{时间(总长)}）")
    print("🔒 没有读取原始录音转写；输出内容只可能来自成片稿。")
    if 术语修正:
        print(f"🔧 输出前重新应用术语表，共修正 {len(术语修正)} 处。")

    章 = 切章节(句子, 总长)
    切片 = 挑切片(句子, 总长)
    章节标题 = [标题初稿(c["文本"], 24) for c in 章]

    # ---------- Show Notes ----------
    L = []
    A = L.append
    A(f"# {期目录.name} Show Notes 素材")
    A("")
    A(f"成片时长 {时间(总长)}。以下时间点全部来自**剪辑后的成片**，可以直接用。")
    A(f"来源文件：`{稿[0].name}`。生成时未读取原始录音转写；文字已重新应用术语表。")
    A("")
    A("## 可直接修改的 Show Notes 初稿")
    A("")
    A(简介初稿(章))
    A("")
    for c, title in zip(章, 章节标题):
        A(f"- {时间(c['起'])}　{title}")
    A("")
    A("标题初稿只截取成片原话，不补写成片里没有的内容；发布前可按节目语气润色。")
    A("")
    A("## 章节定位依据")
    A("")
    A("工具是按「说话中间的停顿」切的——话题要换的时候通常会有个明显的空档。")
    A("时间点来自成片；标题初稿来自对应章节的原话。")
    A("")
    A("| 时间点 | 这一段的第一句 | 字数 |")
    A("|---|---|---|")
    for c, title in zip(章, 章节标题):
        A(f"| {时间(c['起'])} | {title}｜{c['首句'][:24]} | {c['字数']} |")
    A("")
    for c in 章:
        A(f"**{时间(c['起'])}**　{c['预览']}……")
        A("")
    A("---")
    A("")
    A("## 下面整段复制，粘贴给任意 AI")
    A("")
    A("```")
    A(f"这是一档播客的单集逐字稿，节目叫《{节目名}》，主要聊{主题}。")
    A(f"听众是{听众}。请帮我写这一期的 Show Notes。")
    A("")
    A("要求：")
    A("1. 一段 100 字以内的简介，说清楚这期在聊什么、为什么值得听。不要用「本期我们探讨了」这种开头。")
    A("2. 一份章节列表，用下面给出的时间点，每个配一句话标题。标题要具体，别写「关于成长」这种。")
    A("3. 挑 3–5 句原话作为金句，必须一字不改地从稿子里抄，不要改写。")
    A("4. 语气跟着稿子里两个人说话的方式走，不要写成公众号推文。")
    A("5. 所有信息只能来自下面这份成片逐字稿，不补写稿子里没出现的内容。")
    A("")
    A("已经切好的章节时间点（位置是准的，请直接用，不要自己另外估时间）：")
    for c in 章:
        A(f"  {时间(c['起'])}")
    A("")
    A("完整逐字稿：")
    A("")
    A(全文)
    A("```")

    sn = 期目录 / f"{期目录.name}_ShowNotes素材.md"
    sn.write_text("\n".join(L) + "\n", encoding="utf-8")

    # ---------- 切片 ----------
    L = []
    A = L.append
    A(f"# {期目录.name} 切片候选")
    A("")
    A(f"从成片里挑出 {len(切片)} 段，长度都在 {切片长度[0]}–{切片长度[1]} 秒之间，适合做小红书切片。")
    A(f"来源文件：`{稿[0].name}`。生成时未读取原始录音转写；文字已重新应用术语表。")
    A("")
    A("**这只是候选。**哪几条真的能用、按什么顺序排，是判断，工具不做。")
    A("尤其注意：有些话单独截出来会变味，前面那句铺垫可能才是让它成立的东西——")
    A("这种只有你听得出来。")
    A("")
    A("| # | 时间段 | 时长 | 字数 | 边界 |")
    A("|---|---|---|---|---|")
    for i, c in enumerate(切片, 1):
        边界 = "完整" if c["完整开头"] and c["完整结尾"] else "需回听"
        A(f"| {i} | {时间(c['起'])}–{时间(c['止'])} | {c['长']}s | {c['字数']} | {边界} |")
    A("")
    A("---")
    A("")
    for i, c in enumerate(切片, 1):
        A(f"### {i}. {时间(c['起'])} – {时间(c['止'])}　（{c['长']} 秒）")
        A("")
        title = 标题初稿(c["文本"])
        quote = 金句初稿(c["文本"])
        A(f"**标题初稿**：{title}")
        A("")
        A(f"**发布文案初稿**：「{quote}」完整对话见《{节目名}》（成片 {时间(c['起'])}–{时间(c['止'])}）。")
        A("")
        A(f"> {c['文本'][:400]}{'……' if len(c['文本']) > 400 else ''}")
        A("")
    A("---")
    A("")
    A("## 下面整段复制，粘贴给任意 AI")
    A("")
    A("```")
    A(f"这是播客《{节目名}》某一期里挑出来的若干片段，我要把它们剪成短视频。")
    A(f"听众是{听众}。")
    A("")
    A("请对每一个片段：")
    A("1. 起一个标题，不超过 20 字。要用片段里真实说过的话作为钩子，不要编。")
    A("2. 写一段 50 字以内的正文文案，口语，不要煽情，不要用「你是否也」这种句式。")
    A("3. 给 3–5 个小红书话题标签。")
    A("4. 如果你觉得某个片段单独拿出来会变味、或者需要前面的铺垫才成立，直接说出来，")
    A("   并说明缺了什么。这一条比写文案重要。")
    A("5. 不要补充片段里没有说过的事实，也不要引用其他版本的逐字稿。")
    A("")
    A("片段如下，时间点来自剪辑后的成片，可以直接用来定位：")
    A("")
    for i, c in enumerate(切片, 1):
        A(f"【片段 {i}】{时间(c['起'])}–{时间(c['止'])}（{c['长']} 秒）")
        A(c["文本"])
        A("")
    A("```")

    qp = 期目录 / f"{期目录.name}_切片候选.md"
    qp.write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"\n✅ 完成")
    print(f"   {sn.name}　← Show Notes 初稿 + 润色指令")
    print(f"   {qp.name}　← 短视频切片时间轴 + 每条文案初稿")
    print(f"\n📌 时间点都来自剪辑后的成片，不会对不上，也不会把剪掉的内容写进去。")
    print(f"📌 初稿只使用成片文字；留哪条、怎么排和最终语气，由你判断。")


if __name__ == "__main__":
    main()
