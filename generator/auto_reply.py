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
MIN_LIKES = 50
MAX_LIKES = 10000  # 炎上回避
MAX_HISTORY = 500
RECENT_AUTHOR_DAYS = 14

# 攻撃的単語（含まれていたら除外）— 本当に攻撃的なものだけに絞る
# （旧版の バカ/アホ/終わり/ks は誤検出が多すぎて候補が全消えしていた）
HOSTILE_PATTERNS = [
    r"死ね", r"殺す", r"ガイジ", r"消えろ", r"○ね",
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


def search_targets(client: tweepy.Client, queries: list[str]) -> tuple[list[dict], dict]:
    """検索結果と、診断用の集計（クエリ別件数 + HTTPエラー集計）を返す"""
    all_tweets = []
    diag = {"per_query": {}, "errors": {}}
    for q in queries:
        print(f"  検索中: {q}")
        try:
            response = client.search_recent_tweets(
                query=f"{q} -is:retweet -is:reply lang:ja",
                max_results=50,
                tweet_fields=["public_metrics", "author_id", "created_at", "reply_settings"],
                user_auth=True,
            )
        except tweepy.TooManyRequests:
            print(f"    ⚠️ レート制限")
            diag["errors"]["429"] = diag["errors"].get("429", 0) + 1
            diag["per_query"][q] = "rate_limit"
            continue
        except tweepy.HTTPException as e:
            status = getattr(getattr(e, "response", None), "status_code", "?")
            body = ""
            try:
                body = getattr(e.response, "text", "")[:200]
            except Exception:
                pass
            if status == 402:
                print(f"    ⛔ 402 Payment Required（pay-per-use クレジット切れ）: {body}")
                raise SystemExit(0)
            print(f"    ⚠️ HTTP {status}: {body}")
            diag["errors"][str(status)] = diag["errors"].get(str(status), 0) + 1
            diag["per_query"][q] = f"http_{status}"
            continue
        n = len(response.data) if response.data else 0
        diag["per_query"][q] = n
        print(f"    → {n}件")
        if not response.data:
            continue
        for t in response.data:
            m = t.public_metrics
            if m["like_count"] < MIN_LIKES:
                continue  # min_faves演算子代替: コード側でフィルタ
            all_tweets.append({
                "id": str(t.id),
                "text": t.text,
                "author_id": str(t.author_id) if t.author_id else "",
                "metrics": m,
                "reply_settings": getattr(t, "reply_settings", "everyone") or "everyone",
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
    return unique, diag


def filter_targets(
    candidates: list[dict],
    replied_ids: set[str],
    author_last: dict[str, str],
    skip_ids: set[str] | None = None,
) -> tuple[list[dict], dict]:
    """フィルタを通った候補リストを返す（複数候補を試行できるよう list で返す）"""
    cutoff = datetime.now() - timedelta(days=RECENT_AUTHOR_DAYS)
    rejected = {
        "already_replied": 0, "mega_viral": 0, "hostile": 0,
        "recent_author": 0, "reply_restricted": 0, "skip_in_run": 0,
    }
    skip_ids = skip_ids or set()
    out = []
    for t in candidates:
        if t["id"] in skip_ids:
            rejected["skip_in_run"] += 1
            continue
        if t["id"] in replied_ids:
            rejected["already_replied"] += 1
            continue
        if t["metrics"]["like_count"] > MAX_LIKES:
            rejected["mega_viral"] += 1
            continue
        if is_hostile(t["text"]):
            rejected["hostile"] += 1
            continue
        # X のリプ制限（mentioned/following/verified のみ）は事前に除外
        if t.get("reply_settings", "everyone") != "everyone":
            rejected["reply_restricted"] += 1
            continue
        last = author_last.get(t["author_id"], "")
        if last:
            try:
                if datetime.fromisoformat(last) > cutoff:
                    rejected["recent_author"] += 1
                    continue
            except (ValueError, TypeError):
                pass
        out.append(t)
    return out, rejected


def pick_target(candidates: list[dict], replied_ids: set[str], author_last: dict[str, str]) -> tuple[dict | None, dict]:
    """後方互換: 最初の1件を返す（旧呼び出しコード対応）"""
    eligible, rejected = filter_targets(candidates, replied_ids, author_last)
    return (eligible[0] if eligible else None), rejected


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

    candidates, search_diag = search_targets(x_client, SEARCH_QUERIES)
    print(f"\n  クエリ別: {search_diag['per_query']}")
    if search_diag["errors"]:
        print(f"  HTTPエラー集計: {search_diag['errors']}")
    print(f"  候補（重複除外後）: {len(candidates)}件")

    # 投稿時に 403（リプ制限など）が出たらこの run 内では再試行しない ID 集合
    skip_in_run: set[str] = set()
    MAX_ATTEMPTS = 5  # 候補が多くてもリプ生成コスト的に5回まで

    for attempt in range(MAX_ATTEMPTS):
        eligible, rejected = filter_targets(candidates, replied_ids, author_last, skip_in_run)
        if attempt == 0:
            print(f"  リプ可能候補: {len(eligible)}件")
        if not eligible:
            if attempt == 0:
                print(f"\n  ⚠️ 適切なリプ対象が見つかりませんでした")
                print(f"  除外内訳: {rejected}")
                if not candidates and not search_diag["errors"]:
                    print(
                        f"  → 全クエリで0件・エラーなし。原因候補:\n"
                        f"     (1) MIN_LIKES={MIN_LIKES} が高すぎ、Niche のバズ閾値に届いていない\n"
                        f"     (2) 検索クエリが微妙\n"
                        f"     (3) 該当言語/期間にツイートが本当に無い"
                    )
                elif search_diag["errors"]:
                    print(f"  → search_recent_tweets が HTTP エラーで失敗。X API 設定を要確認")
            else:
                print(f"\n  ⚠️ {attempt}回試行したが、リプ可能な候補が尽きました")
            return

        target = eligible[0]
        m = target["metrics"]
        print(f"\n📌 リプ対象 (試行 {attempt+1}, 検索: {target['query']}):")
        print(f"  {target['text'][:200]}")
        print(f"  ❤️{m['like_count']} 🔁{m['retweet_count']} / reply_settings={target.get('reply_settings')}")

        print(f"\n📝 リプ生成中...")
        comment = generate_reply(target["text"])
        print(f"\n{comment}")

        if len(comment) > 200:
            print(f"\n警告: コメントが {len(comment)} 字（180字推奨を超過）")

        if args.dry_run:
            print("\n[dry-run] リプはスキップ")
            return

        print(f"\n🚀 リプ投稿中...")
        try:
            rid = post_reply(x_client, comment, target["id"])
        except tweepy.Forbidden as e:
            print(f"  ⚠️ 403 Forbidden（投稿時のリプ制限など）: {e}")
            print(f"     → このターゲットは skip して次の候補を試行")
            skip_in_run.add(target["id"])
            continue
        print(f"  完了 (ID: {rid})")
        save_reply(target["id"], target["author_id"], target["text"], comment)
        print("  履歴に保存しました")
        return

    print(f"\n  ⚠️ MAX_ATTEMPTS={MAX_ATTEMPTS} 回試行しても投稿できませんでした")


if __name__ == "__main__":
    main()
