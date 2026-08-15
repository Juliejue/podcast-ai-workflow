# Input formats

## Timestamped final transcript

Use one utterance per line:

```text
[00:00] Opening sentence.
[01:27] Next sentence.
```

Minutes may exceed 59. This format is required by the promotion script and supported by the comparison script.

## Speaker timestamp raw transcript

Use this format when turn-taking and speaker balance are needed:

```text
Host A(00:00:03): Opening sentence.
Host B(00:00:18): Follow-up question.
```

The comparison script also accepts SRT and timestamped TXT for raw inputs, but those formats do not identify speakers.

## Full transcript quality

A usable raw transcript contains many timestamped utterances across the full recording. Reject chapter summaries, a handful of long synopsis paragraphs, notes without timestamps, or a transcript from another episode. Text alignment below the tool's reliability threshold must stop the report.

## Performance data

Start from `assets/performance_data.example.json`. The top-level keys should match episode directory names. Useful fields include:

```json
{
  "ep04": {
    "播放": 105,
    "完播率": 0.82,
    "平均播放时长": "48:05",
    "speaker_a": "Host A",
    "raw_audio": "/absolute/path/ep04/raw.mp4",
    "final_audio": "/absolute/path/ep04/final.mp3",
    "chapters": [["00:00", "Opening"], ["05:10", "Story"]]
  }
}
```

Completion rate may be `0.82` or `82`. Prefer absolute media paths. Relative paths are resolved against the directory from which the script is run.

Platform metrics select samples and contextualize differences; they do not prove that editing caused a result. Record missing fields as unavailable and omit unsupported comparisons.
