#!/usr/bin/env python3
"""Check which Podcast AI Workflow capabilities are ready without changing the system."""

import argparse
import importlib.util
import platform
import sys


CAPABILITIES = {
    "core": (),
    "audio": ("av", "numpy"),
    "transcription": ("faster_whisper", "av", "numpy"),
}


def main():
    parser = argparse.ArgumentParser(description="只检查环境，不安装依赖、不下载模型")
    parser.add_argument(
        "--require",
        choices=CAPABILITIES,
        default="core",
        help="core=逐字稿对比/宣发；audio=声波指标；transcription=本地转写",
    )
    args = parser.parse_args()

    print(f"Python {platform.python_version()}｜{sys.executable}")
    python_ok = sys.version_info >= (3, 10)
    print("✅ Python 版本可用" if python_ok else "❌ 需要 Python 3.10+")

    missing = []
    for module in CAPABILITIES[args.require]:
        if importlib.util.find_spec(module):
            print(f"✅ {module}")
        else:
            missing.append(module)
            print(f"❌ 缺少 {module}")

    if args.require == "transcription":
        print("ℹ️  Whisper 模型会在第一次实际转写时下载；本检查不会联网。")
    if missing:
        print("\n先征得使用者同意，再安装 requirements.txt 中的依赖。")
    raise SystemExit(0 if python_ok and not missing else 1)


if __name__ == "__main__":
    main()
