#!/usr/bin/env python3
"""
MBTI×恋愛ランキング ツイート自動生成スクリプト

使い方:
  # 1日分（5本・形式自動選択）を一括生成
  python generate.py daily

  # 形式指定でランキング1本生成
  python generate.py single --theme "付き合ったら一途すぎる男のMBTI" --format tease
  python generate.py single --theme "サプライズが得意なタイプトップ5" --format straight
  python generate.py single --theme "共感力" --format tier

  # INTJのつぶやき（23:00枠用）
  python generate.py mumble

  # テーマだけ5つ提案
  python generate.py themes

形式:
  tease    = 5位→1位は↓（リプで1位発表）※インプレッション最大化
  straight = 1位→5位（1ツイート完結）
  tier     = Tier表 S/A/B/C（全16タイプ分類）

環境変数:
  ANTHROPIC_API_KEY: Claude APIキー
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import anthropic

from prompts import (
    SYSTEM_PROMPT,
    RANKING_TEASE_PROMPT,
    RANKING_STRAIGHT_PROMPT,
    TIER_PROMPT,
    DAILY_THEMES_PROMPT,
    INTJ_MUMBLE_PROMPT,
)

HISTORY_DIR = Path(__file__).parent.parent / "history"
MODEL = "claude-sonnet-4-6"

FORMAT_PROMPTS = {
    "tease": RANKING_TEASE_PROMPT,
    "straight": RANKING_STRAIGHT_PROMPT,
    "tier": TIER_PROMPT,
}


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


def generate(prompt: str, max_tokens: int = 1500) -> str:
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def generate_themes() -> list[dict]:
    """テーマと形式のペアを5つ提案"""
    history = load_history("themes")
    prompt = DAILY_THEMES_PROMPT.format(history=history)
    result = generate(prompt)

    entries = []
    for line in result.strip().split("\n"):
        line = line.strip()
        if not line or not line[0].isdigit():
            continue

        fmt = "tease"
        if "1→5" in line or "1->5" in line:
            fmt = "straight"
        elif "Tier" in line or "tier" in line:
            fmt = "tier"
        elif "5→1" in line or "5->1" in line or "1位は↓" in line:
            fmt = "tease"

        theme = re.sub(r"^\d+\.\s*\[.*?\]\s*", "", line).strip()
        entries.append({"theme": theme, "format": fmt})
        save_history("themes", f"[{fmt}] {theme}")

    return entries


def generate_ranking(theme: str, fmt: str = "tease") -> str:
    """形式指定でランキング/Tier表を生成"""
    prompt_template = FORMAT_PROMPTS.get(fmt, RANKING_TEASE_PROMPT)
    history = load_history("rankings")
    prompt = prompt_template.format(theme=theme, history=history)
    result = generate(prompt, max_tokens=2000)
    save_history("rankings", f"[{fmt}] {theme}: {result[:80]}")
    return result


def generate_mumble() -> str:
    history = load_history("mumble")
    result = generate(INTJ_MUMBLE_PROMPT.format(history=history))
    save_history("mumble", result)
    return result


def cmd_daily():
    """1日分を一括生成"""
    print("=== テーマを5つ生成中... ===\n")
    entries = generate_themes()

    if len(entries) < 5:
        print(f"テーマが{len(entries)}個しか取れませんでした。再実行してください。")
        return

    slots = ["7:30 朝", "12:15 昼", "18:30 夕", "21:30 夜", "23:00 深夜"]
    fmt_labels = {"tease": "5→1位は↓", "straight": "1→5位", "tier": "Tier表"}

    for i, (slot, entry) in enumerate(zip(slots, entries)):
        theme = entry["theme"]
        fmt = entry["format"]
        label = fmt_labels.get(fmt, fmt)

        print(f"\n{'='*60}")
        print(f"【{slot}】[{label}] {theme}")
        print('='*60 + "\n")

        result = generate_ranking(theme, fmt)
        print(result)

        # 23:00枠はつぶやきも候補として生成
        if i == 4:
            print(f"\n{'- '*30}")
            print("【代替: INTJのつぶやき】\n")
            mumble = generate_mumble()
            print(mumble)

    print(f"\n{'='*60}")
    print("生成完了！")
    print("「1位は↓」形式 → 本ツイート投稿後にリプライで1位を投稿")
    print("それ以外 → そのまま1ツイートとして投稿")


def cmd_single(theme: str, fmt: str):
    fmt_labels = {"tease": "5→1位は↓", "straight": "1→5位", "tier": "Tier表"}
    print(f"[{fmt_labels.get(fmt, fmt)}] {theme}\n")
    result = generate_ranking(theme, fmt)
    print(result)


def cmd_mumble():
    result = generate_mumble()
    print(result)


def cmd_themes():
    entries = generate_themes()
    fmt_labels = {"tease": "5→1位は↓", "straight": "1→5位", "tier": "Tier表"}
    print("今日のテーマ候補:\n")
    for i, entry in enumerate(entries, 1):
        label = fmt_labels.get(entry["format"], entry["format"])
        print(f"  {i}. [{label}] {entry['theme']}")


def main():
    parser = argparse.ArgumentParser(description="MBTI×恋愛ランキング ツイート生成")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("daily", help="1日分（5本）を一括生成")
    subparsers.add_parser("themes", help="テーマだけ5つ提案")
    subparsers.add_parser("mumble", help="INTJのつぶやき1本")

    sp = subparsers.add_parser("single", help="テーマ・形式指定で1本生成")
    sp.add_argument("--theme", required=True, help="テーマ")
    sp.add_argument(
        "--format",
        choices=["tease", "straight", "tier"],
        default="tease",
        help="形式: tease(5→1位は↓) / straight(1→5位) / tier(Tier表)",
    )

    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY 環境変数を設定してください")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    match args.command:
        case "daily":
            cmd_daily()
        case "single":
            cmd_single(args.theme, args.format)
        case "mumble":
            cmd_mumble()
        case "themes":
            cmd_themes()
        case _:
            parser.print_help()


if __name__ == "__main__":
    main()
