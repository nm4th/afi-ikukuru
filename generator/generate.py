#!/usr/bin/env python3
"""
MBTI×恋愛ランキング ツイート自動生成スクリプト

使い方:
  # 1日分（7本・形式自動選択）を一括生成
  python generate.py daily

  # 形式指定で1本生成
  python generate.py single --theme "付き合ったら一途すぎる男のMBTI" --format tease
  python generate.py single --theme "サプライズが得意なタイプトップ5" --format straight
  python generate.py single --theme "共感力" --format tier
  python generate.py single --theme "INTJと相性がいいタイプ" --format compat
  python generate.py single --theme "LINE返信パターン全16タイプ" --format full16
  python generate.py single --theme "INTJが冷たいと言われる本当の理由" --format contrast
  python generate.py single --theme "16タイプを動物に例える" --format metaphor

  # INTJのつぶやき（23:00枠用）
  python generate.py mumble

  # テーマだけ7つ提案
  python generate.py themes

形式:
  tease    = 5位→1位は↓（リプで1位発表）※インプレッション最大化
  straight = 1位→5位（1ツイート完結）
  tier     = Tier表 S/A/B/C（全16タイプ分類）
  compat   = 相性ランキング（ペア or 焦点型、tease構造）
  full16   = 全16タイプ網羅（本ツイ8 + リプ8）— 自分のタイプ探し導線
  contrast = 対比型「誤解 vs 本当の理由」（焦点型1タイプ、1ツイ完結）
  metaphor = 比喩型「16タイプを○○に例える」（本ツイ8 + リプ8）

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
    RANKING_COMPAT_PROMPT,
    RANKING_FULL16_PROMPT,
    RANKING_CONTRAST_PROMPT,
    RANKING_METAPHOR_PROMPT,
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
    "compat": RANKING_COMPAT_PROMPT,
    "full16": RANKING_FULL16_PROMPT,
    "contrast": RANKING_CONTRAST_PROMPT,
    "metaphor": RANKING_METAPHOR_PROMPT,
}

# tease構造（本ツイート + リプライ）で出力するフォーマット
TEASE_LIKE_FORMATS = {"tease", "compat", "full16", "metaphor"}

FORMAT_LABELS = {
    "tease": "5→1位は↓",
    "straight": "1→5位",
    "tier": "Tier表",
    "compat": "相性5→1位は↓",
    "full16": "全16タイプ網羅",
    "contrast": "対比型",
    "metaphor": "比喩型",
}

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


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
    client = get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in message.content:
        if block.type == "text":
            return block.text
    return ""


def detect_format(line: str) -> str:
    """テーマ行のラベルから形式を推定"""
    if "全16タイプ網羅" in line or "網羅" in line:
        return "full16"
    if "比喩" in line:
        return "metaphor"
    if "対比" in line:
        return "contrast"
    if "相性" in line:
        return "compat"
    if "Tier" in line or "tier" in line:
        return "tier"
    if "1→5" in line or "1->5" in line:
        return "straight"
    if "5→1" in line or "5->1" in line or "1位は↓" in line:
        return "tease"
    return "tease"


def generate_themes() -> list[dict]:
    """テーマと形式のペアを7つ提案"""
    history = load_history("themes")
    prompt = DAILY_THEMES_PROMPT.format(history=history)
    result = generate(prompt)

    entries = []
    for line in result.strip().split("\n"):
        line = line.strip()
        if not line or not line[0].isdigit():
            continue

        fmt = detect_format(line)
        theme = re.sub(r"^\d+\.\s*\[.*?\]\s*", "", line).strip()
        entries.append({"theme": theme, "format": fmt})
        save_history("themes", f"[{fmt}] {theme}")

    return entries


def parse_tease(raw: str) -> dict:
    """tease形式の出力を本ツイートとリプライに分割"""
    parts = re.split(r"【リプライ】", raw, maxsplit=1)
    main_text = re.sub(r"^【本ツイート】\s*", "", parts[0]).strip()
    reply_text = parts[1].strip() if len(parts) > 1 else ""
    return {"main": main_text, "reply": reply_text}


def parse_single_tweet(raw: str) -> dict:
    """straight/tier/mumble形式の出力をパース"""
    text = re.sub(r"^【ツイート】\s*", "", raw).strip()
    return {"main": text, "reply": ""}


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


DAILY_SLOTS = [
    ("07:30", "7:30 朝"),
    ("12:15", "12:15 昼"),
    ("18:30", "18:30 夕"),
    ("19:30", "19:30 夜1"),
    ("20:30", "20:30 夜2"),
    ("21:30", "21:30 夜3"),
    ("23:00", "23:00 深夜"),
]


def cmd_daily(output_json: str | None = None):
    """1日分を一括生成"""
    n_slots = len(DAILY_SLOTS)
    print(f"=== テーマを{n_slots}つ生成中... ===\n")
    entries = generate_themes()

    if len(entries) < n_slots:
        print(f"テーマが{len(entries)}個しか取れませんでした（{n_slots}個必要）。再実行してください。")
        return

    tweets = []

    for i, ((slot, slot_label), entry) in enumerate(zip(DAILY_SLOTS, entries)):
        theme = entry["theme"]
        fmt = entry["format"]
        label = FORMAT_LABELS.get(fmt, fmt)

        print(f"\n{'='*60}")
        print(f"【{slot_label}】[{label}] {theme}")
        print('='*60 + "\n")

        raw = generate_ranking(theme, fmt)
        print(raw)

        if fmt in TEASE_LIKE_FORMATS:
            parsed = parse_tease(raw)
        else:
            parsed = parse_single_tweet(raw)

        tweets.append({
            "slot": slot,
            "theme": theme,
            "format": fmt,
            "main": parsed["main"],
            "reply": parsed["reply"],
        })

        if i == n_slots - 1:
            print(f"\n{'- '*30}")
            print("【代替: INTJのつぶやき】\n")
            mumble = generate_mumble()
            print(mumble)

    if output_json:
        Path(output_json).write_text(
            json.dumps(tweets, ensure_ascii=False, indent=2)
        )
        print(f"\nJSON出力: {output_json}")

    print(f"\n{'='*60}")
    print("生成完了！")


def cmd_single(theme: str, fmt: str):
    print(f"[{FORMAT_LABELS.get(fmt, fmt)}] {theme}\n")
    result = generate_ranking(theme, fmt)
    print(result)


def cmd_mumble():
    result = generate_mumble()
    print(result)


def cmd_themes():
    entries = generate_themes()
    print("今日のテーマ候補:\n")
    for i, entry in enumerate(entries, 1):
        label = FORMAT_LABELS.get(entry["format"], entry["format"])
        print(f"  {i}. [{label}] {entry['theme']}")


def main():
    parser = argparse.ArgumentParser(description="MBTI×恋愛ランキング ツイート生成")
    subparsers = parser.add_subparsers(dest="command")

    daily_parser = subparsers.add_parser("daily", help="1日分（7本）を一括生成")
    daily_parser.add_argument("--output-json", help="生成結果をJSONファイルに出力")
    subparsers.add_parser("themes", help="テーマだけ7つ提案")
    subparsers.add_parser("mumble", help="INTJのつぶやき1本")

    sp = subparsers.add_parser("single", help="テーマ・形式指定で1本生成")
    sp.add_argument("--theme", required=True, help="テーマ")
    sp.add_argument(
        "--format",
        choices=list(FORMAT_PROMPTS.keys()),
        default="tease",
        help="形式: tease / straight / tier / compat / full16 / contrast / metaphor",
    )

    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY 環境変数を設定してください")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    match args.command:
        case "daily":
            cmd_daily(output_json=args.output_json)
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
