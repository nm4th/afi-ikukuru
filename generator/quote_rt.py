#!/usr/bin/env python3
"""
恋愛リアリティショー × INTJ分析 引用RTスクリプト

その時一番話題になっている恋愛リアリティショーのツイートを見つけ、
INTJ視点の分析引用RTを自動投稿する。

使い方:
  python quote_rt.py                # 自動で1件引用RT
  python quote_rt.py --dry-run      # 投稿せずに確認だけ
  python quote_rt.py --query "恋愛病院"  # 番組指定
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

MODEL = "claude-sonnet-4-6"

HISTORY_FILE = Path(__file__).parent.parent / "history" / "quoted.jsonl"

SEARCH_QUERIES = [
    "恋リア",
    "恋愛リアリティ",
    "ABEMA 恋愛",
    "恋愛番組",
    "恋愛病院",
    "今日好き",
    "乗り換え恋愛",
    "シャッフルアイランド",
    "オオカミくん",
    "ラブパワーキングダム",
    "バチェラー",
    "バチェロレッテ",
]

MIN_LIKES = 50

ANALYSIS_PROMPT = """\
あなたは「恋愛偏差値28のINTJ分析官」です。
恋愛リアリティショーに関するツイートを見て、INTJ視点から分析的な引用リツイートを作成してください。

【引用する元ツイート】
{target_tweet}

【同じ話題に関する他のツイート（世間の反応）】
{context_tweets}

【ルール】
- 260文字以内（引用RT表示分を考慮）
- INTJ特有の冷静で分析的な視点
- でも自分の恋愛偏差値は28なので自虐を交える
- 出演者の行動をMBTIタイプに絡めて分析すると良い
- 「なるほど」「わかる」と思わせる共感性のある内容
- 上から目線ではなく、分析好きが止まらないスタンス
- ハッシュタグは最大1個（番組名など）、なくてもOK
- 改行は最小限に

【ツイート本文のみを出力してください。前置きや説明は不要です。】"""


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


def save_quoted(tweet_id: str, tweet_text: str, analysis: str):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "tweet_id": tweet_id,
        "tweet_text": tweet_text[:100],
        "analysis": analysis[:100],
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def search_tweets(client: tweepy.Client, query: str, max_results: int = 20) -> list[dict]:
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
            print(f"  検索が拒否されました: 402 Payment Required — pay-per-use のクレジット残高が0です ({e})")
        elif status == 401:
            print(f"  検索が拒否されました: 401 Unauthorized ({e})")
        elif status == 403:
            print(f"  検索が拒否されました: 403 Forbidden ({e})")
        else:
            print(f"  検索が拒否されました: HTTP {status} ({e})")
        raise SystemExit(0)

    if not response.data:
        return []

    tweets = []
    for tweet in response.data:
        metrics = tweet.public_metrics
        impressions = metrics.get("impression_count", 0)
        score = (
            impressions
            + metrics["like_count"] * 100
            + metrics["retweet_count"] * 200
            + metrics["reply_count"] * 50
        )
        tweets.append({
            "id": str(tweet.id),
            "text": tweet.text,
            "score": score,
            "metrics": metrics,
            "query": query,
        })

    return tweets


def find_best_tweet(
    client: tweepy.Client,
    queries: list[str],
    quoted_ids: set[str],
) -> tuple[dict | None, list[dict]]:
    all_tweets = []

    for query in queries:
        print(f"  検索中: {query}")
        tweets = search_tweets(client, query)
        if tweets:
            print(f"    → {len(tweets)}件")
        all_tweets.extend(tweets)
        time.sleep(1)

    seen_ids = set()
    unique = []
    for t in all_tweets:
        if t["id"] not in seen_ids:
            seen_ids.add(t["id"])
            unique.append(t)

    unique.sort(key=lambda t: t["score"], reverse=True)

    print(f"\n  合計: {len(unique)}件（重複除外済み）")
    if unique:
        top = unique[0]
        print(f"  トップ: ❤️{top['metrics']['like_count']} 🔁{top['metrics']['retweet_count']} (検索: {top['query']})")

    best = None
    for t in unique:
        if t["id"] not in quoted_ids:
            best = t
            break

    if not best:
        return None, []

    context = [t for t in unique if t["id"] != best["id"]][:5]
    return best, context


def generate_analysis(target_tweet: str, context_tweets: list[dict]) -> str:
    context_text = "\n".join(
        f"- {t['text'][:150]}" for t in context_tweets
    ) if context_tweets else "(なし)"

    prompt = ANALYSIS_PROMPT.format(
        target_tweet=target_tweet,
        context_tweets=context_text,
    )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    for block in message.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def post_quote_rt(client: tweepy.Client, text: str, quote_tweet_id: str) -> str:
    response = client.create_tweet(
        text=text,
        quote_tweet_id=quote_tweet_id,
    )
    return response.data["id"]


def main():
    parser = argparse.ArgumentParser(description="恋愛リアリティショー INTJ分析 引用RT")
    parser.add_argument("--dry-run", action="store_true", help="投稿せずに確認だけ")
    parser.add_argument("--query", help="特定のキーワードで検索")
    args = parser.parse_args()

    for var in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "ANTHROPIC_API_KEY"]:
        if not os.environ.get(var):
            print(f"エラー: {var} が設定されていません")
            sys.exit(1)

    x_client = get_x_client()
    quoted_ids = load_quoted_ids()
    queries = [args.query] if args.query else SEARCH_QUERIES

    print("=== 恋愛リアリティショー 引用RT分析 ===\n")

    best, context = find_best_tweet(x_client, queries, quoted_ids)

    if not best:
        print("引用対象のツイートが見つかりませんでした")
        return

    print(f"\n📌 引用対象 (検索: {best['query']}):")
    print(f"  {best['text'][:200]}")
    print(f"  ❤️{best['metrics']['like_count']} 🔁{best['metrics']['retweet_count']} 💬{best['metrics']['reply_count']} 👁️{best['metrics'].get('impression_count', '?')}")

    print(f"\n📝 分析生成中...")
    analysis = generate_analysis(best["text"], context)
    print(f"\n{analysis}")

    if args.dry_run:
        print("\n[dry-run] 投稿はスキップしました")
        return

    print(f"\n🚀 引用RT投稿中...")
    rt_id = post_quote_rt(x_client, analysis, best["id"])
    print(f"  投稿完了 (ID: {rt_id})")

    save_quoted(best["id"], best["text"], analysis)
    print("  履歴に保存しました")


if __name__ == "__main__":
    main()
