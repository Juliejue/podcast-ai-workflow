import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "podcast-ai-workflow"
SCRIPTS = SKILL / "scripts"
DEMO = SKILL / "assets" / "demo"


class InstalledSkillTest(unittest.TestCase):
    def run_script(self, script, *args, cwd):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), *map(str, args)],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_core_doctor_requires_no_optional_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_script("doctor.py", "--require", "core", cwd=directory)
        self.assertIn("Python 版本可用", result.stdout)

    def test_one_episode_and_promo_run_outside_install_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            episode = workspace / "episode"
            episode.mkdir()
            shutil.copy(DEMO / "匿名示例_转写_带时间戳.txt", episode)
            shutil.copy(DEMO / "匿名示例_转写_带时间戳_原始录音.txt", episode)

            self.run_script("compare_edits.py", episode, cwd=workspace)
            self.run_script(
                "promo_materials.py",
                episode,
                "--成片稿",
                "匿名示例_转写_带时间戳.txt",
                cwd=workspace,
            )

            comparison = (episode / "episode_剪辑对比.md").read_text(encoding="utf-8")
            published = (episode / "episode_ShowNotes素材.md").read_text(encoding="utf-8")
            published += (episode / "episode_切片候选.md").read_text(encoding="utf-8")

        self.assertIn("疑似删除候选", comparison)
        self.assertNotIn("买咖啡", published)
        self.assertNotIn("录完了吗", published)

    def test_editing_guardrail_respects_declared_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            episode = workspace / "episode"
            episode.mkdir()
            for name in (
                "匿名示例_转写_带时间戳.txt",
                "匿名示例_转写_带时间戳_原始录音.txt",
                "editing_intent.json",
            ):
                shutil.copy(DEMO / name, episode)

            self.run_script(
                "editing_guardrails.py",
                episode,
                "--原始稿",
                "匿名示例_转写_带时间戳_原始录音.txt",
                "--粗剪稿",
                "匿名示例_转写_带时间戳.txt",
                "--创作意图",
                "editing_intent.json",
                cwd=workspace,
            )
            card = (episode / "episode_剪辑护栏卡.md").read_text(encoding="utf-8")

        self.assertIn("绿色｜低编辑风险", card)
        self.assertIn("黄色｜需结合上下文", card)
        self.assertIn("红色｜受保护", card)
        self.assertIn("保护词：买咖啡", card)
        protected_row = next(line for line in card.splitlines() if "红色｜受保护" in line)
        self.assertNotIn("□删除", protected_row)
        self.assertIn("考虑缩短的理由", card)
        self.assertIn("考虑保留的理由", card)
        self.assertIn("□保留", card)

    def test_show_notes_prompt_loads_style_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            episode = workspace / "episode"
            episode.mkdir()
            shutil.copy(DEMO / "匿名示例_转写_带时间戳.txt", episode)

            self.run_script(
                "promo_materials.py",
                episode,
                "--成片稿",
                "匿名示例_转写_带时间戳.txt",
                cwd=workspace,
            )
            source = (episode / "episode_ShowNotes素材.md").read_text(encoding="utf-8")

        self.assertIn("Show Notes 风格指南", source)
        self.assertIn("Do not use em-dash punctuation", source)
        self.assertIn("同名小红书账号", source)
        self.assertIn("validate_show_notes.py", source)

    def test_show_notes_validator_accepts_demo_and_rejects_hard_rule_violations(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            good = workspace / "good.md"
            bad = workspace / "bad.md"
            final = workspace / "final.txt"
            shutil.copy(DEMO / "demo_ShowNotes成稿.md", good)
            shutil.copy(DEMO / "匿名示例_转写_带时间戳.txt", final)
            bad.write_text(
                "# 标题\n\n这不是拖延，而是准备。——需要再想。\n\n"
                "✨ 高光内容\n\n⏱ 时间轴\n\n- 09:59 不存在的时间\n\n"
                "💬 本期互动\n\n🎙 关于《稳稳接住》\n\n"
                "欢迎关注同名小红书账号「稳稳接住」。\n",
                encoding="utf-8",
            )

            good_result = self.run_script(
                "validate_show_notes.py", good, "--成片稿", final, cwd=workspace
            )
            bad_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "validate_show_notes.py"),
                    str(bad),
                    "--成片稿",
                    str(final),
                ],
                cwd=workspace,
                text=True,
                capture_output=True,
            )

        self.assertIn("校验通过", good_result.stdout)
        self.assertNotEqual(bad_result.returncode, 0)
        self.assertIn("破折号", bad_result.stdout)
        self.assertIn("禁用对比句式", bad_result.stdout)
        self.assertIn("不在成片稿中", bad_result.stdout)

    def test_cross_episode_output_is_written_to_user_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            episodes = []
            for name in ("ep_low", "ep_mid", "ep_high"):
                target = workspace / name
                shutil.copytree(DEMO / name, target)
                episodes.append(target)
            performance = workspace / "performance_data.json"
            shutil.copy(DEMO / "performance_data.json", performance)
            report = workspace / "review.md"

            self.run_script(
                "compare_edits.py",
                *episodes,
                "--汇总",
                "--表现数据",
                performance,
                "--输出",
                report,
                cwd=workspace,
            )

            content = report.read_text(encoding="utf-8")

        self.assertIn("指导后续录制与剪辑", content)
        self.assertIn("单次相关性不等于因果", content)

    def test_installed_scripts_do_not_bind_to_repository_parent(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in SCRIPTS.glob("*.py")
        )
        self.assertNotIn("PROJECT_DIR", combined)
        self.assertNotIn("/Users/", combined)


if __name__ == "__main__":
    unittest.main()
