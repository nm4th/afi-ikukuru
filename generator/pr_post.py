#!/usr/bin/env python3
"""
アフィリエイトPR投稿（バチェラーデート / Photojoy → 単一の Linktree URL）

ステマ規制対応:
- 全ツイの先頭ツイ（または単独ツイ）の冒頭に【PR】を必ず明記
- リンク先は Linktree のハブページ（LINKTREE_URL secret）

GitHub Secrets が未設定の場合は何もせず exit 0（安全装置）。

使い方:
  python pr_post.py --service bachelor_date --format thread
  python pr_post.py --service photojoy --format single --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import tweepy

HISTORY_FILE = Path(__file__).parent.parent / "history" / "pr_posts.jsonl"
MAX_HISTORY = 200
PR_PREFIX = "【PR】"

SERVICE_CONFIG = {
    "bachelor_date": {"name": "バチェラーデート"},
    "photojoy": {"name": "Photojoy"},
}

sys.path.insert(0, str(Path(__file__).parent))
from generate import MODEL, get_client as get_claude
from prompts import (
    SYSTEM_PROMPT,
    PR_BACHELOR_DATE_THREAD_PROMPT,
    PR_BACHELOR_DATE_SINGLE_PROMPT,
    PR_PHOTOJOY_THREAD_PROMPT,
    PR_PHOTOJOY_SINGLE_PROMPT,
)

PROMPTS = {
    ("bachelor_date", "thread"): PR_BACHELOR_DATE_THREAD_PROMPT,
    ("bachelor_date", "single"): PR_BACHELOR_DATE_SINGLE_PROMPT,
    ("photojoy", "thread"): PR_PHOTOJOY_THREAD_PROMPT,
    ("photojoy", "single"): PR_PHOTOJOY_SINGLE_PROMPT,
}


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_recent_pr(service: str, limit: int = 20) -> str:
    """指定サービスの過去PRを取得（被り回避用）"""
    if not HISTORY_FILE.exists():
        return "(まだ履歴なし)"
    lines = HISTORY_FILE.read_text().strip().split("\n")[-limit * 4:]
    out = []
    for line in lines:
        if not line:
            continue
        d = json.loads(line)
        if d.get("service") == service:
            out.append(f"- [{d['date'][:10]}] {d['summary'][:120]}")
    return "\n".join(out[-limit:]) or "(該当履歴なし)"


def save(service: str, fmt: str, summary: str, posted_ids: list[str]):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "service": service,
        "format": fmt,
        "summary": summary[:300],
        "posted_ids": posted_ids,
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    lines = HISTORY_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        HISTORY_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def generate(service: str, fmt: str) -> str:
    history = load_recent_pr(service)
    prompt = PROMPTS[(service, fmt)].format(history=history)
    client = get_claude()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in msg.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def parse_thread(raw: str) -> list[str]:
    parts = re.split(r"【ツイート\d+】", raw)
    return [p.strip() for p in parts if p.strip()]


def ensure_pr_prefix(text: str) -> str:
    """【PR】が無ければ冒頭に付与（ステマ規制対応の belt-and-suspenders）"""
    if PR_PREFIX in text[:20]:
        return text
    return f"{PR_PREFIX} {text}"


def substitute_url(text: str, url: str) -> str:
    """{url} placeholder を実URLに置換"""
    return text.replace("{url}", url)


def post_thread(client: tweepy.Client, tweets: list[str]) -> list[str]:
    posted = []
    prev_id = None
    for i, text in enumerate(tweets, 1):
        kwargs: dict = {"text": text}
        if prev_id:
            kwargs["in_reply_to_tweet_id"] = str(prev_id)
        try:
            response = client.create_tweet(**kwargs)
        except tweepy.HTTPException as e:
            status = getattr(getattr(e, "response", None), "status_code", "?")
            if status == 402:
                print("\n!!! 402 Payment Required（クレジット切れ）!!!")
            raise
        prev_id = str(response.data["id"])
        posted.append(prev_id)
        print(f"  [{i}/{len(tweets)}] 投稿完了 (ID: {prev_id})")
        if i < len(tweets):
            time.sleep(2)
    return posted


def main():
    parser = argparse.ArgumentParser(description="アフィリエイトPR投稿")
    parser.add_argument("--service", required=True, choices=list(SERVICE_CONFIG))
    parser.add_argument("--format", default="thread", choices=["thread", "single"])
    parser.add_argument("--dry-run", action="store_true", help="投稿しない")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    # 安全装置: LINKTREE_URL が空なら exit 0（ASP承認待ち期間）
    linktree_url = os.environ.get("LINKTREE_URL", "").strip()
    if not linktree_url:
        if args.dry_run:
            linktree_url = "https://linktr.ee/EXAMPLE"
            print("⚠️  LINKTREE_URL 未設定（dry-run なので example URL で続行）")
        else:
            print(
                "⚠️  LINKTREE_URL secret が未設定です。\n"
                "   ASP承認 + Linktree 設定が完了したら GitHub の\n"
                "   Settings → Secrets → Actions に LINKTREE_URL を追加してください。\n"
                "   今回は何もせず exit 0 で終了します。"
            )
            return

    if not args.dry_run:
        for var in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]:
            if not os.environ.get(var):
                print(f"エラー: {var} が設定されていません")
                sys.exit(1)

    service_name = SERVICE_CONFIG[args.service]["name"]
    print(f"=== PR: {service_name} ({args.format}) ===\n")

    raw = generate(args.service, args.format)
    if args.format == "thread":
        tweets = parse_thread(raw)
        if len(tweets) < 3:
            print(f"スレッド生成失敗 (got {len(tweets)} tweets)\n--raw--\n{raw}")
            sys.exit(1)
    else:
        tweets = [raw]

    # 1) 先頭ツイに【PR】を強制付与
    tweets[0] = ensure_pr_prefix(tweets[0])
    # 2) {url} placeholder を実URLに置換
    tweets = [substitute_url(t, linktree_url) for t in tweets]

    print("--- 生成結果 ---")
    for i, t in enumerate(tweets, 1):
        print(f"\nツイ{i} ({len(t)}字):\n{t}")
        if len(t) > 280:
            print(f"  ⚠️ {len(t)}字 > 280字。X側で切られる可能性")

    if args.dry_run:
        print("\n[dry-run] 投稿スキップ")
        return

    print("\n=== 投稿開始 ===")
    x_client = get_x_client()
    posted = post_thread(x_client, tweets)
    save(args.service, args.format, tweets[0], posted)
    print(f"\n投稿完了: {len(posted)} tweets")


if __name__ == "__main__":
    main()
