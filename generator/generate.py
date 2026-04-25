#!/usr/bin/env python3
"""
MBTI×恋愛ランキング ツイート自動生成スクリプト

使い方:
  # 1日分のテーマ提案 → ランキング5本を一括生成
  python generate.py daily

  # テーマ指定でランキング1本生成
  python generate.py single --theme "付き合ったら一途すぎる男のMBTI"

  # INTJのつぶやき（23:00枠用）を1本生成
  python generate.py mumble

  # テーマだけ5つ提案（生成はしない）
  python generate.py themes

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
    RANKING_PROMPT,
    DAILY_THEMES_PROMPT,
    INTJ_MUMBLE_PROMPT,
)

HISTORY_DIR = Path(__file__).parent.parent / "history"
MODEL = "claude-sonnet-4-6"


def load_history(category: str, limit: int = 30) -> str:
    history_file = HISTORY_DIR / f"{category}.jsonl"
    if not history_file.exists():
        return "(まだ履歴なし)"

    lines = history_file.read_text().strip().split("\n")
    recent = lines[-limit:]
    entries = []
    for line in recent:
        data = json.loads(line)
        entries.append(f"- {data['text'][:100]}")
    return "\n".join(entries)


def save_history(category: str, text: str):
    HISTORY_DIR.mkdir(exist_ok=True)
    history_file = HISTORY_DIR / f"{category}.jsonl"
    entry = {"date": datetime.now().isoformat(), "text": text}
    with open(history_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def generate(prompt: str, max_tokens: int = 1024) -> str:
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def generate_themes() -> list[str]:
    """今日のテーマを5つ提案"""
    history = load_history("themes")
    prompt = DAILY_THEMES_PROMPT.format(history=history)
    result = generate(prompt)

    themes = []
    for line in result.strip().split("\n"):
        line = line.strip()
        if line and line[0].isdigit():
            theme = line.lstrip("0123456789.、．) ").strip()
            themes.append(theme)

    for theme in themes:
        save_history("themes", theme)

    return themes


def generate_ranking(theme: str) -> str:
    """テーマ指定でランキング1本生成"""
    history = load_history("rankings")
    prompt = RANKING_PROMPT.format(theme=theme, history=history)
    result = generate(prompt, max_tokens=1500)
    save_history("rankings", f"{theme}: {result[:80]}")
    return result


def generate_mumble() -> str:
    """INTJのつぶやきを1本生成"""
    history = load_history("mumble")
    result = generate(INTJ_MUMBLE_PROMPT.format(history=history))
    save_history("mumble", result)
    return result


def cmd_daily():
    """1日分のランキングを一括生成"""
    print("=== テーマを5つ生成中... ===\n")
    themes = generate_themes()

    if len(themes) < 5:
        print(f"テーマが{len(themes)}個しか取れませんでした。再実行してください。")
        return

    slots = ["7:30 朝", "12:15 昼（バズ狙い）", "18:30 夕", "21:30 夜（バズ狙い）", "23:00 深夜"]

    for i, (slot, theme) in enumerate(zip(slots, themes)):
        print(f"\n{'='*50}")
        print(f"【{slot}】テーマ: {theme}")
        print('='*50)

        if i == 4:
            # 23:00枠はランキングorつぶやきを選択
            print("\n--- ランキング ---")
            result = generate_ranking(theme)
            print(result)
            print("\n--- または、INTJのつぶやき ---")
            mumble = generate_mumble()
            print(mumble)
        else:
            result = generate_ranking(theme)
            print(result)

    print(f"\n{'='*50}")
    print("生成完了！各ツイートを予約投稿に設定してください。")
    print("本ツイートを投稿 → 1位のリプライを投稿 の順番で。")


def cmd_single(theme: str):
    """テーマ指定でランキング1本"""
    print(f"テーマ: {theme}\n")
    result = generate_ranking(theme)
    print(result)


def cmd_mumble():
    """INTJのつぶやき1本"""
    result = generate_mumble()
    print(result)


def cmd_themes():
    """テーマだけ5つ提案"""
    themes = generate_themes()
    print("今日のテーマ候補:\n")
    for i, theme in enumerate(themes, 1):
        print(f"  {i}. {theme}")


def main():
    parser = argparse.ArgumentParser(description="MBTI×恋愛ランキング ツイート生成")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("daily", help="1日分（5本）を一括生成")
    subparsers.add_parser("themes", help="テーマだけ5つ提案")
    subparsers.add_parser("mumble", help="INTJのつぶやきを1本生成")

    single_parser = subparsers.add_parser("single", help="テーマ指定でランキング1本")
    single_parser.add_argument("--theme", required=True, help="ランキングのテーマ")

    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY 環境変数を設定してください")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    if args.command == "daily":
        cmd_daily()
    elif args.command == "single":
        cmd_single(args.theme)
    elif args.command == "mumble":
        cmd_mumble()
    elif args.command == "themes":
        cmd_themes()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
