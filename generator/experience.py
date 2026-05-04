#!/usr/bin/env python3
"""
街コン/マッチングアプリ 体験談スレッド（隔日・奇数日 22:00 JST）

5ツイート構成のリプ連結スレッドを生成して投稿する。各ツイートが独立シーン/オチで、
X上で個別にインプレッションを確認できる構造。

使い方:
  python experience.py             # 生成 + 投稿
  python experience.py --dry-run   # 生成のみ（投稿しない）
  python experience.py --force     # 偶数日でも実行
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import tweepy

sys.path.insert(0, str(Path(__file__).parent))
from generate import MODEL, save_history, load_history, get_client as get_claude
from prompts import SYSTEM_PROMPT, EXPERIENCE_PROMPT

JST = ZoneInfo("Asia/Tokyo")
HISTORY_DIR = Path(__file__).parent.parent / "history"


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def generate_experience() -> list[str]:
    """5ツイート分の体験談を生成してリストで返す"""
    history = load_history("experience")
    prompt = EXPERIENCE_PROMPT.format(history=history)

    client = get_claude()
    message = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = ""
    for block in message.content:
        if block.type == "text":
            raw = block.text
            break

    save_history("experience", raw[:200])

    parts = re.split(r"【ツイート\d+】", raw)
    tweets = [p.strip() for p in parts if p.strip()]
    return tweets


def post_thread(client: tweepy.Client, tweets: list[str]) -> list[str]:
    """各ツイートをリプライで連結投稿。投稿IDのリストを返す"""
    posted_ids = []
    prev_id: str | None = None
    for i, text in enumerate(tweets, 1):
        kwargs: dict = {"text": text}
        if prev_id:
            kwargs["in_reply_to_tweet_id"] = str(prev_id)

        try:
            response = client.create_tweet(**kwargs)
        except tweepy.HTTPException as e:
            status = getattr(getattr(e, "response", None), "status_code", "?")
            if status == 402:
                print(
                    "\n!!! 402 Payment Required !!!\n"
                    "X API の pay-per-use クレジットが枯渇しています。\n"
                    "Developer Portal の Billing で残高を追加してください。\n"
                    f"詳細: {e}\n"
                )
            raise

        if response.data is None:
            raise RuntimeError(f"create_tweet returned no data; errors={response.errors}")

        tid = str(response.data["id"])
        posted_ids.append(tid)
        print(f"  [{i}/{len(tweets)}] 投稿完了 (ID: {tid})")
        prev_id = tid

        if i < len(tweets):
            time.sleep(2)

    return posted_ids


def main():
    parser = argparse.ArgumentParser(description="街コン/マッチングアプリ 体験談スレッド")
    parser.add_argument("--dry-run", action="store_true", help="投稿せず生成のみ")
    parser.add_argument("--force", action="store_true", help="偶数日でも実行")
    args = parser.parse_args()

    today = datetime.now(JST).day
    if not args.force and today % 2 == 0:
        print(f"今日は {today} 日（偶数）。隔日設定（奇数日のみ）によりスキップ。")
        return

    if not args.dry_run:
        for var in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]:
            if not os.environ.get(var):
                print(f"エラー: {var} が設定されていません")
                sys.exit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    print("=== 体験談スレッド生成 ===\n")
    tweets = generate_experience()

    if not tweets or len(tweets) < 3:
        print(f"生成結果が不正（{len(tweets)} tweets）。中断。")
        sys.exit(1)

    for i, t in enumerate(tweets, 1):
        print(f"\n--- ツイート{i} ({len(t)}字) ---")
        print(t)

    if args.dry_run:
        print("\n[dry-run] 投稿はスキップしました")
        return

    print("\n=== 投稿開始 ===")
    x_client = get_x_client()
    posted = post_thread(x_client, tweets)
    print(f"\n投稿完了！ ({len(posted)} tweets)")


if __name__ == "__main__":
    main()
