# MBTI × 恋愛ランキング（X Premium インプレッション収益）

INTJの分析好きキャラが、MBTI×恋愛をランキング形式で解説するXアカウント。
「5位→1位は↓」構造でリプライに誘導し、インプレッションを稼ぐ。

## セットアップ

```bash
pip install -r generator/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## 使い方

### 1日分を一括生成（テーマ提案→ランキング5本）
```bash
python generator/generate.py daily
```

### テーマ指定でランキング1本
```bash
python generator/generate.py single --theme "付き合ったら一途すぎる男のMBTI"
```

### テーマだけ5つ提案
```bash
python generator/generate.py themes
```

### INTJのつぶやき（23:00枠用）
```bash
python generator/generate.py mumble
```

## 構成

```
content/          アカウント設計・運用ガイド
tweets/           サンプルツイート（参考用）
generator/        ツイート自動生成スクリプト
history/          過去の生成履歴（ネタ被り防止）
```
