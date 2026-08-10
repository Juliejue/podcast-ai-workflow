import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
DEMO = ROOT / "demo"
sys.path.insert(0, str(TOOLS))

import compare_edits  # noqa: E402
import promo_materials  # noqa: E402
import analysis_metrics  # noqa: E402


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_path = DEMO / "匿名示例_转写_带时间戳_原始录音.txt"
        cls.final_path = DEMO / "匿名示例_转写_带时间戳.txt"
        cls.raw = compare_edits.读转写(cls.raw_path)
        cls.final = compare_edits.读转写(cls.final_path)

    def test_full_text_alignment_finds_real_deletions(self):
        keep, coverage, exact_ratio = compare_edits.找出被删的(self.raw, self.final)
        segments = compare_edits.并成片段(self.raw, keep, coverage)

        self.assertGreater(exact_ratio, 0.55)
        self.assertLess(exact_ratio, 0.90)
        deleted = "".join(segment["文本"] for segment in segments)
        self.assertIn("回声", deleted)
        self.assertIn("买咖啡", deleted)
        self.assertIn("跟前面重复", deleted)

    def test_promo_spans_are_contiguous_final_transcript_text(self):
        sentences, _ = promo_materials.读转写(self.final_path)
        timestamp_to_index = {seconds: i for i, (seconds, _) in enumerate(sentences)}
        clips = promo_materials.挑切片(sentences, sentences[-1][0])

        self.assertGreaterEqual(len(clips), 2)
        for clip in clips:
            self.assertIn(clip["起"], timestamp_to_index)
            self.assertIn(clip["止"], timestamp_to_index)
            start = timestamp_to_index[clip["起"]]
            end = timestamp_to_index[clip["止"]]
            expected = "".join(text for _, text in sentences[start:end])
            self.assertEqual(clip["文本"], expected)

    def test_raw_only_material_cannot_enter_promo_candidates(self):
        sentences, _ = promo_materials.读转写(self.final_path)
        clips = promo_materials.挑切片(sentences, sentences[-1][0])
        promo_text = "".join(clip["文本"] for clip in clips)

        self.assertNotIn("回声", promo_text)
        self.assertNotIn("买咖啡", promo_text)
        self.assertNotIn("录完了吗", promo_text)

    def test_speaker_timestamp_export_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meeting.txt"
            path.write_text(
                "主播甲(00:00:03): 第一段内容。\n\n"
                "主播乙(01:02:04)：第二段内容。\n",
                encoding="utf-8",
            )
            parsed = compare_edits.读转写(path)

        self.assertEqual(parsed, [(3, "第一段内容。"), (3724, "第二段内容。")])

    def test_summary_like_source_is_rejected(self):
        summary = [
            (0, "第一章的长篇总结" * 20),
            (900, "第二章的长篇总结" * 20),
            (1800, "第三章的长篇总结" * 20),
            (2700, "第四章的长篇总结" * 20),
        ]
        issue = compare_edits.逐字稿质量问题(summary)
        self.assertIn("摘要", issue)

    def test_chapter_duration_metrics(self):
        metrics = analysis_metrics.chapter_metrics(
            [["00:00", "Opening"], ["02:00", "Story"], ["05:30", "Close"]],
            420,
        )
        self.assertEqual(metrics["chapter_count"], 3)
        self.assertEqual(metrics["durations"], [120, 210, 90])
        self.assertEqual(metrics["longest_chapter_seconds"], 210)

    def test_configured_speaker_a_is_stable_when_host_b_speaks_first(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.txt"
            final = Path(directory) / "final.txt"
            raw.write_text(
                "Host B(00:00:00): 先由另一位主播开场。\n"
                "Host A(00:00:10): 这里是主播A的完整观点。\n"
                "Host B(00:00:30): 我来追问一个问题。\n"
                "Host A(00:00:40): 主播A继续把故事讲完。\n",
                encoding="utf-8",
            )
            final.write_text(
                "[00:00] 先由另一位主播开场。\n"
                "[00:10] 这里是主播A的完整观点。\n"
                "[00:30] 我来追问一个问题。\n"
                "[00:40] 主播A继续把故事讲完。\n",
                encoding="utf-8",
            )
            metrics = analysis_metrics.turn_metrics(raw, final, "Host A")

        self.assertGreater(metrics["speaker_a_char_share"], 50)
        self.assertGreater(metrics["estimated_final_speaker_a_char_share"], 50)

    def test_committed_promo_outputs_do_not_reference_raw_only_content(self):
        published = (DEMO / "demo_ShowNotes素材.md").read_text(encoding="utf-8")
        published += (DEMO / "demo_切片候选.md").read_text(encoding="utf-8")
        self.assertNotIn("回声", published)
        self.assertNotIn("买咖啡", published)
        self.assertNotIn("录完了吗", published)


if __name__ == "__main__":
    unittest.main()
