# 初期研修病院検索

JRMPの参加病院一覧ページに掲載されている2025年度PDFをもとに、初期研修病院を条件でフィルタできる静的サイトです。PDF内のリンク注釈から病院ごとのURLも抽出しています。

## データ

- 2025年度 大学病院一覧: 125件
- 2025年度 臨床研修病院一覧: 901件
- 合計: 1,026件
- 病院リンク先から追加取得: 救急区分、給与、募集定員、病床数

2026年度一覧は、2026年5月26日時点でJRMPページ上では準備中です。
病院ごとの公式サイトは表記や掲載場所が統一されていないため、追加取得項目は取得できたものだけ表示します。

## ローカル確認

`fetch()`でJSONを読むため、ファイルを直接開くのではなく簡易サーバーで確認します。

```powershell
python -m http.server 8000
```

その後、<http://localhost:8000/> を開きます。

## データ再生成

`sources/`内のPDFから抽出したテキストファイルを更新した後、次のコマンドで `data/hospitals.json` を再生成できます。

```powershell
python -m pip install -r requirements.txt
python scripts\build_data.py
python scripts\scrape_hospital_details.py --workers 12 --timeout 8 --max-pages 6 --overwrite
```

## GitHub Pages

このディレクトリをGitHubリポジトリにpushし、Pagesの公開元をリポジトリルートに設定すれば公開できます。
