# Demo Guide

## 審查者的 5 分鐘路徑

1. 從 [README](../README.md) 的定位與核心流程開始。
2. 閱讀 [Architecture](ARCHITECTURE.md) 的 run lifecycle 與 failure semantics。
3. 查看 `src/api/signalforge_research_persistence.py`，確認 `run_id`、idempotency 與持久化不是只有概念。
4. 查看 `src/processors/signalforge_founder_idea_loop.py` 與 `signalforge_research_backlog.py`，搜尋 `relevance`、`dedup`、`first_seen`、`seen_count`。
5. 執行兩個不需真實 credential 的代表性測試。

## Persistence demo

在 repository root 執行：

```bash
python tests/research_persistence_smoke.py
```

測試會使用 temporary directory，不讀寫 production runtime。預期驗證：

- start request 在 canonical work 完成前回傳；
- 同一方向的 active run 具有 idempotency；
- canonical start 不會重複呼叫；
- UI 再次查詢可用同一 `run_id` 讀回狀態；
- run registry 確實落盤；
- research infrastructure 不會寫入 market truth。

## Relevance regression demo

```bash
python tests/research_relevance_regression.py
```

此測試使用固定 fixture 與假的 transport，不呼叫外部網路。它檢查：

- discussion comment 與 root post 的不同語意；
- exact / related / counterevidence 邊界；
- optional source failure 仍顯示為 gap；
- 某來源已失敗時，不會對每個 query facet 反覆撞同一來源。

## UI walkthrough（完整應用環境）

1. 建立方向：`AI users struggle to give public links to their AI and keep the conversation going`。
2. 檢視 actor、platform、failure、workaround 與 source facets。
3. 啟動 research 並記錄畫面上的 `run_id`。
4. refresh browser，確認 UI reconnect 到原 run。
5. 比較 human discussion、solution、published material、counterevidence 與 gap。
6. 打開其中一筆 record，核對 source URL、search trace、first seen 與 seen count。
7. 確認 blocked / timeout source 沒有被顯示為「no demand」。
8. 把 brief 交給 ChatGPT / Founder，產生人工可審核的下一步驗證計畫。

## Demo 的誠實邊界

此案例只展示研究 pipeline 與資料可信度設計。它不證明該 hypothesis 已有市場、有人願意付費，或 SignalForge 能預測商業成功。

