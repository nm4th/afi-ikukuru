# INTJ × Pappy アフィリエイトコンテンツ

「偏りすぎたINTJおじさんの恋愛奮闘記」アカウント運用キット。
Claude APIでツイートを自動生成し、過去の投稿と被らない内容を毎回作る。

## セットアップ

```bash
pip install -r generator/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## 使い方

### 1日分のツイートを生成（4本）
```bash
python generator/generate.py daily
```
→ 朝・夕・夜①（誘導付き）・夜② の4カテゴリ分を一括生成

### 奮闘記シリーズを週次生成（7話）
```bash
python generator/generate.py series --theme "初めてのデートで失敗する話"
```
→ 昼枠の連載7話分をまとめて生成

### 特定カテゴリだけ生成
```bash
python generator/generate.py single --category aruaru_morning
python generator/generate.py single --category aruaru_evening
python generator/generate.py single --category weapon
python generator/generate.py single --category reflection
```

## 構成

```
content/          アカウント設計・運用ガイド
tweets/           サンプルツイート集（参考用）
generator/        ツイート自動生成スクリプト
  generate.py     メインスクリプト
  prompts.py      プロンプト定義
history/          過去の生成履歴（自動作成・ネタ被り防止用）
```
