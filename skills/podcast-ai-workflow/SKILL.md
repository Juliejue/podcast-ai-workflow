---
name: podcast-ai-workflow
description: "Run a privacy-first podcast workflow from raw/final transcription through cross-episode learning, evidence-first rough-cut guardrails, and style-validated Show Notes or short-video candidates. Use when the user asks to transcribe podcast media, compare raw and edited transcripts, learn from completion/performance data, prepare a human-reviewed editing action card, preserve a show's editorial intent, or generate promotional material strictly from a final cut."
---

# Podcast AI Workflow

Run a local workflow that learns from earlier episodes without letting a model silently make editorial decisions. Keep private media and transcripts in the user's workspace.

## Set up the run

1. Treat the directory containing this file as `SKILL_DIR`.
2. Treat the user's podcast directory as `WORKSPACE_DIR`.
3. Inspect filenames and the user's goal before running a stage.
4. Resolve all user inputs against `WORKSPACE_DIR`. Never expect private media beside this Skill.
5. Never overwrite original media, transcripts, or earlier reports.
6. Read [references/transcript-formats.md](references/transcript-formats.md) for unfamiliar transcript exports or performance data.

## Place each stage in the episode lifecycle

- **After recording:** transcribe the full raw recording.
- **After the first human rough cut, before final delivery:** create an editing guardrail card for the current episode.
- **After the final cut:** transcribe the final media and create style-checked Show Notes or clip candidates.
- **After performance data becomes meaningful:** update the cross-episode review so its lessons can inform a later episode.

Historical review guides future experiments. The guardrail card reviews the current rough cut. Neither stage edits audio or promises traffic results.

## Check readiness

Run the relevant check before changing the environment:

```bash
python3 "$SKILL_DIR/scripts/doctor.py" --require core
python3 "$SKILL_DIR/scripts/doctor.py" --require audio
python3 "$SKILL_DIR/scripts/doctor.py" --require transcription
```

`core` needs Python 3.10+. `audio` needs `av` and `numpy`. `transcription` also needs `faster-whisper`.

If dependencies are missing, explain what they enable and ask before installing. If approved, create a virtual environment inside `WORKSPACE_DIR` and install `"$SKILL_DIR/requirements.txt"`. Warn that the first transcription downloads a Whisper model.

Copy `assets/config.example.json`, `assets/glossary.example.json`, `assets/performance_data.example.json`, or `assets/editing_intent.example.json` only when the user wants editable local copies. Never put private values back into the installed Skill or public repository.

## Stage 1: transcribe raw and final recordings

Run once for the raw recording and again after editing:

```bash
python3 "$SKILL_DIR/scripts/transcribe.py" "/absolute/path/ep05/raw.mp4" --原始
python3 "$SKILL_DIR/scripts/transcribe.py" "/absolute/path/ep05/final.mp3"
```

Use `--试跑` for the first three minutes on a new machine. Use `--模型 small|medium|large-v3` only when the user has a speed or quality preference. Use `--配置` and `--术语表` for nonstandard paths.

Expect timestamped TXT and SRT in the recording directory. Existing outputs receive a version suffix. State that speaker diarization is not provided.

## Stage 2: learn from previous episodes

### Review one raw-to-final pair

```bash
python3 "$SKILL_DIR/scripts/compare_edits.py" "/absolute/path/ep05" \
  --原始稿 "/absolute/path/ep05/raw-transcript.txt" \
  --成片稿 "/absolute/path/ep05/final-transcript.txt"
```

Require a full timestamped raw transcript and a timestamped final transcript from the same episode. Reject summaries, sparse chapter notes, empty inputs, and very low alignment. Call the output suspected deletion candidates, not ground truth.

### Build a cross-episode review

Use two or more paired episodes and manually supplied performance data:

```bash
python3 "$SKILL_DIR/scripts/compare_edits.py" \
  "/absolute/path/ep02" "/absolute/path/ep03" "/absolute/path/ep04" \
  --汇总 \
  --表现数据 "/absolute/path/performance_data.json" \
  --输出 "/absolute/path/cross-episode-editing-review.md"
```

Compare duration, deletion location, text density, section timing, topic movement, pause and audio metrics, turn-taking, speaking balance, and recurring production talk only when the inputs support those metrics.

Use completion rate and average listening time as context. Keep the claims correlational. State sample size and missing inputs. End with no more than three hypotheses and one controlled experiment for the next episode. Do not regenerate promotion for historical episodes unless the user asks.

Audio metrics require media paths in the performance JSON. Speaker metrics require raw transcripts in `Speaker(HH:MM:SS): text` form. Omit unsupported metrics.

## Stage 3: create a rough-cut editing guardrail card

Use this after a human has made a first rough cut and before the final cut.

1. Read [references/editing-guardrails.md](references/editing-guardrails.md).
2. Create `editing_intent.json` from `assets/editing_intent.example.json` with the user. Record the episode question, desired listener takeaway, lead host, desired feeling, protected ranges or phrases, signature digressions, and one experiment.
3. Run:

```bash
python3 "$SKILL_DIR/scripts/editing_guardrails.py" "/absolute/path/ep05" \
  --原始稿 "/absolute/path/ep05/raw-transcript.txt" \
  --粗剪稿 "/absolute/path/ep05/rough-cut-transcript.txt" \
  --创作意图 "/absolute/path/ep05/editing_intent.json" \
  --历史复盘 "/absolute/path/cross-episode-editing-review.md"
```

4. Open the generated card and inspect the cited transcript ranges. Enrich generic lines with episode-specific context only when the evidence supports it.
5. For every candidate, preserve both a reason to shorten and a reason to keep. Name the evidence source, risk, confidence, and the missing information.
6. Treat written intent as higher authority than a generic pattern from past performance. Keep protected material red. Do not recommend direct deletion for red candidates.
7. Leave the human decision blank. The allowed decisions are keep, shorten, remove, or listen back.

Use green only for clear production residue or an exact repeated take. Use yellow for context-sensitive pacing choices. Never modify media or claim that a recommendation maximizes completion.

## Stage 4: create final-cut promotion

Run this only for the episode being prepared for publication:

```bash
python3 "$SKILL_DIR/scripts/promo_materials.py" "/absolute/path/ep05" \
  --成片稿 "/absolute/path/ep05/final-transcript.txt" \
  --风格 "$SKILL_DIR/references/show-notes-style.md"
```

The script creates Show Notes source and short-video candidates. It accepts only a final transcript and embeds the fixed style guide in the reusable prompt.

### Finish the Show Notes

1. Read [references/show-notes-style.md](references/show-notes-style.md).
2. Write the final copy to `ShowNotes成稿.md` using facts, quotes, and timestamps from the final transcript only.
3. Run:

```bash
python3 "$SKILL_DIR/scripts/validate_show_notes.py" "/absolute/path/ShowNotes成稿.md" \
  --成片稿 "/absolute/path/ep05/final-transcript.txt"
```

4. Rewrite and rerun until validation passes.

The validator rejects prohibited punctuation and sentence patterns, missing fixed sections or Xiaohongshu follow text, and timeline nodes absent from the final transcript. Semantic tone still requires human review.

### Verify clip candidates

Check that every start and end timestamp exists in the final transcript, every excerpt is contiguous final-cut text, and no raw-only phrase appears. Treat selection, ordering, final copy, and publication as human choices.

## Validate with anonymous data

Copy `assets/demo` to a temporary or user-approved workspace. Do not write generated reports inside an installed Skill.

```bash
python3 "$SKILL_DIR/scripts/compare_edits.py" demo

python3 "$SKILL_DIR/scripts/editing_guardrails.py" demo \
  --原始稿 "匿名示例_转写_带时间戳_原始录音.txt" \
  --粗剪稿 "匿名示例_转写_带时间戳.txt" \
  --创作意图 "editing_intent.json"

python3 "$SKILL_DIR/scripts/promo_materials.py" demo \
  --成片稿 "匿名示例_转写_带时间戳.txt"

python3 "$SKILL_DIR/scripts/validate_show_notes.py" \
  "demo/demo_ShowNotes成稿.md" \
  --成片稿 "demo/匿名示例_转写_带时间戳.txt"
```

After every run, report the exact inputs, created outputs, skipped metrics, and quality warnings. Never expose private transcripts, media, absolute personal paths, keys, or client data in a public repository.
