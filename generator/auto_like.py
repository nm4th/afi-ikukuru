#!/usr/bin/env python3
"""
フォロワーのツイートにいいねするスクリプト

1時間に6件のペースでフォロワーの最新ツイートにいいねする。

使い方:
  python auto_like.py              # 6件いいね
  python auto_like.py --count 3    # 3件いいね
  python auto_like.py --dry-run    # いいねせず確認だけ
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import tweepy

HISTORY_FILE = Path(__file__).parent.parent / "history" / "liked.jsonl"
FOLLOWERS_CACHE = Path(__file__).parent.parent / "history" / "followers.json"

MAX_HISTORY = 500


def get_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_liked_ids() -> set[str]:
    if not HISTORY_FILE.exists():
        return set()
    ids = set()
    for line in HISTORY_FILE.read_text().strip().split("\n"):
        if line:
            data = json.loads(line)
            ids.add(data["tweet_id"])
    return ids


def save_liked(tweet_id: str, user_name: str):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "tweet_id": tweet_id,
        "user": user_name,
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    trim_history()


def trim_history():
    if not HISTORY_FILE.exists():
        return
    lines = HISTORY_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        HISTORY_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def get_followers(client: tweepy.Client, user_id: str) -> list[dict]:
    cache_valid = False
    if FOLLOWERS_CACHE.exists():
        data = json.loads(FOLLOWERS_CACHE.read_text())
        age_hours = (datetime.now() - datetime.fromisoformat(data["updated"])).total_seconds() / 3600
        if age_hours < 24:
            cache_valid = True
            print(f"  フォロワーキャッシュ使用（{len(data['followers'])}人、{age_hours:.0f}時間前）")
            return data["followers"]

    if not cache_valid:
        print("  フォロワーリスト取得中...")
        followers = []
        try:
            response = client.get_users_followers(
                user_id,
                max_results=200,
                user_fields=["username"],
            )
            if response.data:
                for user in response.data:
                    followers.append({
                        "id": str(user.id),
                        "username": user.username,
                    })
        except tweepy.TooManyRequests:
            print("  レート制限に達しました")
            if FOLLOWERS_CACHE.exists():
                return json.loads(FOLLOWERS_CACHE.read_text())["followers"]
            return []

        FOLLOWERS_CACHE.parent.mkdir(exist_ok=True)
        FOLLOWERS_CACHE.write_text(json.dumps({
            "updated": datetime.now().isoformat(),
            "followers": followers,
        }, ensure_ascii=False, indent=2))
        print(f"  {len(followers)}人のフォロワーを取得")
        return followers


def like_followers_tweets(
    client: tweepy.Client,
    user_id: str,
    followers: list[dict],
    count: int,
    liked_ids: set[str],
    dry_run: bool = False,
) -> int:
    random.shuffle(followers)
    liked = 0

    for follower in followers:
        if liked >= count:
            break

        try:
            response = client.get_users_tweets(
                follower["id"],
                max_results=5,
                tweet_fields=["public_metrics"],
                exclude=["retweets", "replies"],
            )
        except (tweepy.Forbidden, tweepy.TooManyRequests):
            continue

        if not response.data:
            continue

        for tweet in response.data:
            tweet_id = str(tweet.id)
            if tweet_id in liked_ids:
                continue

            if dry_run:
                print(f"  [dry-run] ❤️ @{follower['username']}: {tweet.text[:80]}...")
            else:
                try:
                    client.like(user_id, tweet.id)
                    print(f"  ❤️ @{follower['username']}: {tweet.text[:80]}...")
                    save_liked(tweet_id, follower["username"])
                except tweepy.Forbidden:
                    continue
                except tweepy.TooManyRequests:
                    print("  レート制限に達しました。終了します。")
                    return liked

            liked_ids.add(tweet_id)
            liked += 1
            time.sleep(2)
            break

    return liked


def main():
    parser = argparse.ArgumentParser(description="フォロワーへの自動いいね")
    parser.add_argument("--count", type=int, default=6, help="いいね数（デフォルト: 6）")
    parser.add_argument("--dry-run", action="store_true", help="いいねせず確認だけ")
    args = parser.parse_args()

    for var in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]:
        if not os.environ.get(var):
            print(f"エラー: {var} が設定されていません")
            sys.exit(1)

    client = get_client()

    print("=== フォロワーいいね ===\n")

    me = client.get_me()
    user_id = str(me.data.id)
    print(f"  アカウント: @{me.data.username}")

    followers = get_followers(client, user_id)
    if not followers:
        print("  フォロワーがいません")
        return

    liked_ids = load_liked_ids()

    liked = like_followers_tweets(
        client, user_id, followers, args.count, liked_ids, args.dry_run,
    )

    print(f"\n  {liked}件いいねしました{'（dry-run）' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
