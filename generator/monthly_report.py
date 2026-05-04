#!/usr/bin/env python3
"""
月初のマチアプ収支報告（毎月1日 21:00 JST）

架空の数字でリアルな失敗ベースの「月次収支」を投稿する。
シリーズ識別ハッシュタグ #月初のマチアプ収支報告 をつける。
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import tweepy

JST = ZoneInfo("Asia/Tokyo")
HISTORY_FILE = Path(__file__).parent.parent / "history" / "monthly_report.jsonl"

sys.path.insert(0, str(Path(__file__).parent))
from generate import MODEL, get_client as get_claude
from prompts import SYSTEM_PROMPT, MONTHLY_REPORT_PROMPT


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_history(limit: int = 6) -> str:
    if not HISTORY_FILE.exists():
        return "(まだ履歴なし)"
    lines = HISTORY_FILE.read_text().strip().split("\n")[-limit:]
    out = []
    for line in lines:
        if line:
            d = json.loads(line)
            out.append(f"- {d['month']}: {d['summary'][:100]}")
    return "\n".join(out)


def save(month: str, summary: str, tweet_id: str | None):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {"date": datetime.now().isoformat(), "month": month, "summary": summary[:300], "tweet_id": tweet_id}
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def generate_report() -> tuple[str, str]:
    """先月名と投稿テキストを返す"""
    now = datetime.now(JST)
    last_month = now.month - 1 if now.month > 1 else 12
    history = load_history()

    client = get_claude()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": MONTHLY_REPORT_PROMPT.format(month=last_month, history=history)}],
    )
    text = ""
    for block in msg.content:
        if block.type == "text":
            text = block.text.strip()
            break
    return str(last_month), text


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
    parser = argparse.ArgumentParser(description="月初のマチアプ収支報告")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run:
        for var in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]:
            if not os.environ.get(var):
                print(f"エラー: {var} が設定されていません")
                sys.exit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    print("=== 月初のマチアプ収支報告 ===\n")
    month, text = generate_report()
    print(f"先月: {month}月")
    print(f"\n--- ({len(text)}字) ---")
    print(text)

    if args.dry_run:
        print("\n[dry-run] 投稿スキップ")
        return

    print("\n🚀 投稿中...")
    x_client = get_x_client()
    tid = post(x_client, text)
    print(f"  完了 (ID: {tid})")
    save(month, text, tid)


if __name__ == "__main__":
    main()
