#!/usr/bin/env python3
"""
金曜のINTJ反省会（毎週金曜 22:00 JST、4ツイートのスレッド）

シリーズ識別ハッシュタグ #金曜のINTJ反省会 をツイ1とツイ4に付ける。
週末入り口に「動けなかった瞬間TOP3」を自虐的に振り返るブランド投稿。
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import tweepy

HISTORY_FILE = Path(__file__).parent.parent / "history" / "friday_review.jsonl"
MAX_HISTORY = 100

sys.path.insert(0, str(Path(__file__).parent))
from generate import MODEL, get_client as get_claude
from prompts import SYSTEM_PROMPT, FRIDAY_REVIEW_PROMPT


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_history(limit: int = 8) -> str:
    if not HISTORY_FILE.exists():
        return "(まだ履歴なし)"
    lines = HISTORY_FILE.read_text().strip().split("\n")[-limit:]
    out = []
    for line in lines:
        if line:
            d = json.loads(line)
            out.append(f"- {d['date'][:10]}: {d['summary'][:120]}")
    return "\n".join(out)


def save(summary: str, posted_ids: list[str]):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {"date": datetime.now().isoformat(), "summary": summary[:300], "posted_ids": posted_ids}
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    lines = HISTORY_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        HISTORY_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def generate_review() -> list[str]:
    history = load_history()
    client = get_claude()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": FRIDAY_REVIEW_PROMPT.format(history=history)}],
    )
    raw = ""
    for block in msg.content:
        if block.type == "text":
            raw = block.text
            break
    parts = re.split(r"【ツイート\d+】", raw)
    return [p.strip() for p in parts if p.strip()]


def post_thread(client: tweepy.Client, tweets: list[str]) -> list[str]:
    posted = []
    prev_id = None
    for i, text in enumerate(tweets, 1):
        kwargs = {"text": text}
        if prev_id:
            kwargs["in_reply_to_tweet_id"] = str(prev_id)
        try:
            response = client.create_tweet(**kwargs)
        except tweepy.HTTPException as e:
            status = getattr(getattr(e, "response", None), "status_code", "?")
            if status == 402:
                print("\n!!! 402 Payment Required（クレジット切れ）!!!")
            raise
        prev_id = str(response.data["id"])
        posted.append(prev_id)
        print(f"  [{i}/{len(tweets)}] 投稿完了 (ID: {prev_id})")
        if i < len(tweets):
            time.sleep(2)
    return posted


def main():
    parser = argparse.ArgumentParser(description="金曜のINTJ反省会")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run:
        for var in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]:
            if not os.environ.get(var):
                print(f"エラー: {var} が設定されていません")
                sys.exit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    print("=== 金曜のINTJ反省会 ===\n")
    tweets = generate_review()

    if len(tweets) < 3:
        print(f"生成失敗 (got {len(tweets)} tweets)")
        sys.exit(1)

    for i, t in enumerate(tweets, 1):
        print(f"\n--- ツイ{i} ({len(t)}字) ---\n{t}")

    if args.dry_run:
        print("\n[dry-run] 投稿スキップ")
        return

    print("\n=== 投稿開始 ===")
    x_client = get_x_client()
    posted = post_thread(x_client, tweets)
    save(tweets[0], posted)
    print(f"\n完了: {len(posted)} tweets")


if __name__ == "__main__":
    main()
