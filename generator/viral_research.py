#!/usr/bin/env python3
"""
MBTI/INTJ系のバズツイートを週次で研究し、要素を抽出して
history/viral_references.jsonl に保存する。

日次の theme 生成プロンプトはこの結果を参考にする。

使い方:
  python viral_research.py             # 検索 + 分析 + 保存
  python viral_research.py --dry-run   # 保存しない
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import tweepy

VIRAL_FILE = Path(__file__).parent.parent / "history" / "viral_references.jsonl"
SEARCH_QUERIES = [
    "MBTI 恋愛",
    "INTJ 恋愛",
    "INFJ 恋愛",
    "ENFP 恋愛",
    "MBTI 相性",
]
MIN_LIKES = 500
MAX_HISTORY = 50

sys.path.insert(0, str(Path(__file__).parent))
from prompts import VIRAL_ANALYSIS_PROMPT


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def search_viral(client: tweepy.Client, query: str, max_results: int = 10) -> list:
    try:
        response = client.search_recent_tweets(
            query=f"{query} -is:retweet -is:reply lang:ja min_faves:{MIN_LIKES}",
            max_results=max_results,
            tweet_fields=["public_metrics", "created_at"],
            user_auth=True,
        )
    except tweepy.TooManyRequests:
        print(f"  レート制限: {query}")
        return []
    except tweepy.HTTPException as e:
        status = getattr(getattr(e, "response", None), "status_code", "?")
        if status == 402:
            print(f"  検索拒否（402 Payment Required, クレジット切れ）: {query}")
            raise SystemExit(0)
        print(f"  検索エラー HTTP {status}: {query} ({e})")
        return []
    return list(response.data) if response.data else []


def analyze(tweets_text: str) -> str:
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": VIRAL_ANALYSIS_PROMPT.format(tweets=tweets_text)}],
    )
    for block in msg.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def trim_history():
    if not VIRAL_FILE.exists():
        return
    lines = VIRAL_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        VIRAL_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="保存しない")
    args = parser.parse_args()

    for var in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "ANTHROPIC_API_KEY"]:
        if not os.environ.get(var):
            print(f"エラー: {var} が設定されていません")
            sys.exit(1)

    x_client = get_x_client()

    print("=== MBTI/INTJ バズツイート研究 ===\n")

    all_tweets = []
    for query in SEARCH_QUERIES:
        print(f"  検索中: {query}")
        tweets = search_viral(x_client, query)
        all_tweets.extend(tweets)
        print(f"    → {len(tweets)}件")

    if not all_tweets:
        print("バズツイートが見つかりませんでした")
        return

    seen = set()
    unique = []
    for t in all_tweets:
        if t.id not in seen:
            seen.add(t.id)
            unique.append(t)

    unique.sort(key=lambda t: t.public_metrics.get("like_count", 0), reverse=True)
    top = unique[:15]

    print(f"\n  ユニーク: {len(unique)}件 / 解析対象: {len(top)}件")

    tweets_text = "\n".join([
        f"- ❤️{t.public_metrics['like_count']} {t.text[:200]}"
        for t in top
    ])

    print("\n=== Claudeで要素抽出中... ===\n")
    analysis = analyze(tweets_text)
    print(analysis)

    if args.dry_run:
        print("\n[dry-run] 保存はスキップしました")
        return

    VIRAL_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "queries": SEARCH_QUERIES,
        "sample_count": len(top),
        "analysis": analysis,
        "top_tweets": [
            {"id": str(t.id), "text": t.text[:300], "likes": t.public_metrics["like_count"]}
            for t in top[:5]
        ],
    }
    with open(VIRAL_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    trim_history()
    print(f"\n保存: {VIRAL_FILE}")


if __name__ == "__main__":
    main()
