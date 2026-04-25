# MBTI × 恋愛ランキング（X Premium インプレッション収益）

INTJの分析好きキャラが、MBTI×恋愛をランキング形式で解説するXアカウント。
3つの投稿形式を使い分けてインプレッションを最大化する。

## 3つの形式

| 形式 | コマンド | 特徴 |
|------|---------|------|
| **5→1位は↓** | `--format tease` | リプで1位発表。インプレッション2倍 |
| **1→5位** | `--format straight` | 1ツイート完結。手軽に読める |
| **Tier表** | `--format tier` | 全16タイプをS〜D分類。保存されやすい |

## セットアップ

```bash
pip install -r generator/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## 使い方

```bash
# 1日分を一括生成（テーマ自動提案→形式自動選択→5本生成）
python generator/generate.py daily

# テーマ・形式を指定して1本
python generator/generate.py single --theme "付き合ったら一途すぎる男のMBTI" --format tease
python generator/generate.py single --theme "サプライズが得意なタイプトップ5" --format straight
python generator/generate.py single --theme "嫉妬深さ" --format tier

# テーマだけ5つ提案
python generator/generate.py themes

# INTJのつぶやき（23:00枠用）
python generator/generate.py mumble
```

## 構成

```
content/          アカウント設計・投稿スケジュール
tweets/           サンプルツイート（参考用）
generator/        ツイート自動生成スクリプト
history/          過去の生成履歴（ネタ被り防止）
```
