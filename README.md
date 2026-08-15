# Podcast AI Workflow

一个可安装的 Codex Skill，把播客从录音结束后的零散工作连成完整流程：

**原始录音 / 成片转写 → 跨期剪辑学习 → 本期粗剪护栏 → 风格化 Show Notes / 切片候选**

最核心的两个结果是：

- 一张有证据、有反方理由、有风险等级的剪辑护栏卡，帮助主播回听和判断，不替主播删音频；
- 一套只读取成片、遵守节目固定语气、能自动检查时间点和语言禁区的 Show Notes 流程。

所有真实音频和逐字稿都留在使用者自己的电脑里。公开仓库只包含代码、配置示例与人工编写的匿名 demo。

## 一键安装

在 Codex 中直接说：

```text
请安装这个 Skill：https://github.com/Juliejue/podcast-ai-workflow/tree/main/skills/podcast-ai-workflow
```

也可以使用 Codex 自带的安装器：

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo Juliejue/podcast-ai-workflow \
  --path skills/podcast-ai-workflow
```

安装后重新开始一轮对话，再说：

```text
用 $podcast-ai-workflow 检查这个播客文件夹。先告诉我现有素材能完成哪一步，再继续执行。
```

## 先看结果

- [匿名剪辑护栏卡](skills/podcast-ai-workflow/assets/demo/demo_剪辑护栏卡.md)
- [匿名 Show Notes 成稿](skills/podcast-ai-workflow/assets/demo/demo_ShowNotes成稿.md)
- [三分钟展示稿](DEMO.md)

匿名 demo 可以直接试：

```text
用 $podcast-ai-workflow 处理仓库里的匿名 demo：生成粗剪护栏卡，解释为什么“买咖啡”片段被保护；再校验 demo Show Notes。不要安装转写模型。
```

## 三个组成部分

### 1. 原始录音与成片双转写

使用者先交付原始录音，得到带时间轴 TXT 和 SRT。完成剪辑后再交付成片，得到第二份同格式转写稿。两份稿子建立了后续复盘的共同时间轴。

本地转写基于 `faster-whisper`。支持前三分钟试跑、术语表和多档模型；已有输出会自动保留版本，不覆盖原文件。

### 2. 跨期剪辑学习与本期粗剪护栏

这部分分成两个时间点：

| 何时使用 | 输入 | 输出 | 服务谁 |
|---|---|---|---|
| 历史单集积累到表现数据以后 | 多期原始稿、成片稿、手动填写的完播率等 | 跨期剪辑复盘 | 指导下一期的一个可验证实验 |
| 本期完成第一轮粗剪以后 | 本期原始稿、粗剪稿、创作意图、可选历史复盘 | 剪辑护栏卡 | 指导本期最终回听和二剪 |

跨期复盘会比较删减位置、板块时长、文字密度、话题移动、停顿、声波和双人接话等可获得维度。它会明确区分相关性与因果，不把一两期数据包装成流量规律。

粗剪护栏卡先读取主播写下的本期问题、听众收获、主叙事者、想保留的感受、受保护片段和一个实验，再对照粗剪前后的差异。每个候选必须同时显示：

- 原始时间与原文证据；
- 片段在本期可能承担的功能；
- 考虑缩短的理由；
- 考虑保留的理由；
- 证据来源、风险与置信度；
- 留空的人工决定。

绿色只用于明显制作残留或完全重复的录制；黄色必须结合上下文；红色来自创作意图保护，工具不提供删除选项。主播的明确意图优先于历史高表现期的通用规律。

### 3. 风格化 Show Notes 与切片候选

这一步只在新一期成片确认后运行，而且只读取成片逐字稿。

Skill 会生成章节时间点、Show Notes 写作素材和小红书切片候选，再用《稳稳接住》的固定风格完成成稿。风格指南包括具体场景开篇、情绪与内在冲突、固定栏目、固定节目介绍和同名小红书关注提示。

这里有两道边界。素材生成只读取成片稿，避免把原始稿已经删除的内容带进文案；最终校验会拦截：

- 不在成片逐字稿里的时间点；
- 缺失的固定栏目或小红书提示；
- 破折号；
- “不是 A，而是 B”式的人工金句；

语言校验能守住硬边界，最终语气和发布决定仍需要主播确认。

## 工作周期

```text
录音完成
  ↓
原始转写
  ↓
人工粗剪 → 剪辑护栏卡 → 人工回听与二剪
  ↓
成片转写 → Show Notes / 切片候选 → 风格与时间点校验
  ↓
发布并等待表现数据
  ↓
跨期复盘 → 下一期只验证一个新实验
```

## 独立命令示例

### 跨期复盘

```bash
python3 skills/podcast-ai-workflow/scripts/compare_edits.py \
  episodes/ep02 episodes/ep03 episodes/ep04 \
  --汇总 --表现数据 performance_data.json
```

### 粗剪护栏卡

```bash
python3 skills/podcast-ai-workflow/scripts/editing_guardrails.py episodes/ep05 \
  --原始稿 raw-transcript.txt \
  --粗剪稿 rough-cut-transcript.txt \
  --创作意图 editing_intent.json \
  --历史复盘 cross-episode-editing-review.md
```

### Show Notes 素材与校验

```bash
python3 skills/podcast-ai-workflow/scripts/promo_materials.py episodes/ep05 \
  --成片稿 final-transcript.txt

python3 skills/podcast-ai-workflow/scripts/validate_show_notes.py ShowNotes成稿.md \
  --成片稿 episodes/ep05/final-transcript.txt
```

## 验证

```bash
python3 -m unittest discover -s tests -v
```

当前自动化测试覆盖：不同转写切句的对齐、摘要误用拦截、原始稿独有内容隔离、跨期输出、受保护片段、三档风险、固定 Show Notes 风格、禁用语言和成片时间点校验。

## 重要边界

- 平台数据需要使用者手动填写，Skill 不抓取私有小宇宙后台。
- 声波指标只能描述节奏、静默和音量特征，不能判断内容质量。
- 转写差异可能带来少量对比误报，所以输出使用“疑似删除候选”。
- 单声道混音无法可靠还原精确分轨；双人接话指标依赖带说话人时间轴的原始稿。
- Skill 不修改音频，不自动删除，不保证完播率或流量增长。

完整产品案例：[heyjue.com/podcast-delivery.html](https://heyjue.com/podcast-delivery.html)
