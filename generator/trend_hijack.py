#!/usr/bin/env python3
"""
トレンドハイジャック（4時間ごと）

直近4時間で min_faves:200 の MBTI/INTJ系ツイートを検出し、
INTJ視点の独立した投稿（引用RTではなく、トピックに乗っかるオリジナル）を生成・投稿。

1日の最大反応回数（DAILY_CAP）でスパム化を防ぐ。
反応済みトピックを history/hijacked.jsonl で管理。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import tweepy

HISTORY_FILE = Path(__file__).parent.parent / "history" / "hijacked.jsonl"
SEARCH_QUERIES = ["MBTI", "INTJ", "INFJ", "ENFP", "ISTJ"]
MIN_LIKES = 500
DAILY_CAP = 2  # 1日最大2回反応
RECENT_HOURS = 8  # 直近8時間のツイートのみ対象（cron に合わせて拡大）
MAX_HISTORY = 500

sys.path.insert(0, str(Path(__file__).parent))
from prompts import SYSTEM_PROMPT, TREND_HIJACK_PROMPT


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_history() -> tuple[set[str], int]:
    """反応済みID集合と、当日反応数を返す"""
    if not HISTORY_FILE.exists():
        return set(), 0
    today = datetime.now().date()
    ids = set()
    today_count = 0
    for line in HISTORY_FILE.read_text().strip().split("\n"):
        if not line:
            continue
        d = json.loads(line)
        ids.add(d["target_id"])
        try:
            if datetime.fromisoformat(d["date"]).date() == today:
                today_count += 1
        except (ValueError, TypeError):
            pass
    return ids, today_count


def save(target_id: str, target_text: str, hijack_text: str, posted_id: str):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "target_id": target_id,
        "target_text": target_text[:200],
        "hijack_text": hijack_text[:200],
        "posted_id": posted_id,
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    lines = HISTORY_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        HISTORY_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def search_recent(client: tweepy.Client, queries: list[str]) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENT_HOURS)
    all_tweets = []
    for q in queries:
        print(f"  検索中: {q}")
        try:
            response = client.search_recent_tweets(
                query=f"{q} -is:retweet -is:reply lang:ja min_faves:{MIN_LIKES}",
                max_results=15,
                tweet_fields=["public_metrics", "created_at", "author_id"],
                start_time=cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
                user_auth=True,
            )
        except tweepy.TooManyRequests:
            print(f"    レート制限")
            continue
        except tweepy.HTTPException as e:
            status = getattr(getattr(e, "response", None), "status_code", "?")
            if status == 402:
                print(f"    402 Payment Required（クレジット切れ）")
                raise SystemExit(0)
            print(f"    HTTP {status}: {e}")
            continue
        if not response.data:
            continue
        for t in response.data:
            m = t.public_metrics
            all_tweets.append({
                "id": str(t.id),
                "text": t.text,
                "metrics": m,
                "score": m["like_count"] + m["retweet_count"] * 3,
                "query": q,
            })
        time.sleep(1)

    seen = set()
    unique = []
    for t in all_tweets:
        if t["id"] not in seen:
            seen.add(t["id"])
            unique.append(t)
    unique.sort(key=lambda t: t["score"], reverse=True)
    return unique


def generate_hijack(target_text: str, context: list[dict]) -> str:
    context_text = "\n".join(f"- {t['text'][:150]}" for t in context) if context else "(なし)"
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": TREND_HIJACK_PROMPT.format(
            target_tweet=target_text,
            context_tweets=context_text,
        )}],
    )
    for block in msg.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def post(client: tweepy.Client, text: str) -> str:
    try:
        response = client.create_tweet(text=text)
    except tweepy.HTTPException as e:
        status = getattr(getattr(e, "response", None), "status_code", "?")
        if status == 402:
            print("\n!!! 402 Payment Required（クレジット切れ）!!!")
        raise
    return str(response.data["id"])


def main():
    parser = argparse.ArgumentParser(description="トレンドハイジャック")
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

    print("=== トレンドハイジャック ===\n")

    hijacked_ids, today_count = load_history()
    print(f"  本日の反応数: {today_count}/{DAILY_CAP}")
    if today_count >= DAILY_CAP:
        print("  本日の上限に達しました。スキップ。")
        return

    x_client = get_x_client()
    candidates = search_recent(x_client, SEARCH_QUERIES)
    print(f"\n  直近{RECENT_HOURS}h候補: {len(candidates)}件")

    target = next((t for t in candidates if t["id"] not in hijacked_ids), None)
    if not target:
        print("適切なターゲットが見つかりませんでした")
        return

    m = target["metrics"]
    print(f"\n📌 ターゲット (検索: {target['query']}):")
    print(f"  {target['text'][:200]}")
    print(f"  ❤️{m['like_count']} 🔁{m['retweet_count']}")

    context = [t for t in candidates if t["id"] != target["id"]][:5]
    print(f"\n📝 ハイジャック投稿生成中...")
    text = generate_hijack(target["text"], context)
    print(f"\n{text}")

    if args.dry_run:
        print("\n[dry-run] 投稿スキップ")
        return

    print("\n🚀 投稿中...")
    pid = post(x_client, text)
    print(f"  完了 (ID: {pid})")
    save(target["id"], target["text"], text, pid)


if __name__ == "__main__":
    main()
