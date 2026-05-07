#!/usr/bin/env python3
"""
バチェラーデート アフィリエイトPR投稿

ステマ規制対応:
- 全ツイの先頭ツイ（または単独ツイ）の冒頭に【PR】を必ず明記
- リンク先は BACHELOR_DATE_URL secret（直リンク）

GitHub Secrets が未設定の場合は何もせず exit 0（安全装置）。

使い方:
  python pr_post.py                       # 投稿（デフォルト thread）
  python pr_post.py --format single       # 単独ツイ
  python pr_post.py --dry-run             # 投稿せず生成だけ
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
SERVICE_NAME = "バチェラーデート"

sys.path.insert(0, str(Path(__file__).parent))
from generate import MODEL, get_client as get_claude
from prompts import (
    SYSTEM_PROMPT,
    PR_BACHELOR_DATE_THREAD_PROMPT,
    PR_BACHELOR_DATE_SINGLE_PROMPT,
)

PROMPTS = {
    "thread": PR_BACHELOR_DATE_THREAD_PROMPT,
    "single": PR_BACHELOR_DATE_SINGLE_PROMPT,
}


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_recent_pr(limit: int = 20) -> str:
    """過去PRを取得（被り回避用）"""
    if not HISTORY_FILE.exists():
        return "(まだ履歴なし)"
    lines = HISTORY_FILE.read_text().strip().split("\n")[-limit:]
    out = []
    for line in lines:
        if not line:
            continue
        d = json.loads(line)
        out.append(f"- [{d['date'][:10]}] {d['summary'][:120]}")
    return "\n".join(out) or "(履歴なし)"


def save(fmt: str, summary: str, posted_ids: list[str]):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "service": "bachelor_date",
        "format": fmt,
        "summary": summary[:300],
        "posted_ids": posted_ids,
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    lines = HISTORY_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        HISTORY_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def generate(fmt: str) -> str:
    history = load_recent_pr()
    prompt = PROMPTS[fmt].format(history=history)
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
    return text.replace("{url}", url)


def build_url_reply(url: str) -> str:
    """URL専用リプの本文を組み立て。【PR】明記必須（広告本体のため）"""
    return f"【PR】 公式リンクはこちら↓\n\n{url}"


def post_thread(client: tweepy.Client, tweets: list[str]) -> list[str]:
    """本文ツイートを順にリプで連投。各ツイのIDをリストで返す"""
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
    parser = argparse.ArgumentParser(description=f"アフィリエイトPR投稿（{SERVICE_NAME}）")
    parser.add_argument("--format", default="thread", choices=["thread", "single"])
    parser.add_argument("--dry-run", action="store_true", help="投稿しない")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    # 安全装置: BACHELOR_DATE_URL が空なら exit 0
    affiliate_url = os.environ.get("BACHELOR_DATE_URL", "").strip()
    if not affiliate_url:
        if args.dry_run:
            affiliate_url = "https://example.com/bachelor-date-affiliate"
            print("⚠️  BACHELOR_DATE_URL 未設定（dry-run なので example URL で続行）")
        else:
            print(
                "⚠️  BACHELOR_DATE_URL secret が未設定です。\n"
                "   GitHub の Settings → Secrets → Actions に BACHELOR_DATE_URL を追加してください。\n"
                "   今回は何もせず exit 0 で終了します。"
            )
            return

    if not args.dry_run:
        for var in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]:
            if not os.environ.get(var):
                print(f"エラー: {var} が設定されていません")
                sys.exit(1)

    print(f"=== PR: {SERVICE_NAME} ({args.format}) ===\n")

    raw = generate(args.format)
    if args.format == "thread":
        tweets = parse_thread(raw)
        if len(tweets) < 3:
            print(f"スレッド生成失敗 (got {len(tweets)} tweets)\n--raw--\n{raw}")
            sys.exit(1)
    else:
        tweets = [raw]

    # 1) 先頭ツイに【PR】を強制付与（プロンプト指示が漏れた場合の belt-and-suspenders）
    tweets[0] = ensure_pr_prefix(tweets[0])

    # 2) 本文に紛れ込んだ {url} やURLは除去（プロンプトで禁止してるが念のため）
    tweets = [substitute_url(t, "").strip() for t in tweets]

    # 3) URL専用リプ（広告本体、【PR】必須）を最後に追加
    url_reply = build_url_reply(affiliate_url)
    all_posts = tweets + [url_reply]

    print("--- 生成結果 ---")
    for i, t in enumerate(all_posts, 1):
        is_url_reply = (i == len(all_posts))
        label = "URLリプ" if is_url_reply else f"ツイ{i}"
        print(f"\n{label} ({len(t)}字):\n{t}")
        if len(t) > 280:
            print(f"  ⚠️ {len(t)}字 > 280字。X側で切られる可能性")

    if args.dry_run:
        print("\n[dry-run] 投稿スキップ")
        return

    print("\n=== 投稿開始 ===")
    x_client = get_x_client()
    posted = post_thread(x_client, all_posts)
    save(args.format, tweets[0], posted)
    print(f"\n投稿完了: {len(posted)} tweets（うち最後の1件はURL専用リプ）")


if __name__ == "__main__":
    main()
