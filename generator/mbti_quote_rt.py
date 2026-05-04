#!/usr/bin/env python3
"""
MBTI/INTJ系のバズツイートに INTJ視点コメントをつけて引用RT（週2回）

使い方:
  python mbti_quote_rt.py             # 検索 + 引用RT投稿
  python mbti_quote_rt.py --dry-run   # 投稿しない
  python mbti_quote_rt.py --query "INTJ"  # クエリ指定
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
import tweepy

HISTORY_FILE = Path(__file__).parent.parent / "history" / "mbti_quoted.jsonl"
SEARCH_QUERIES = ["MBTI 恋愛", "INTJ 恋愛", "MBTI 相性", "INFJ 恋愛"]
MIN_LIKES = 300
MAX_HISTORY = 200

sys.path.insert(0, str(Path(__file__).parent))
from prompts import SYSTEM_PROMPT, MBTI_QUOTE_PROMPT


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_quoted_ids() -> set[str]:
    if not HISTORY_FILE.exists():
        return set()
    ids = set()
    for line in HISTORY_FILE.read_text().strip().split("\n"):
        if line:
            data = json.loads(line)
            ids.add(data["tweet_id"])
    return ids


def save_quoted(tweet_id: str, tweet_text: str, comment: str):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "tweet_id": tweet_id,
        "tweet_text": tweet_text[:200],
        "comment": comment[:200],
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    lines = HISTORY_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        HISTORY_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def search_tweets(client: tweepy.Client, query: str, max_results: int = 15) -> list[dict]:
    try:
        response = client.search_recent_tweets(
            query=f"{query} -is:retweet -is:reply lang:ja min_faves:{MIN_LIKES}",
            max_results=max_results,
            tweet_fields=["public_metrics", "created_at", "author_id"],
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
    if not response.data:
        return []

    out = []
    for t in response.data:
        m = t.public_metrics
        score = (
            m.get("impression_count", 0)
            + m["like_count"] * 100
            + m["retweet_count"] * 200
            + m["reply_count"] * 50
        )
        out.append({
            "id": str(t.id),
            "text": t.text,
            "metrics": m,
            "score": score,
            "query": query,
        })
    return out


def find_target(client: tweepy.Client, queries: list[str], quoted_ids: set[str]):
    all_tweets = []
    for q in queries:
        print(f"  検索中: {q}")
        tweets = search_tweets(client, q)
        if tweets:
            print(f"    → {len(tweets)}件")
        all_tweets.extend(tweets)
        time.sleep(1)

    seen = set()
    unique = []
    for t in all_tweets:
        if t["id"] not in seen:
            seen.add(t["id"])
            unique.append(t)

    unique.sort(key=lambda t: t["score"], reverse=True)
    print(f"\n  合計: {len(unique)}件（重複除外済み）")

    target = None
    for t in unique:
        if t["id"] not in quoted_ids:
            target = t
            break

    if not target:
        return None, []

    context = [t for t in unique if t["id"] != target["id"]][:5]
    return target, context


def generate_comment(target_text: str, context: list[dict]) -> str:
    context_text = "\n".join(f"- {t['text'][:150]}" for t in context) if context else "(なし)"
    prompt = MBTI_QUOTE_PROMPT.format(target_tweet=target_text, context_tweets=context_text)
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in msg.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def post_quote_rt(client: tweepy.Client, comment: str, quote_tweet_id: str) -> str:
    try:
        response = client.create_tweet(text=comment, quote_tweet_id=quote_tweet_id)
    except tweepy.HTTPException as e:
        status = getattr(getattr(e, "response", None), "status_code", "?")
        if status == 402:
            print(
                "\n!!! 402 Payment Required !!!\n"
                "Developer Portal の Billing でクレジット残高を追加してください。\n"
                f"詳細: {e}\n"
            )
        raise
    return str(response.data["id"])


def main():
    parser = argparse.ArgumentParser(description="MBTI/INTJ 引用RT")
    parser.add_argument("--dry-run", action="store_true", help="投稿せず確認だけ")
    parser.add_argument("--query", help="特定のキーワードのみで検索")
    args = parser.parse_args()

    if not args.dry_run:
        for var in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]:
            if not os.environ.get(var):
                print(f"エラー: {var} が設定されていません")
                sys.exit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    x_client = get_x_client()
    quoted_ids = load_quoted_ids()
    queries = [args.query] if args.query else SEARCH_QUERIES

    print("=== MBTI/INTJ 引用RT ===\n")
    target, context = find_target(x_client, queries, quoted_ids)

    if not target:
        print("引用対象のツイートが見つかりませんでした")
        return

    m = target["metrics"]
    print(f"\n📌 引用対象 (検索: {target['query']}):")
    print(f"  {target['text'][:200]}")
    print(f"  ❤️{m['like_count']} 🔁{m['retweet_count']} 💬{m['reply_count']}")

    print(f"\n📝 INTJコメント生成中...")
    comment = generate_comment(target["text"], context)
    print(f"\n{comment}")

    if args.dry_run:
        print("\n[dry-run] 投稿はスキップしました")
        return

    print(f"\n🚀 引用RT投稿中...")
    rt_id = post_quote_rt(x_client, comment, target["id"])
    print(f"  投稿完了 (ID: {rt_id})")

    save_quoted(target["id"], target["text"], comment)
    print("  履歴に保存しました")


if __name__ == "__main__":
    main()
