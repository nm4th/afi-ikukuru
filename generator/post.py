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
from pathlib import Path

import tweepy

# 画像化対象フォーマット（main 本文を画像化して添付する）
IMAGE_FORMATS = {"tier", "straight", "full16", "contrast"}


def get_client() -> tweepy.Client:
    import os
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def post_tweet(
    client: tweepy.Client,
    text: str,
    reply_to: str | None = None,
    media_ids: list[str] | None = None,
) -> str:
    """ツイートを投稿し、ツイートIDを返す"""
    kwargs: dict = {"text": text}
    if reply_to:
        kwargs["in_reply_to_tweet_id"] = str(reply_to)
        print(f"  → in_reply_to_tweet_id={kwargs['in_reply_to_tweet_id']}")
    if media_ids:
        kwargs["media_ids"] = media_ids
        print(f"  → media_ids={media_ids}")

    try:
        response = client.create_tweet(**kwargs)
    except tweepy.HTTPException as e:
        status = getattr(getattr(e, "response", None), "status_code", "?")
        if status == 402:
            print(
                "\n!!! 402 Payment Required !!!\n"
                "X API は2026年2月から pay-per-use 課金モデルに移行しました。\n"
                "投稿を再開するには Developer Portal の Billing でクレジットを\n"
                "追加してください（月次キャップの設定も忘れずに）。\n"
                f"詳細: {e}\n"
            )
        raise

    if response.data is None:
        raise RuntimeError(f"create_tweet returned no data; errors={response.errors}")
    return str(response.data["id"])


def maybe_render_and_upload(client: tweepy.Client, text: str, fmt: str, slot: str) -> list[str] | None:
    """フォーマットが画像化対象なら HTML→PNG レンダリング & アップロードして media_ids を返す"""
    if fmt not in IMAGE_FORMATS:
        return None
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from render_image import render_tweet_image, upload_image_to_x
    except ImportError as e:
        print(f"  画像化スキップ（playwright 未インストール？）: {e}")
        return None

    try:
        out_path = Path("/tmp") / f"tweet_{slot.replace(':', '')}.png"
        print(f"  画像生成中... ({fmt})")
        render_tweet_image(text, fmt, out_path)
        print(f"  画像アップロード中... ({out_path})")
        media_id = upload_image_to_x(client, out_path)
        if media_id:
            return [media_id]
    except Exception as e:
        print(f"  画像化失敗、テキストのみで投稿します: {e}")
    return None


def post_from_json(json_path: str, slot_filter: str | None = None, no_image: bool = False):
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

        media_ids = None if no_image else maybe_render_and_upload(client, main_text, fmt, slot)

        tweet_id = post_tweet(client, main_text, media_ids=media_ids)
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
    parser.add_argument("--no-image", action="store_true", help="画像化を無効化（テキストのみ）")

    args = parser.parse_args()

    import os
    missing = [v for v in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
               if not os.environ.get(v)]
    if missing:
        print(f"エラー: 以下の環境変数を設定してください: {', '.join(missing)}")
        sys.exit(1)

    post_from_json(args.json_file, slot_filter=args.slot, no_image=args.no_image)


if __name__ == "__main__":
    main()
