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
