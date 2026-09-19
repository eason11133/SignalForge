# Research Method

## 研究單位

SignalForge 將輸入視為 hypothesis，而不是結論。每筆材料都應能回到 source、URL、query / facet、擷取時間、relevance 分類與歷史紀錄。

## 1. Decompose

長句先拆成幾個可搜尋維度：

- **actor**：誰遇到問題；
- **platform / context**：問題發生在哪裡；
- **failure**：什麼事情失敗或成本過高；
- **workaround**：人目前怎麼補洞；
- **source facet**：哪一類公開來源最可能留下痕跡。

拆解讓不同來源使用適合自己的 query，而不是要求所有平台理解同一個長句。

## 2. Retrieve from a source portfolio

候選來源包括 public discussions、GitHub、general web、reviews、products、articles / research。每個 adapter 應回報 status、query、count、error 與 trace；source failure 不得被靜默移除。

## 3. Classify relevance

判斷重點是 problem identity，而不是共同單字。檢查 actor、failure mechanism、context 與 workaround 是否相符；只有 URL、AI、GPT 等通用詞命中時，應留在 related / noise。

## 4. Deduplicate

依序使用 canonical URL、內容 fingerprint 與事件 identity。轉貼可以增加 `seen_count` 並補充 distribution context，但不能假裝成獨立 evidence。

## 5. Categorize

常用 lane 包括：

- human conversation；
- existing product / solution；
- published or technical material；
- workaround；
- counterevidence；
- coverage gap。

分類是為了後續閱讀與比較，不是把材料自動轉為 validation。

## 6. Preserve history

研究紀錄保留 `first_seen`、last seen、source、URL、search trace、`seen_count`、run id 與 failure metadata。再次研究時應更新歷史，而不是用新結果覆蓋所有舊脈絡。

## 7. Handoff

輸出交給 ChatGPT / Founder，回答：

- 哪些材料直接支持 hypothesis？
- 哪些只是 related？
- 有哪些反證？
- coverage 哪裡不足？
- 下一個最低成本的驗證行動是什麼？

SignalForge 不代替這些 judgment。

## Interpretation rules

| 觀察 | 可以說 | 不可以說 |
|---|---|---|
| 找到多筆相關討論 | 公開資料中存在可追溯 signal | 市場已驗證 |
| 單一來源回傳 0 筆 | 此 query / source 未找到結果 | 沒有需求 |
| 來源 timeout / blocked | coverage 不完整，需要 retry 或替代來源 | 市場不存在 |
| 多個 URL 指向同一事件 | 此事件有多個轉貼或入口 | 有多份獨立 evidence |
| 找到現有產品 | 存在替代方案或相鄰解法 | 競品證明一定有人付費 |

