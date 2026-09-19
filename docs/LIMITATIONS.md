# Limitations

SignalForge 是 research infrastructure，不是市場預測器。以下限制在解讀輸出時必須保留：

## Coverage

- 公開搜尋無法涵蓋 private community、closed group、付費資料庫或未被索引的頁面。
- 登入牆、robots policy、rate limit、地區限制與 API 變動會造成 source gap。
- 平台搜尋排序與索引會變動，同一 query 在不同時間可能得到不同結果。

## Relevance

- 規則與語意判定都可能產生 false positive / false negative。
- 不同人可能對「同一問題」的邊界有合理分歧。
- related material 有研究價值，但不能自動升格為 core evidence。

## Deduplication

- URL normalization 無法識別所有 mirror、截圖、改寫與跨語言轉貼。
- 內容相似不一定代表同一事件；過度合併也會損失獨立訊號。

## Validation

- Relevance 不等於 validation。
- 討論熱度不等於 willingness to pay。
- GitHub activity、評論或產品存在，不等於市場規模或商業可行性。
- 此系統未宣稱使用者數、營收、準確率或成功預測紀錄。

## Failure semantics

- `SEARCH FAILED != NO MARKET SIGNAL`
- `0 results != no demand`
- `source blocked != no evidence exists`

失敗應被保存為 coverage metadata，並由後續 retry、替代來源或人工研究補足。

## Public repository scope

本 repo 包含 SignalForge production working tree 的完整 current source，但刻意不包含 runtime database、私人資料、credentials、cache、installer/export package、rollback bundle 與歷史 backup。外部來源仍需要使用者自行提供 API keys 與服務設定；完整排除規則與檔案計數記錄於 [`FULL_SOURCE_MANIFEST.md`](../FULL_SOURCE_MANIFEST.md)。
