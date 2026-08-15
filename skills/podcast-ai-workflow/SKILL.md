---
name: podcast-ai-workflow
description: "Run a privacy-first local podcast post-production workflow: transcribe raw and final audio/video to timestamped TXT and SRT, compare pre-edit and final transcripts, review editing patterns across episodes with completion/performance data and optional audio/turn-taking metrics, and generate Show Notes plus short-video clip candidates strictly from the final transcript. Use when the user asks about podcast transcription, editing review, retention-informed editing, cross-episode analysis, Show Notes, Xiaohongshu/social clips, or a recording-to-promotion workflow."
---

# Podcast AI Workflow

Use the bundled scripts for deterministic extraction and alignment. Keep editorial judgment with the user.

## Set up the run

1. Treat the directory containing this `SKILL.md` as `SKILL_DIR`.
2. Treat the user's current podcast/project directory as `WORKSPACE_DIR`.
3. Resolve user inputs against `WORKSPACE_DIR`; never expect private media beside the installed skill.
4. Inspect filenames before running anything. Never modify or overwrite original audio, video, or transcripts.
5. Read [references/transcript-formats.md](references/transcript-formats.md) when inputs use unfamiliar transcript formats or when preparing cross-episode performance data.

## Choose the requested stage

- **Raw/final transcription**: run Stage 1.
- **One-episode deleted/retained review**: run Stage 2 with one paired episode.
- **Learn from historical episodes for future content**: run Stage 2 in cross-episode mode. Do not generate promotion for those historical episodes unless explicitly requested.
- **Prepare material for a newly finished episode**: run Stage 3, using only the final-cut transcript.
- **Full workflow**: run Stages 1 → 2 → 3 as the required inputs become available.

## Check readiness without changing the system

Run the relevant check first:

```bash
python3 "$SKILL_DIR/scripts/doctor.py" --require core
python3 "$SKILL_DIR/scripts/doctor.py" --require audio
python3 "$SKILL_DIR/scripts/doctor.py" --require transcription
```

`core` needs only Python 3.10+. `audio` needs `av` and `numpy`; `transcription` also needs `faster-whisper`.

If dependencies are missing, explain what they enable and ask before installing them. If approved, create a virtual environment in `WORKSPACE_DIR` and install `"$SKILL_DIR/requirements.txt"`. Warn that the first transcription downloads the selected Whisper model. Never install packages or download a model silently.

Copy `assets/config.example.json` and `assets/glossary.example.json` into `WORKSPACE_DIR` only when the user wants editable local configuration. Name the copies `config.json` and `glossary.json`. Do not put private values back into the skill or public repository.

## Stage 1 — Transcribe raw and final recordings

Run once for the raw recording and again after editing:

```bash
python3 "$SKILL_DIR/scripts/transcribe.py" "/absolute/path/ep05/raw.mp4" --原始
python3 "$SKILL_DIR/scripts/transcribe.py" "/absolute/path/ep05/final.mp3"
```

Use `--试跑` for the first three minutes when validating a new machine or glossary. Use `--模型 small|medium|large-v3` only when the user has a speed/quality preference. Use `--配置` and `--术语表` for nonstandard configuration locations.

Expected outputs are timestamped TXT and SRT files in the recording's directory. Existing outputs receive a version suffix; do not delete earlier versions. State that speaker diarization is not provided.

## Stage 2 — Review editing choices

### One episode

Prefer explicit transcript paths when naming is ambiguous:

```bash
python3 "$SKILL_DIR/scripts/compare_edits.py" "/absolute/path/ep05" \
  --原始稿 "/absolute/path/ep05/raw-transcript.txt" \
  --成片稿 "/absolute/path/ep05/final-transcript.txt"
```

Require a full timestamped raw transcript and a timestamped final transcript from the same episode. Reject summaries, sparse chapter notes, empty inputs, or very low text alignment. Present deletions as **suspected deletion candidates**, not ground truth. Ask the user to listen back to high-value candidates before deciding why they were cut.

### Cross-episode review for future episodes

Use two or more paired episode directories and optional performance data:

```bash
python3 "$SKILL_DIR/scripts/compare_edits.py" \
  "/absolute/path/ep02" "/absolute/path/ep03" "/absolute/path/ep04" \
  --汇总 \
  --表现数据 "/absolute/path/performance_data.json" \
  --输出 "/absolute/path/cross-episode-editing-review.md"
```

Use completion rate or average listening time to choose high- and low-performing samples. Compare structure, section duration, text density, deletion location, long cuts, pause/rhythm metrics, turn-taking frequency, speaking balance, topic movement, and recurring production talk when the available files support them.

Keep claims descriptive: small platform samples and editing differences are correlational. Phrase findings as hypotheses and propose one controlled change for the next episode. Do not claim that a cut caused retention or traffic changes.

Audio metrics require audio paths in the performance JSON. Speaker metrics require raw transcripts in `Speaker(HH:MM:SS): text` form. If either input is absent, omit the unsupported metric instead of inventing it.

## Stage 3 — Generate promotion from the final cut

Run this only for the episode the user is preparing to publish:

```bash
python3 "$SKILL_DIR/scripts/promo_materials.py" "/absolute/path/ep05" \
  --成片稿 "/absolute/path/ep05/final-transcript.txt"
```

Always prefer `--成片稿`. The script rejects filenames marked raw/trial and asks for disambiguation when several final candidates exist. It generates:

- Show Notes source with chapter timestamps and a reusable refinement prompt;
- short-video candidates with final-cut start/end timestamps, draft hooks, and a reusable copy prompt.

Verify before handoff:

1. Every timestamp exists in the final transcript.
2. Every candidate is a contiguous excerpt of final-transcript text.
3. Raw-only phrases do not appear in either output.
4. Claims and quotes do not add facts absent from the final transcript.
5. Clip ordering, final wording, and publish decisions remain explicitly human choices.

## Validate with anonymous data

When checking a fresh installation, copy `assets/demo` to a temporary or user-approved workspace before running it. Do not write generated reports inside the installed skill.

```bash
python3 "$SKILL_DIR/scripts/compare_edits.py" demo
python3 "$SKILL_DIR/scripts/promo_materials.py" demo --成片稿 "匿名示例_转写_带时间戳.txt"
python3 "$SKILL_DIR/scripts/compare_edits.py" demo/ep_low demo/ep_mid demo/ep_high \
  --汇总 --表现数据 demo/performance_data.json
```

After every run, report the exact inputs used, outputs created, skipped metrics, and any quality warning. Never expose private transcripts, media, absolute personal paths, keys, or client names in a public repository.
