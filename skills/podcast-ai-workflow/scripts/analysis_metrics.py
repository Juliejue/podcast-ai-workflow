"""Internal metrics used by the cross-episode editing review.

This module is not a fourth user-facing tool. It keeps audio and turn-taking
calculations separate from the compare_edits command.
"""

import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median


def parse_clock(value):
    parts = [int(part) for part in str(value).split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"无法识别时间：{value}")


def media_duration(path: Path):
    import av

    with av.open(str(path)) as container:
        return float(container.duration / av.time_base) if container.duration else 0.0


def audio_metrics(path: Path):
    """Decode to mono 16 kHz and summarize waveform/pause/spectrum traits."""
    import av
    import numpy as np

    rate = 16000
    window_seconds = 0.5
    window_size = int(rate * window_seconds)
    rms_db, peaks, centroids = [], [], []
    clipped = sample_count = window_index = 0
    pending = np.empty(0, dtype=np.float32)

    def dbfs(value):
        return 20 * math.log10(max(float(value), 1e-10))

    with av.open(str(path)) as container:
        duration = float(container.duration / av.time_base) if container.duration else 0.0
        stream = next(stream for stream in container.streams if stream.type == "audio")
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=rate)
        for frame in container.decode(stream):
            converted_frames = resampler.resample(frame)
            if not isinstance(converted_frames, list):
                converted_frames = [converted_frames]
            for converted in converted_frames:
                if converted is None:
                    continue
                data = converted.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                pending = np.concatenate((pending, data))
                while pending.size >= window_size:
                    block = pending[:window_size]
                    pending = pending[window_size:]
                    rms = float(np.sqrt(np.mean(block * block)))
                    rms_db.append(dbfs(rms))
                    peaks.append(float(np.max(np.abs(block))))
                    clipped += int(np.count_nonzero(np.abs(block) >= 0.999))
                    sample_count += block.size
                    if window_index % 10 == 0:
                        spectral = block[:4096] * np.hanning(4096)
                        magnitude = np.abs(np.fft.rfft(spectral))
                        frequencies = np.fft.rfftfreq(spectral.size, 1 / rate)
                        denom = float(magnitude.sum())
                        if denom:
                            centroids.append(float((frequencies * magnitude).sum() / denom))
                    window_index += 1

    values = np.asarray(rms_db, dtype=np.float32)
    median_all = float(np.median(values)) if values.size else -100.0
    threshold = max(-50.0, median_all - 18.0)
    silence_flags = values < threshold
    active = values[~silence_flags]
    pause_lengths, current = [], 0
    for flag in silence_flags.tolist():
        if flag:
            current += 1
        elif current:
            pause_lengths.append(current * window_seconds)
            current = 0
    if current:
        pause_lengths.append(current * window_seconds)
    long_pauses = [value for value in pause_lengths if value >= 1.5]
    minutes = max(duration / 60, 1e-6)
    return {
        "duration_seconds": duration,
        "median_active_dbfs": round(float(np.median(active)) if active.size else median_all, 2),
        "active_dynamic_range_db": round(float(np.percentile(active, 90) - np.percentile(active, 10)) if active.size else 0, 2),
        "peak_dbfs": round(dbfs(max(peaks, default=0)), 2),
        "clipping_percent": round(clipped / max(sample_count, 1) * 100, 5),
        "silence_percent": round(float(np.mean(silence_flags)) * 100 if silence_flags.size else 0, 2),
        "long_pauses_per_minute": round(len(long_pauses) / minutes, 2),
        "median_spectral_centroid_hz": round(float(np.median(centroids)) if centroids else 0, 1),
    }


def normalize(text):
    return re.sub(r"[^一-鿿A-Za-z0-9]", "", text)


def parse_speaker_transcript(path: Path, speaker_a=None):
    turns = []
    speaker_map = {}
    pattern = re.compile(r"^(.*?)\((\d+):(\d+):(\d+)\)\s*[:：]\s*(.*)$")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line.strip())
        if not match or not match.group(5).strip():
            continue
        raw_name = match.group(1).strip()
        if speaker_a:
            speaker = "A" if raw_name.casefold() == str(speaker_a).casefold() else "B"
        else:
            if raw_name not in speaker_map:
                speaker_map[raw_name] = "A" if not speaker_map else "B"
            speaker = speaker_map[raw_name]
        seconds = int(match.group(2)) * 3600 + int(match.group(3)) * 60 + int(match.group(4))
        turns.append((seconds, speaker, match.group(5).strip()))
    return turns


def parse_final_transcript(path: Path):
    out = []
    pattern = re.compile(r"^\[(\d+):(\d+)\]\s*(.*)$")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line.strip())
        if match and match.group(3).strip():
            out.append((int(match.group(1)) * 60 + int(match.group(2)), match.group(3).strip()))
    return out


def turn_metrics(raw_path: Path, final_path: Path | None = None, speaker_a=None):
    """Measure original conversational rhythm; estimate final speaking share by text alignment."""
    import numpy as np

    turns = parse_speaker_transcript(raw_path, speaker_a)
    if not turns:
        return {}
    duration = turns[-1][0]
    minutes = max(duration / 60, 1e-6)
    switches = sum(a[1] != b[1] for a, b in zip(turns, turns[1:]))
    durations = [max(b[0] - a[0], 0) for a, b in zip(turns, turns[1:])]
    chars = {"A": 0, "B": 0}
    for _, speaker, text in turns:
        chars[speaker] += len(normalize(text))
    total_chars = max(sum(chars.values()), 1)
    result = {
        "turns": len(turns),
        "turns_per_minute": round(len(turns) / minutes, 2),
        "switches_per_minute": round(switches / minutes, 2),
        "alternation_percent": round(switches / max(len(turns) - 1, 1) * 100, 1),
        "median_turn_seconds": round(float(np.median(durations)) if durations else 0, 2),
        "p90_turn_seconds": round(float(np.percentile(durations, 90)) if durations else 0, 2),
        "long_turns_45s_plus": sum(value >= 45 for value in durations),
        "short_response_percent": round(sum(len(normalize(text)) <= 12 for _, _, text in turns) / len(turns) * 100, 1),
        "speaker_a_char_share": round(chars["A"] / total_chars * 100, 1),
        "speaker_balance_score": round(min(chars.values()) / max(chars.values()) * 100 if max(chars.values()) else 0, 1),
    }
    if not final_path:
        return result

    final = parse_final_transcript(final_path)
    raw_text, ranges = "", []
    for _, _, text in turns:
        part = normalize(text)
        ranges.append((len(raw_text), len(raw_text) + len(part)))
        raw_text += part
    final_text = "".join(normalize(text) for _, text in final)
    matched = bytearray(len(raw_text))
    for block in SequenceMatcher(None, raw_text, final_text, autojunk=False).get_matching_blocks():
        if block.size:
            matched[block.a:block.a + block.size] = b"\1" * block.size
    coverage = [sum(matched[start:end]) / max(end - start, 1) for start, end in ranges]
    kept_chars = {"A": 0.0, "B": 0.0}
    for (_, speaker, text), value in zip(turns, coverage):
        kept_chars[speaker] += len(normalize(text)) * value
    kept_total = max(sum(kept_chars.values()), 1)
    result["estimated_final_speaker_a_char_share"] = round(kept_chars["A"] / kept_total * 100, 1)
    result["alignment_percent"] = round(sum(matched) / max(len(matched), 1) * 100, 1)
    return result


def chapter_metrics(chapters, final_duration):
    if not chapters:
        return {}
    starts = [parse_clock(item[0]) for item in chapters]
    durations = [max((starts[i + 1] if i + 1 < len(starts) else final_duration) - start, 0)
                 for i, start in enumerate(starts)]
    minutes = max(final_duration / 60, 1e-6)
    return {
        "chapter_count": len(starts),
        "chapters_per_10_min": round(len(starts) / minutes * 10, 2),
        "median_chapter_seconds": round(float(median(durations)), 1),
        "longest_chapter_seconds": max(durations),
        "durations": durations,
    }

