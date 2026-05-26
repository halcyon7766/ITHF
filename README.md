# 初期研修病院検索

JRMPの参加病院一覧ページに掲載されている2025年度PDFをもとに、初期研修病院を条件でフィルタできる静的サイトです。

## データ

- 2025年度 大学病院一覧: 125件
- 2025年度 臨床研修病院一覧: 901件
- 合計: 1,026件

2026年度一覧は、2026年5月26日時点でJRMPページ上では準備中です。

## ローカル確認

`fetch()`でJSONを読むため、ファイルを直接開くのではなく簡易サーバーで確認します。

```powershell
python -m http.server 8000
```

その後、<http://localhost:8000/> を開きます。

## データ再生成

`sources/`内のPDFから抽出したテキストファイルを更新した後、次のコマンドで `data/hospitals.json` を再生成できます。

```powershell
python scripts\build_data.py
```

## GitHub Pages

このディレクトリをGitHubリポジトリにpushし、Pagesの公開元をリポジトリルートに設定すれば公開できます。
