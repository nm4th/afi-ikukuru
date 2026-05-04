#!/usr/bin/env python3
"""
バズMBTI/INTJツイートのコメント欄に INTJ視点のリプライを残す（1日3回）

引用RTより「コメント欄」の方が新規露出に強いため、賢いリプを残して
リプ欄経由で目に触れる戦法。

安全装置:
- 1実行で1リプ（同時間帯の連投禁止）
- 同じauthorに連続リプ禁止（過去14日間）
- 過去にリプ済みのツイートは除外
- 攻撃的単語を含む元ツイは除外
- min_faves: 300〜10000 の範囲（メガ投稿は炎上参戦回避）

使い方:
  python auto_reply.py             # 検索 + リプ投稿
  python auto_reply.py --dry-run   # 投稿しない
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import tweepy

HISTORY_FILE = Path(__file__).parent.parent / "history" / "replied.jsonl"
SEARCH_QUERIES = ["MBTI 恋愛", "INTJ 恋愛", "MBTI 相性", "INFJ 恋愛", "ENFP 恋愛"]
MIN_LIKES = 300
MAX_LIKES = 10000  # 炎上回避
MAX_HISTORY = 500
RECENT_AUTHOR_DAYS = 14

# 攻撃的単語（含まれていたら除外）
HOSTILE_PATTERNS = [
    r"死ね", r"殺す", r"クソ", r"ks", r"ガイジ", r"バカ", r"アホ",
    r"終わり", r"消えろ",
]

sys.path.insert(0, str(Path(__file__).parent))
from prompts import SYSTEM_PROMPT, REPLY_PROMPT


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_history() -> tuple[set[str], dict[str, str]]:
    """過去にリプしたツイートID集合と、author_id → 最終リプ日 のマップを返す"""
    if not HISTORY_FILE.exists():
        return set(), {}
    ids = set()
    author_last = {}
    for line in HISTORY_FILE.read_text().strip().split("\n"):
        if not line:
            continue
        d = json.loads(line)
        ids.add(d["tweet_id"])
        author_last[d.get("author_id", "")] = d["date"]
    return ids, author_last


def save_reply(tweet_id: str, author_id: str, target_text: str, comment: str):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "tweet_id": tweet_id,
        "author_id": author_id,
        "target_text": target_text[:200],
        "comment": comment[:200],
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    lines = HISTORY_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        HISTORY_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def is_hostile(text: str) -> bool:
    return any(re.search(p, text) for p in HOSTILE_PATTERNS)


def search_targets(client: tweepy.Client, queries: list[str]) -> list[dict]:
    all_tweets = []
    for q in queries:
        print(f"  検索中: {q}")
        try:
            response = client.search_recent_tweets(
                query=f"{q} -is:retweet -is:reply lang:ja min_faves:{MIN_LIKES}",
                max_results=15,
                tweet_fields=["public_metrics", "author_id", "created_at"],
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
            print(f"    HTTP {status} エラー: {e}")
            continue
        if not response.data:
            continue
        for t in response.data:
            m = t.public_metrics
            all_tweets.append({
                "id": str(t.id),
                "text": t.text,
                "author_id": str(t.author_id) if t.author_id else "",
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


def pick_target(candidates: list[dict], replied_ids: set[str], author_last: dict[str, str]) -> dict | None:
    cutoff = datetime.now() - timedelta(days=RECENT_AUTHOR_DAYS)
    for t in candidates:
        if t["id"] in replied_ids:
            continue
        if t["metrics"]["like_count"] > MAX_LIKES:
            continue  # 炎上回避
        if is_hostile(t["text"]):
            continue
        last = author_last.get(t["author_id"], "")
        if last:
            try:
                if datetime.fromisoformat(last) > cutoff:
                    continue  # 同一authorへの直近リプ禁止
            except (ValueError, TypeError):
                pass
        return t
    return None


def generate_reply(target_text: str, context_replies: str = "(なし)") -> str:
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": REPLY_PROMPT.format(
            target_tweet=target_text,
            context_replies=context_replies,
        )}],
    )
    for block in msg.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def post_reply(client: tweepy.Client, comment: str, in_reply_to: str) -> str:
    try:
        response = client.create_tweet(text=comment, in_reply_to_tweet_id=in_reply_to)
    except tweepy.HTTPException as e:
        status = getattr(getattr(e, "response", None), "status_code", "?")
        if status == 402:
            print("\n!!! 402 Payment Required（クレジット切れ）!!!")
        raise
    return str(response.data["id"])


def main():
    parser = argparse.ArgumentParser(description="MBTI/INTJ バズツイへのリプ")
    parser.add_argument("--dry-run", action="store_true", help="投稿せず確認")
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
    replied_ids, author_last = load_history()

    print("=== バズツイ コメント欄リプ ===\n")
    print(f"  過去リプ: {len(replied_ids)}件 / 直近{RECENT_AUTHOR_DAYS}日リプ済author: {len(author_last)}件\n")

    candidates = search_targets(x_client, SEARCH_QUERIES)
    print(f"\n  候補: {len(candidates)}件")

    target = pick_target(candidates, replied_ids, author_last)
    if not target:
        print("適切なリプ対象が見つかりませんでした")
        return

    m = target["metrics"]
    print(f"\n📌 リプ対象 (検索: {target['query']}):")
    print(f"  {target['text'][:200]}")
    print(f"  ❤️{m['like_count']} 🔁{m['retweet_count']}")

    print(f"\n📝 リプ生成中...")
    comment = generate_reply(target["text"])
    print(f"\n{comment}")

    if len(comment) > 200:
        print(f"\n警告: コメントが {len(comment)} 字（180字推奨を超過）")

    if args.dry_run:
        print("\n[dry-run] リプはスキップ")
        return

    print(f"\n🚀 リプ投稿中...")
    rid = post_reply(x_client, comment, target["id"])
    print(f"  完了 (ID: {rid})")
    save_reply(target["id"], target["author_id"], target["text"], comment)
    print("  履歴に保存しました")


if __name__ == "__main__":
    main()
