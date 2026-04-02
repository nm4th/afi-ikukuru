#!/usr/bin/env python3
"""
INTJ×Pappy ツイート自動生成スクリプト

使い方:
  # 1日分のツイート（5本）を生成
  python generate.py daily

  # 奮闘記シリーズ（7話）を生成
  python generate.py series --theme "初めてのデートで失敗する話"

  # 特定カテゴリだけ生成
  python generate.py single --category aruaru_morning
  python generate.py single --category aruaru_evening
  python generate.py single --category weapon
  python generate.py single --category reflection

環境変数:
  ANTHROPIC_API_KEY: Claude APIキー
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic

from prompts import (
    SYSTEM_PROMPT,
    ARUARU_MORNING_PROMPT,
    ARUARU_EVENING_PROMPT,
    WEAPON_PROMPT,
    REFLECTION_PROMPT,
    SERIES_PROMPT,
)

HISTORY_DIR = Path(__file__).parent.parent / "history"
MODEL = "claude-sonnet-4-6"


def load_history(category: str, limit: int = 20) -> str:
    """過去の投稿履歴を読み込む"""
    history_file = HISTORY_DIR / f"{category}.jsonl"
    if not history_file.exists():
        return "(まだ投稿履歴なし)"

    lines = history_file.read_text().strip().split("\n")
    recent = lines[-limit:]
    entries = []
    for line in recent:
        data = json.loads(line)
        entries.append(f"- {data['text'][:80]}...")
    return "\n".join(entries)


def save_history(category: str, text: str):
    """投稿履歴を保存する"""
    HISTORY_DIR.mkdir(exist_ok=True)
    history_file = HISTORY_DIR / f"{category}.jsonl"
    entry = {"date": datetime.now().isoformat(), "text": text}
    with open(history_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def generate(prompt: str) -> str:
    """Claude APIでツイートを生成する"""
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def generate_single(category: str) -> str:
    """指定カテゴリのツイートを1本生成"""
    prompts = {
        "aruaru_morning": ARUARU_MORNING_PROMPT,
        "aruaru_evening": ARUARU_EVENING_PROMPT,
        "weapon": WEAPON_PROMPT,
        "reflection": REFLECTION_PROMPT,
    }
    if category not in prompts:
        print(f"エラー: カテゴリは {list(prompts.keys())} から選んでください")
        sys.exit(1)

    history = load_history(category)
    prompt = prompts[category].format(history=history)
    result = generate(prompt)
    save_history(category, result)
    return result


def generate_daily() -> dict:
    """1日分のツイート（5本）を一括生成"""
    print("=== 1日分のツイートを生成中 ===\n")
    results = {}

    categories = [
        ("aruaru_morning", "7:30 朝（偏りあるある）"),
        ("aruaru_evening", "18:30 夕（偏りあるある・仕事系）"),
        ("weapon", "21:30 夜①（武器になった話＋誘導）"),
        ("reflection", "23:00 夜②（気づき・内省）"),
    ]

    for category, label in categories:
        print(f"--- {label} ---")
        result = generate_single(category)
        results[category] = result
        print(result)
        print()

    return results


def generate_series(theme: str) -> str:
    """奮闘記シリーズ（7話）を生成"""
    print(f"=== 奮闘記シリーズを生成中（テーマ: {theme}） ===\n")

    history = load_history("series")
    prompt = SERIES_PROMPT.format(theme=theme, history=history)
    result = generate(prompt)
    save_history("series", f"テーマ: {theme} | {result[:100]}")

    # 各話を個別にも保存
    HISTORY_DIR.mkdir(exist_ok=True)
    series_dir = HISTORY_DIR / "series_episodes"
    series_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    (series_dir / f"{date_str}.txt").write_text(result)

    print(result)
    return result


def main():
    parser = argparse.ArgumentParser(description="INTJ×Pappy ツイート自動生成")
    subparsers = parser.add_subparsers(dest="command")

    # daily: 1日分生成
    subparsers.add_parser("daily", help="1日分のツイート（4本＋奮闘記は別管理）を生成")

    # series: 奮闘記生成
    series_parser = subparsers.add_parser("series", help="奮闘記シリーズ（7話）を生成")
    series_parser.add_argument("--theme", required=True, help="今週のテーマ")

    # single: 1本だけ生成
    single_parser = subparsers.add_parser("single", help="指定カテゴリのツイートを1本生成")
    single_parser.add_argument(
        "--category",
        required=True,
        choices=["aruaru_morning", "aruaru_evening", "weapon", "reflection"],
        help="カテゴリ",
    )

    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY 環境変数を設定してください")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    if args.command == "daily":
        results = generate_daily()
        print("\n=== 昼の奮闘記は別途 series コマンドで週次生成してください ===")
        print("  python generate.py series --theme '今週のテーマ'")

    elif args.command == "series":
        generate_series(args.theme)

    elif args.command == "single":
        result = generate_single(args.category)
        print(result)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
