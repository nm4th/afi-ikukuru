#!/usr/bin/env python3
"""
バチェラーデート アフィリエイトPR投稿（火・木・土 21:00 JST、週3回）

物語アーク2種を交互に投稿:
- arc="next"  : マチアプ8年失敗 → 「次これ試す」
- arc="tried" : バチェラーデート使ってみた → INTJ自爆

ステマ規制対応:
- 先頭ツイ冒頭 + URL専用リプ冒頭 の両方に【PR】明記
- リンク先は BACHELOR_DATE_URL secret（直リンク）
- URL は本文には絶対に含めず、最後に独立リプとして投稿

GitHub Secrets が未設定の場合は何もせず exit 0（安全装置）。

使い方:
  python pr_post.py                       # 投稿（デフォルト thread, arc=auto）
  python pr_post.py --arc tried           # tried アーク強制
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
    PR_BACHELOR_DATE_TRIED_PROMPT,
)

# (format, arc) → prompt
# - thread + next  : 失敗 → 次バチェラーデート試す（5ツイ）
# - thread + tried : バチェラーデート使ってみた → INTJ自爆（5ツイ）
# - single + next  : 1ツイで「次これ試す」型
# - single + tried : 1ツイで「使ってみた自爆」型（同 thread tried を圧縮した版）
PROMPTS = {
    ("thread", "next"): PR_BACHELOR_DATE_THREAD_PROMPT,
    ("thread", "tried"): PR_BACHELOR_DATE_TRIED_PROMPT,
    ("single", "next"): PR_BACHELOR_DATE_SINGLE_PROMPT,
    ("single", "tried"): PR_BACHELOR_DATE_SINGLE_PROMPT,  # フォールバック（next 用を流用）
}


def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def load_recent_pr(arc: str | None = None, limit: int = 20) -> str:
    """過去PRを取得（被り回避用）。arc 指定時はそのアークだけに絞る"""
    if not HISTORY_FILE.exists():
        return "(まだ履歴なし)"
    lines = HISTORY_FILE.read_text().strip().split("\n")
    out = []
    for line in reversed(lines):
        if not line:
            continue
        d = json.loads(line)
        if arc and d.get("arc") != arc:
            continue
        out.append(f"- [{d['date'][:10]}] {d['summary'][:120]}")
        if len(out) >= limit:
            break
    return "\n".join(reversed(out)) or "(履歴なし)"


def determine_arc() -> str:
    """history を見て次の arc を決定（直近 next なら tried、逆もまた然り）"""
    if not HISTORY_FILE.exists():
        return "next"
    lines = HISTORY_FILE.read_text().strip().split("\n")
    for line in reversed(lines):
        if not line:
            continue
        d = json.loads(line)
        last_arc = d.get("arc")
        if last_arc == "next":
            return "tried"
        if last_arc == "tried":
            return "next"
    # arc 記録のない古い履歴しかない場合は next から始める
    return "next"


def save(fmt: str, arc: str, summary: str, posted_ids: list[str]):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    entry = {
        "date": datetime.now().isoformat(),
        "service": "bachelor_date",
        "format": fmt,
        "arc": arc,
        "summary": summary[:300],
        "posted_ids": posted_ids,
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    lines = HISTORY_FILE.read_text().strip().split("\n")
    if len(lines) > MAX_HISTORY:
        HISTORY_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n")


def generate(fmt: str, arc: str) -> str:
    history = load_recent_pr(arc=arc)
    prompt = PROMPTS[(fmt, arc)].format(history=history)
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


def ensure_reply_pointer(text: str) -> str:
    """最後の本文ツイートに「リンクはリプ欄に」誘導を必ず付与する。
    Claude がプロンプト指示を忘れて誘導文を入れない事故への defense-in-depth。
    """
    # 既に十分な誘導があるか軽くチェック
    has_pointer = (
        ("リプ" in text or "返信" in text)
        and ("↓" in text or "公式" in text or "リンク" in text)
    )
    if has_pointer:
        return text
    # 末尾に明示的な誘導を1行追加
    return text.rstrip() + "\n\n↓ 公式リンクはリプ欄に貼ってます ↓"


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
    parser.add_argument(
        "--arc",
        default="auto",
        choices=["auto", "next", "tried"],
        help="物語アーク: auto=履歴を見て交互、next=次行く型、tried=使ってみた型",
    )
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

    arc = args.arc if args.arc != "auto" else determine_arc()
    print(f"=== PR: {SERVICE_NAME} (format={args.format}, arc={arc}) ===\n")

    raw = generate(args.format, arc)
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

    # 3) 最後の本文ツイに「リンクはリプに」誘導を強制付与
    #    （プロンプトで指示してるが Claude が忘れることがある事故への defense-in-depth）
    tweets[-1] = ensure_reply_pointer(tweets[-1])

    # 4) URL専用リプ（広告本体、【PR】必須）を最後に追加
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
    save(args.format, arc, tweets[0], posted)
    print(f"\n投稿完了: {len(posted)} tweets（うち最後の1件はURL専用リプ）")


if __name__ == "__main__":
    main()
