# Podcast AI Workflow

一套给非技术播客主理人使用的本地工作流，覆盖：

**录音结束 → 剪前/剪后转写 → 数据辅助剪辑复盘 → 新一期 Show Notes / 短视频候选**

它不是三个互不相关的小工具。第一段建立可比对的数据，第二段从历史高低表现期提炼下一期的剪辑假设，第三段只服务之后的新内容。三段共享同一份成片时间轴，同时把“该删什么、该发什么”的最终判断留给人。

## 作为 Codex Skill 一键安装

在 Codex 中直接说：

> 请安装这个 Skill：https://github.com/Juliejue/podcast-ai-workflow/tree/main/skills/podcast-ai-workflow

也可以使用 Codex 自带的安装器：

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo Juliejue/podcast-ai-workflow \
  --path skills/podcast-ai-workflow
```

安装后，在下一轮对话中使用：

```text
用 $podcast-ai-workflow 处理这个播客文件夹：先检查现有素材，再做剪前/剪后转写、剪辑复盘或成片宣发。
```

Skill 会先检查环境。逐字稿对比和宣发只需要 Python 3.10+；本地转写和声波指标需要额外依赖。安装依赖和首次下载 Whisper 模型前，它会先征求同意。私有音频、逐字稿和配置始终留在使用者自己的工作区，不需要复制到 Skill 安装目录。

## 为什么做

项目从三个连续需求长出来：

1. 主理人需要同时拿到原始录音和剪辑成片的带时间轴逐字稿；
2. 高完播单集出现后，需要知道它删了什么、保留了什么，以及低表现期下一次怎么剪；
3. 新一期发布前，需要基于成片自动准备 Show Notes 和短视频候选。

两位主播轮流剪辑时，原始录音、成片、SRT 和本地转写的命名与格式并不一致。最常见的两个宣发错误是：

- 时间点来自原始录音，发布时对不上成片；
- 文案引用了已经删掉的内容。

这套工具把可机械验证的部分固定下来：成片物料只读成片稿；剪辑复盘把转写差异、平台表现、声波和双人对话节奏放进同一张表，但不把小样本相关性写成因果。

## 三个工具

### 1. 剪前 / 剪后本地转写（来自使用者的首个需求）

```bash
python3 tools/transcribe.py episodes/ep05/audio.mp3
python3 tools/transcribe.py episodes/ep05/raw.mp4 --原始
```

第一次在原始录音上加 `--原始`，得到剪前逐字稿；剪辑完成后再对成片运行一次，得到发布版本逐字稿。基于 `faster-whisper`，同时生成带时间戳 TXT 与可导入剪辑软件的 SRT。`--试跑` 只处理前三分钟；`--模型` 可选 `small`、`medium`、`large-v3`。

### 2. 数据辅助剪辑复盘（核心需求）

```bash
python3 tools/compare_edits.py episodes/ep05
```

支持本工具的时间戳 TXT、已有 SRT，以及 `说话人(00:12:34): 正文` 形式的会议转写：

```bash
python3 tools/compare_edits.py episodes/ep05 --原始稿 raw-export.srt
```

算法先把两份稿子连成全文，再按字符顺序对齐，最后映射回原始时间轴。它不依赖两边使用同一种转写工具，也不要求切句一致。单集报告包含：

- 真实时长差与逐字对齐率；
- 疑似删除候选、原始时间点、置信度；
- 删除集中在前、中、后哪一段；
- 最长候选的原文，供人工回听。

更重要的是跨期模式。把历史高、低完播单集放在一起：

```bash
cp performance_data.example.json performance_data.json
python3 tools/compare_edits.py episodes/ep02 episodes/ep03 episodes/ep04 \
  --汇总 --表现数据 performance_data.json
```

`performance_data.json` 可填播放、完播率、平均播放时长、原始/成片媒体路径、说话人 A 和发布章节。报告会生成一张跨期表，覆盖：

- 剪前/剪后时长、文字删除率、长段删减和删减位置；
- 框架、章节数量、每个板块停留时间、话题切换密度；
- 文字密度、静默占比、长停顿、动态范围和频谱异常；
- 接话频率、轮流接话率、单次发言时长、长发言数量和双方文字占比；
- 高完播样本删了什么、保留了什么，以及低表现期下一次可验证的剪辑假设。

声波只说明“剪得多紧、音量是否异常”，不能代表内容质量；平台样本小时，报告会明确把结论标成工作假设，而不是因果证明。

会议转写里一段可能长达一分钟；脚本会先按标点细分，再按字数在相邻时间点之间插值。
文字候选总时长不必等于音频时长差：静默、停顿和语速变化会被单独列为“未由文字候选解释”。

### 3. 新一期宣发物料（辅助需求）

```bash
python3 tools/promo_materials.py episodes/ep05
```

只在未来的新一期完成剪辑后运行，历史分析期不需要重新生成宣发。它生成 Show Notes 初稿和短视频候选，只读取成片稿，并在输出里写明来源文件；候选的起止点必须是成片稿已有的时间戳。片段边界会标记为“完整”或“需回听”，两条候选之间至少保留 20 秒。

脚本不调用付费 API。输出附带可复制到任意大模型的 prompt，但标题、排序和发布决定仍由人完成。

## 作为独立命令行工具安装

需要 Python 3.10+。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
cp glossary.example.json glossary.json
```

在 `config.json` 填节目名、主播、主题和目标听众；在 `glossary.json` 增补人名、专有词和固定句式。

## 匿名演示

`demo/` 是人工编写的匿名素材，不来自真实节目。可以直接运行单集与跨期流程：

```bash
python3 tools/compare_edits.py demo
python3 tools/promo_materials.py demo
python3 tools/compare_edits.py demo/ep_low demo/ep_mid demo/ep_high \
  --汇总 --表现数据 demo/performance_data.json
```

仓库保留对应输出，包括 `demo/demo_跨期剪辑复盘.md`，方便不安装转写模型时直接查看结果。

## 验证

```bash
python3 -m unittest discover -s tests -v
```

测试会检查：

- 不同切句方式仍能对齐；
- 摘要型文件会被拒绝，不能冒充带时间轴逐字稿；
- 每个切片的起止点都来自成片稿；
- 每段候选文字都是成片稿连续片段；
- 原始稿独有的录前、录后内容不会进入宣发输出；
- 章节停留时间和指定说话人 A 的统计保持稳定。

真实项目回归覆盖三组带说话人时间轴的原始稿（公开仓库不含逐字稿或音频）：84:38 → 32:23、77:27 → 57:39、119:26 → 52:35。最高表现样本识别出 38 个候选，并把录前准备、录后复盘、重复追问和支线展开分别定位；低文字删减样本只有约 6% 文本表现为整段删除，其余时长差保留为停顿、语速或转写差异，避免把音频压缩误写成内容删减。

## 数据与隐私

`.gitignore` 默认排除：

- 音频、视频；
- 私人逐字稿和运行产物；
- `.env`、`config.json`、`glossary.json`；
- Python 缓存。

公开仓库只应提交代码、示例配置和匿名 demo。运行前仍建议执行一次敏感信息扫描。

## 已知边界

- 双人配合指标需要原始稿使用 `说话人(HH:MM:SS): 正文` 格式；成片说话比例是文字对齐估算。单声道混音更适合从录制端改成分轨。
- 转写差异会造成少量剪辑对比误报，因此报告使用“疑似删除候选”。
- 章节标题可以来自发布清单；自动章节边界基于停顿，不理解主题语义。
- 术语表不能安全修正“把一个真实主播名听成另一位真实主播名”的歧义。
- 播放量、完播率、标题、主题和流量来源可能共同影响结果；工具不判断某次删除“导致”了完播提升。
- 工具不修改音频，不替人决定该删、该留或该发布什么。

## 案例

完整产品案例：[heyjue.com/podcast-delivery.html](https://heyjue.com/podcast-delivery.html)
