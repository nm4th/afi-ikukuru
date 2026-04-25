#!/usr/bin/env python3
"""
X（Twitter）自動投稿スクリプト

生成済みのJSONファイルを読み込み、指定スロットのツイートをXに投稿する。

使い方:
  # 全スロットを一括投稿
  python post.py tweets.json

  # 特定スロットだけ投稿
  python post.py tweets.json --slot 07:30

環境変数:
  X_API_KEY: X API Key
  X_API_SECRET: X API Key Secret
  X_ACCESS_TOKEN: X Access Token
  X_ACCESS_TOKEN_SECRET: X Access Token Secret
"""

import argparse
import json
import sys
import time

import tweepy


def get_client() -> tweepy.Client:
    import os
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def post_tweet(client: tweepy.Client, text: str, reply_to: str | None = None) -> str:
    """ツイートを投稿し、ツイートIDを返す"""
    kwargs = {"text": text}
    if reply_to:
        kwargs["in_reply_to_tweet_id"] = reply_to

    try:
        response = client.create_tweet(**kwargs)
        tweet_id = response.data["id"]
        return tweet_id
    except tweepy.Forbidden as e:
        print(f"  403エラー詳細: {e.response.text}")
        print(f"  レスポンスヘッダ: {dict(e.response.headers)}")
        raise


def post_from_json(json_path: str, slot_filter: str | None = None):
    """JSONファイルからツイートを投稿"""
    with open(json_path) as f:
        tweets = json.load(f)

    if slot_filter:
        tweets = [t for t in tweets if t["slot"] == slot_filter]

    if not tweets:
        print("投稿するツイートがありません。")
        return

    client = get_client()

    for tweet in tweets:
        slot = tweet["slot"]
        fmt = tweet["format"]
        theme = tweet["theme"]
        main_text = tweet["main"]
        reply_text = tweet.get("reply", "")

        print(f"\n--- [{slot}] {theme} ---")

        tweet_id = post_tweet(client, main_text)
        print(f"  本ツイート投稿完了 (ID: {tweet_id})")

        if reply_text:
            time.sleep(2)
            reply_id = post_tweet(client, reply_text, reply_to=tweet_id)
            print(f"  リプライ投稿完了 (ID: {reply_id})")

        time.sleep(3)

    print(f"\n全 {len(tweets)} 件投稿完了！")


def main():
    parser = argparse.ArgumentParser(description="X（Twitter）自動投稿")
    parser.add_argument("json_file", help="生成済みツイートのJSONファイル")
    parser.add_argument("--slot", help="特定スロットだけ投稿 (例: 07:30)")

    args = parser.parse_args()

    import os
    missing = [v for v in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
               if not os.environ.get(v)]
    if missing:
        print(f"エラー: 以下の環境変数を設定してください: {', '.join(missing)}")
        sys.exit(1)

    post_from_json(args.json_file, slot_filter=args.slot)


if __name__ == "__main__":
    main()
