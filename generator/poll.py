#!/usr/bin/env python3
"""
Poll投票ツイートを生成して投稿（火・木・土 20:00 JST）

X v2 API の poll_options/poll_duration_minutes を使う。
エンゲージメント率が上がる → アルゴリズムが露出を伸ばす狙い。

使い方:
  python poll.py             # 生成 + 投稿
  python poll.py --dry-run   # 投稿しない
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import tweepy

HISTORY_FILE = Path(__file__).parent.parent / "history" / "polls.jsonl"
MAX_HISTORY = 100
POLL_DURATION_MINUTES = 1440  # 24h

sys.path.insert(0, str(Path(__file__).parent))
from generate import MODEL, get_client as get_claude
from prompts import SYSTEM_PROMPT, POLL_PROMPT


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_history(limit: int = 20) -> str:
    if not HISTORY_FILE.exists():
        return "(まだ履歴なし)"
    lines = HISTORY_FILE.read_text().strip().split("\n")[-limit:]
    out = []
    for line in lines:
        if line:
            d = json.loads(line)
            out.append(f"- {d['question'][:80]}")
    return "\n".join(out)


def save_history(question: str, options: list[str], tweet_id: str | None):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "question": question[:200],
        "options": options,
        "tweet_id": tweet_id,
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    lines = HISTORY_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        HISTORY_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def generate_poll() -> tuple[str, list[str]]:
    """質問文と4つの選択肢を生成"""
    history = load_history()
    client = get_claude()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": POLL_PROMPT.format(history=history)}],
    )
    raw = ""
    for block in msg.content:
        if block.type == "text":
            raw = block.text
            break

    # Parse 【質問】... 【選択肢】 1. ... 2. ... 3. ... 4. ...
    q_match = re.search(r"【質問】\s*(.+?)\s*【選択肢】", raw, re.DOTALL)
    opts_match = re.search(r"【選択肢】\s*(.+)$", raw, re.DOTALL)

    if not q_match or not opts_match:
        raise RuntimeError(f"Poll output parse failed:\n{raw}")

    question = q_match.group(1).strip()
    opts_block = opts_match.group(1).strip()

    options = []
    for line in opts_block.split("\n"):
        line = line.strip()
        m = re.match(r"^\d+[.\.\)）]\s*(.+)$", line)
        if m:
            opt = m.group(1).strip()
            if opt:
                options.append(opt[:25])  # X仕様: 25字上限

    if len(options) != 4:
        raise RuntimeError(f"Expected 4 options, got {len(options)}:\n{options}")

    return question, options


def post_poll(client: tweepy.Client, question: str, options: list[str]) -> str:
    try:
        response = client.create_tweet(
            text=question,
            poll_options=options,
            poll_duration_minutes=POLL_DURATION_MINUTES,
        )
    except tweepy.HTTPException as e:
        status = getattr(getattr(e, "response", None), "status_code", "?")
        if status == 402:
            print("\n!!! 402 Payment Required（クレジット切れ）!!!")
        raise
    return str(response.data["id"])


def main():
    parser = argparse.ArgumentParser(description="Poll投票ツイート")
    parser.add_argument("--dry-run", action="store_true", help="投稿しない")
    args = parser.parse_args()

    if not args.dry_run:
        for var in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]:
            if not os.environ.get(var):
                print(f"エラー: {var} が設定されていません")
                sys.exit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    print("=== Poll生成 ===\n")
    question, options = generate_poll()

    print(f"【質問】({len(question)}字)")
    print(question)
    print(f"\n【選択肢】")
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o} ({len(o)}字)")

    if args.dry_run:
        print("\n[dry-run] 投稿スキップ")
        save_history(question, options, None)
        return

    print("\n🚀 投稿中...")
    x_client = get_x_client()
    tid = post_poll(x_client, question, options)
    print(f"  完了 (ID: {tid})")
    save_history(question, options, tid)


if __name__ == "__main__":
    main()
