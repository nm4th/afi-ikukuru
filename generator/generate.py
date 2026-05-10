#!/usr/bin/env python3
"""
MBTI×恋愛ランキング ツイート自動生成スクリプト

使い方:
  # 1日分（10本・形式自動選択）を一括生成
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

  # テーマだけ10個提案
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
    RANKING_ARUARU_PROMPT,
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
    "aruaru": RANKING_ARUARU_PROMPT,
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
    "aruaru": "短文あるある",
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


def load_viral_references(limit: int = 2) -> str:
    """直近の viral_research.py 出力を文字列で返す（DAILY_THEMES_PROMPT 用）"""
    path = HISTORY_DIR / "viral_references.jsonl"
    if not path.exists():
        return "(まだ研究履歴なし。普段の方針で生成してOK)"
    lines = path.read_text().strip().split("\n")
    if not lines:
        return "(まだ研究履歴なし。普段の方針で生成してOK)"
    recent = lines[-limit:]
    out = []
    for line in recent:
        d = json.loads(line)
        out.append(f"[{d['date'][:10]}]\n{d['analysis']}")
    return "\n\n".join(out)


def save_history(category: str, text: str):
    HISTORY_DIR.mkdir(exist_ok=True)
    history_file = HISTORY_DIR / f"{category}.jsonl"
    entry = {"date": datetime.now().isoformat(), "text": text}
    with open(history_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def claude_call_with_retry(
    prompt: str,
    system: str = SYSTEM_PROMPT,
    max_tokens: int = 1500,
    max_retries: int = 5,
) -> str:
    """Anthropic API 呼び出しを 429 RateLimitError に対するバックオフ付きで実行。

    レート制限（30K input tokens/分）に当たった時に指数バックオフで再試行。
    他の HTTP エラー（401/500等）は再試行せずに即raise。
    """
    import time
    client = get_client()
    last_err = None
    for attempt in range(max_retries):
        try:
            message = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            for block in message.content:
                if block.type == "text":
                    return block.text
            return ""
        except anthropic.RateLimitError as e:
            last_err = e
            wait = 30 * (attempt + 1)  # 30, 60, 90, 120, 150秒
            print(f"  ⏸  Anthropic rate limit hit (attempt {attempt+1}/{max_retries}), waiting {wait}s...")
            time.sleep(wait)
    # 全リトライ失敗
    raise RuntimeError(f"Anthropic rate limit persistent after {max_retries} retries: {last_err}")


def generate(prompt: str, max_tokens: int = 1500) -> str:
    """generate.py 内部用の薄いラッパ（後方互換）"""
    return claude_call_with_retry(prompt, system=SYSTEM_PROMPT, max_tokens=max_tokens)


def detect_format(line: str) -> str:
    """テーマ行から形式を推定。
    優先順位:
      (1) 角括弧内の英語キー（最も明示的、最強）
      (2) 角括弧内の日本語の特定的フォーマット名（全16タイプ網羅、比喩型 等）
      (3) テーマ本文中の強い内容キーワード（一覧/例えたら/本当の理由）
          → ラベルが「[ランキング5→1位は↓]」でも、内容で full16/metaphor/contrast に上書き
      (4) 汎用ラベル（tease / straight / tier）の検出
    """
    import re

    # (1) 角括弧内の英語キー
    bracket = re.search(r"\[([^\]]+)\]", line)
    if bracket:
        key = bracket.group(1).strip().lower()
        for fmt in ("full16", "contrast", "metaphor", "compat", "aruaru"):
            if fmt in key:
                return fmt

    # (2) 角括弧内の日本語の特定的フォーマット名
    if "全16タイプ網羅" in line or "網羅型" in line:
        return "full16"
    if "比喩型" in line:
        return "metaphor"
    if "対比型" in line:
        return "contrast"
    if "相性ランキング" in line:
        return "compat"
    if "Tier表" in line:
        return "tier"
    if "短文あるある" in line or "あるある" in line:
        return "aruaru"

    # (3) テーマ本文の強い内容キーワード（汎用ラベルを上書きする）
    if "全16タイプ" in line or "16タイプ一覧" in line or "全タイプ" in line:
        return "full16"
    if re.search(r"例え(たら|ると|て|る)", line) or "に例える" in line:
        return "metaphor"
    if "本当の理由" in line:
        return "contrast"

    # (4) 汎用ラベルの検出
    if bracket:
        key = bracket.group(1).strip().lower()
        if "tier" in key:
            return "tier"
        if "straight" in key or "1→5" in key or "1->5" in key:
            return "straight"
        if "tease" in key or "5→1" in key or "5->1" in key or "1位は↓" in key:
            return "tease"
    if "1→5" in line or "1->5" in line:
        return "straight"
    if "5→1" in line or "5->1" in line or "1位は↓" in line:
        return "tease"

    return "tease"


def generate_themes() -> list[dict]:
    """テーマと形式のペアを10個提案"""
    history = load_history("themes")
    viral_context = load_viral_references()
    prompt = DAILY_THEMES_PROMPT.format(history=history, viral_context=viral_context)
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
    """tease/compat/full16/metaphor 形式の出力を本ツイートとリプライに分割。

    LLM が【リプライ】マーカーを省略するケースに備え、フォールバック分割も実装:
    - 「↓」で終わる行 + 空行 + 後続コンテンツ → 後続を reply として救う
    - 後続コンテンツが「N位 」「XXXX：」のような構造を持つ場合に限り採用
    """
    # 1) 明示マーカーで分割（変種も許容）
    marker_re = re.compile(r"【\s*(?:リプライ|リプ|返信|Reply|reply)\s*】")
    parts = marker_re.split(raw, maxsplit=1)
    if len(parts) > 1:
        main_text = re.sub(r"^【\s*本ツイート\s*】\s*", "", parts[0]).strip()
        return {"main": main_text, "reply": parts[1].strip()}

    # 2) フォールバック: 「↓」の後に明示マーカー無しで続いているケース
    text = re.sub(r"^【\s*本ツイート\s*】\s*", "", raw).strip()
    fallback = re.search(
        # main: 文頭 から 末尾の「↓」を含む行末まで（greedy）
        # その後: 改行 + 空行 + 任意の '---' 区切り + 空行
        # reply: 「N位 」または「XXXX：」で始まるブロック
        r"(?P<main>.+↓)[ \t]*\n[ \t]*\n+(?:[-]+[ \t]*\n+)?(?P<reply>(?:[1-9]位 |[A-Z]{4}[：:＝]).+)\Z",
        text,
        re.DOTALL,
    )
    if fallback:
        # 正規表現が「↓ + 空行 + ランキング/MBTI:」を要求してるので、
        # マッチした時点で構造的に reply とみなして良い。
        return {
            "main": fallback.group("main").strip(),
            "reply": fallback.group("reply").strip(),
        }

    # 3) リプライなし（main 1ツイ完結扱い）
    if "↓" in text:
        # 「↓」があるのに reply が拾えなかった場合は警告ログ
        print(f"  ⚠️ parse_tease: 「↓」検出したがリプライ抽出失敗。本ツイのみ投稿。raw末尾: ...{text[-200:]!r}")
    return {"main": text, "reply": ""}


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


# テーマ生成対象のスロット（12個）。mumble と異なり generate_themes() が
# テーマ + 形式キーを出すスロット。時間順だが、02:00 は次の日の早朝に投稿。
DAILY_SLOTS = [
    ("02:00", "2:00 深夜 (aruaru)"),
    ("11:00", "11:00 午前 (aruaru)"),
    ("12:15", "12:15 昼"),
    ("14:00", "14:00 午後 (aruaru)"),
    ("15:00", "15:00 午後"),
    ("17:00", "17:00 夕方 (aruaru)"),
    ("18:30", "18:30 夕"),
    ("19:30", "19:30 夜1"),
    ("20:30", "20:30 夜2"),
    ("21:30", "21:30 夜3"),
    ("22:30", "22:30 夜4"),
    ("23:00", "23:00 深夜"),
]

# Mumble スロット（テーマ不要、generate_mumble() で別途生成）
MUMBLE_SLOT = ("23:30", "23:30 INTJ深夜つぶやき")


def cmd_daily(output_json: str | None = None):
    """1日分を一括生成"""
    n_slots = len(DAILY_SLOTS)
    print(f"=== テーマを{n_slots}つ生成中... ===\n")
    entries = generate_themes()

    if len(entries) < n_slots:
        print(f"テーマが{len(entries)}個しか取れませんでした（{n_slots}個必要）。再実行してください。")
        return

    tweets = []

    import time
    for i, ((slot, slot_label), entry) in enumerate(zip(DAILY_SLOTS, entries)):
        theme = entry["theme"]
        fmt = entry["format"]
        label = FORMAT_LABELS.get(fmt, fmt)

        print(f"\n{'='*60}")
        print(f"【{slot_label}】[{label}] {theme}")
        print('='*60 + "\n")

        # 連続生成での Anthropic rate limit (30K input tokens/分) を回避するため、
        # 各生成の間に短い sleep を挟む。13スロット × 平均3K input ≈ 40K tokens/min
        # を回避できる。
        if i > 0:
            time.sleep(6)

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

    # mumble スロット（23:30 INTJ深夜つぶやき）を生成して tweets に追加
    print(f"\n{'='*60}")
    print(f"【{MUMBLE_SLOT[1]}】[mumble] 深夜のつぶやき")
    print('='*60 + "\n")
    time.sleep(6)
    mumble_text = generate_mumble().strip()
    print(mumble_text)
    tweets.append({
        "slot": MUMBLE_SLOT[0],
        "theme": "深夜のつぶやき（中の人独白）",
        "format": "mumble",
        "main": mumble_text,
        "reply": "",
    })

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

    daily_parser = subparsers.add_parser("daily", help="1日分（10本）を一括生成")
    daily_parser.add_argument("--output-json", help="生成結果をJSONファイルに出力")
    subparsers.add_parser("themes", help="テーマだけ10個提案")
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
