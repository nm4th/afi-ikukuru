#!/usr/bin/env python3
"""
ツイート本文を「ホワイトボード風」画像（PNG）にレンダリングするヘルパー。

- Claude が生成した HTML本文 を、固定 CSS テンプレートで囲んで Playwright で screenshot
- 出力サイズ: 1080x1350 (X 推奨の 4:5 縦長)
- 黒背景にチョーク風タイポグラフィ、薄いグリッドの「ホワイトボード」感
- 右下に @intj_love_ サイン
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


CSS_TEMPLATE = """
@import url('https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@400;700;900&family=M+PLUS+Rounded+1c:wght@400;700;900&display=swap');

* { box-sizing: border-box; }

html, body {
    margin: 0;
    padding: 0;
    width: 1080px;
    height: 1350px;
    background: #1a1d21;
    color: #f5f1e8;
    font-family: 'Zen Kaku Gothic New', 'M PLUS Rounded 1c', sans-serif;
    background-image:
        linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
    background-size: 48px 48px;
    overflow: hidden;
    position: relative;
}

.canvas {
    padding: 64px 72px 72px 72px;
    height: 100%;
    display: flex;
    flex-direction: column;
}

.title {
    font-size: 52px;
    font-weight: 900;
    line-height: 1.25;
    margin: 0 0 36px 0;
    color: #fff5cc;
    border-bottom: 3px dashed #4a5058;
    padding-bottom: 24px;
    letter-spacing: 0.02em;
}

.rank {
    display: flex;
    align-items: flex-start;
    gap: 20px;
    margin-bottom: 22px;
    font-size: 30px;
    line-height: 1.45;
}
.rank-num {
    flex-shrink: 0;
    background: #ffd166;
    color: #1a1d21;
    font-weight: 900;
    padding: 4px 16px;
    border-radius: 6px;
    min-width: 80px;
    text-align: center;
}
.rank-body { color: #f5f1e8; }

.tier-row {
    display: flex;
    align-items: stretch;
    gap: 24px;
    margin-bottom: 18px;
    border-left: 4px solid #4a5058;
    padding-left: 20px;
}
.tier-label {
    flex-shrink: 0;
    font-size: 56px;
    font-weight: 900;
    width: 80px;
    text-align: center;
    color: #ffd166;
    line-height: 1;
}
.tier-row .tier-label.s { color: #ff6b6b; }
.tier-row .tier-label.a { color: #ffd166; }
.tier-row .tier-label.b { color: #4ecdc4; }
.tier-row .tier-label.c { color: #95a5a6; }
.tier-types { font-size: 28px; line-height: 1.5; flex: 1; padding-top: 8px; color: #f5f1e8; }

strong {
    background: rgba(255, 209, 102, 0.18);
    color: #fff5cc;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 0.95em;
    letter-spacing: 0.04em;
}

p, ul, li { font-size: 28px; line-height: 1.5; }
ul { padding-left: 32px; }
li { margin-bottom: 8px; }

.punchline {
    margin-top: auto;
    padding-top: 32px;
    border-top: 2px dotted #4a5058;
    font-size: 26px;
    line-height: 1.5;
    color: #c9c2b0;
    font-style: italic;
}

.signature {
    position: absolute;
    bottom: 36px;
    right: 56px;
    font-size: 22px;
    color: #6a7078;
    letter-spacing: 0.1em;
    font-family: 'M PLUS Rounded 1c', sans-serif;
}
"""


HTML_FRAME = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<style>{css}</style>
</head>
<body>
<div class="canvas">
{body}
</div>
<div class="signature">@intj_love_</div>
</body>
</html>
"""


def render_html_to_png(html_body: str, output_path: Path | str, width: int = 1080, height: int = 1350) -> Path:
    """HTMLボディを受け取り、CSSテンプレートで囲んで PNG にレンダリング"""
    from playwright.sync_api import sync_playwright

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    full_html = HTML_FRAME.format(css=CSS_TEMPLATE, body=html_body)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=2)
        page = context.new_page()
        page.set_content(full_html, wait_until="networkidle")
        page.screenshot(path=str(output_path), full_page=False, omit_background=False)
        browser.close()

    return output_path


def upload_image_to_x(client, image_path: Path | str) -> Optional[str]:
    """X(Twitter) に画像をアップロードして media_id を返す"""
    import os
    import tweepy

    api_v1 = tweepy.API(
        tweepy.OAuth1UserHandler(
            os.environ["X_API_KEY"],
            os.environ["X_API_SECRET"],
            os.environ["X_ACCESS_TOKEN"],
            os.environ["X_ACCESS_TOKEN_SECRET"],
        )
    )
    media = api_v1.media_upload(filename=str(image_path))
    return str(media.media_id)


def _clean_html_output(s: str) -> str:
    """Claudeが返したHTML本文から markdown コードフェンス・doctype・html/body
    タグ・余計な前置きを除去。「```html」がそのままテキストとして画像に
    出てしまう事故を防ぐ。
    """
    import re

    s = s.strip()

    # ```html\n...\n``` 形式のコードフェンスを除去
    fence_pattern = re.compile(r"^```\s*[a-zA-Z]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)
    m = fence_pattern.match(s)
    if m:
        s = m.group(1).strip()
    else:
        # 開始だけ ``` で終わりが無い、または逆のパターンにも対応
        if s.startswith("```"):
            first_nl = s.find("\n")
            if first_nl != -1:
                s = s[first_nl + 1 :]
            else:
                s = s.lstrip("`").lstrip("html").lstrip()
        if s.endswith("```"):
            s = s[: -3].rstrip()

    # 単独の "html" 行が残ってるケース（fence外しても残るパターン）
    s = re.sub(r"^\s*html\s*\n", "", s, count=1, flags=re.IGNORECASE)

    # <!DOCTYPE>, <html>, <head>...</head>, <body>, </body>, </html> を除去
    s = re.sub(r"<!DOCTYPE[^>]*>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<head[^>]*>.*?</head>", "", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"</?html[^>]*>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"</?body[^>]*>", "", s, flags=re.IGNORECASE)

    return s.strip()


def generate_html_body(text: str, format_type: str) -> str:
    """テキストとフォーマット名から、Claude経由でHTML本文を生成"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from generate import get_client, MODEL
    from prompts import IMAGE_HTML_PROMPT

    client = get_client()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": IMAGE_HTML_PROMPT.format(tweet_text=text, format_type=format_type)}],
    )
    for block in msg.content:
        if block.type == "text":
            return _clean_html_output(block.text)
    return ""


def render_tweet_image(text: str, format_type: str, output_path: Path | str) -> Path:
    """テキスト + フォーマットから一発で PNG を生成"""
    html_body = generate_html_body(text, format_type)
    return render_html_to_png(html_body, output_path)


if __name__ == "__main__":
    # テスト用: サンプル HTML を直接レンダリング
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", help="ツイートテキスト（生成テスト用）")
    parser.add_argument("--format", default="straight", help="フォーマットタイプ")
    parser.add_argument("--output", default="/tmp/tweet.png")
    parser.add_argument("--html", help="HTML本文を直接指定（Claude呼ばずにレンダリングだけテスト）")
    args = parser.parse_args()

    if args.html:
        out = render_html_to_png(args.html, args.output)
    else:
        out = render_tweet_image(args.text, args.format, args.output)
    print(f"saved: {out}")
