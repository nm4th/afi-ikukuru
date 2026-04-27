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

TARGET_ACCOUNT = "lovembti_analyz"

MAX_HISTORY = 500


def get_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_liked_tweet_ids() -> set[str]:
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

    lines = HISTORY_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        HISTORY_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def resolve_user_id(client: tweepy.Client, username: str) -> str:
    response = client.get_user(username=username, user_auth=True)
    return str(response.data.id)


def get_followers(client: tweepy.Client, target_user_id: str) -> list[dict]:
    if FOLLOWERS_CACHE.exists():
        data = json.loads(FOLLOWERS_CACHE.read_text())
        age_hours = (datetime.now() - datetime.fromisoformat(data["updated"])).total_seconds() / 3600
        if age_hours < 24:
            print(f"  フォロワーキャッシュ使用（{len(data['followers'])}人、{age_hours:.0f}時間前）")
            return data["followers"]

    print(f"  @{TARGET_ACCOUNT} のフォロワーリスト取得中...")
    followers = []
    try:
        response = client.get_users_followers(
            target_user_id,
            max_results=200,
            user_fields=["username"],
            user_auth=True,
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
    except (tweepy.Unauthorized, tweepy.Forbidden) as e:
        print(f"  フォロワー取得が拒否されました（pay-per-use 未契約 or billing 未設定の可能性）: {e}")
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
    followers: list[dict],
    count: int,
    liked_tweet_ids: set[str],
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
                exclude=["retweets", "replies"],
                user_auth=True,
            )
        except (tweepy.Forbidden, tweepy.TooManyRequests):
            continue
        except tweepy.Unauthorized as e:
            print(f"  ツイート取得が拒否されました（billing 未設定の可能性）: {e}")
            return liked

        if not response.data:
            continue

        tweet = response.data[0]
        tweet_id = str(tweet.id)

        if tweet_id in liked_tweet_ids:
            continue

        if dry_run:
            print(f"  [dry-run] ❤️ @{follower['username']}: {tweet.text[:80]}...")
        else:
            try:
                client.like(tweet.id)
                print(f"  ❤️ @{follower['username']}: {tweet.text[:80]}...")
                save_liked(tweet_id, follower["username"])
            except tweepy.Forbidden:
                continue
            except tweepy.TooManyRequests:
                print("  レート制限に達しました。終了します。")
                return liked

        liked_tweet_ids.add(tweet_id)
        liked += 1
        if liked < count:
            time.sleep(20)

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
    print(f"  操作アカウント: @{me.data.username}")

    try:
        target_user_id = resolve_user_id(client, TARGET_ACCOUNT)
    except (tweepy.Unauthorized, tweepy.Forbidden) as e:
        print(f"  対象アカウントの解決が拒否されました（pay-per-use billing 未設定の可能性）: {e}")
        print("  Developer Portal で従量課金を有効化し、上限キャップを設定してください。")
        return
    print(f"  対象アカウント: @{TARGET_ACCOUNT}")

    followers = get_followers(client, target_user_id)
    if not followers:
        print("  フォロワーがいません")
        return

    liked_tweet_ids = load_liked_tweet_ids()
    print(f"  いいね済みツイート: {len(liked_tweet_ids)}件\n")

    liked = like_followers_tweets(
        client, followers, args.count, liked_tweet_ids, args.dry_run,
    )

    print(f"\n  {liked}件いいねしました{'（dry-run）' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
