# StockAgent 系統架構

本文件依目前程式碼繪製，重點在 **Agent（聊天）流程**。圖使用 Mermaid，GitHub 與 VS Code 的 Markdown 預覽可直接顯示。

---

## 1. 系統總覽

```mermaid
flowchart LR
    subgraph Browser["瀏覽器 127.0.0.1:5173（React）"]
        DASH["儀表板<br/>卡片 / 詳細頁 / 全部分析"]
        CHAT["聊天欄 ChatPanel<br/>回覆 + 確認卡片"]
    end

    VITE["Vite dev server<br/>/api 轉發（同源，不開 CORS）"]

    subgraph API["FastAPI 127.0.0.1:8000"]
        GUARD["安全層<br/>TrustedHost（擋偽造 Host）<br/>POST 只收 JSON（擋跨站觸發）"]
        R1["/api/watchlist"]
        R2["/api/reports"]
        R3["/api/analysis<br/>單檔同步 / 全清單背景＋共用鎖"]
        R4["/api/chat<br/>/api/chat/actions/{id}/confirm|cancel"]
    end

    subgraph Agent["聊天 Agent（chat/）"]
        SVC["ChatService<br/>agentic loop"]
        TOOLS["工具註冊表 + 三級權限"]
        ACT["待確認動作 PendingAction"]
    end

    subgraph Pipeline["分析 pipeline"]
        PIPE["analyze_stock<br/>抓資料 → 指標 → 訊號 → 價位 → 報告"]
    end

    FM[("FinMind API<br/>＋本機快取")]
    OAI[("OpenAI<br/>gpt-4o / gpt-4o-mini")]
    DB[("SQLite（WAL）<br/>清單 / 報告 / 聊天 / 待確認動作 / 摘要")]

    DASH --> VITE
    CHAT --> VITE
    VITE --> GUARD
    GUARD --> R1 & R2 & R3 & R4
    R1 --> DB
    R2 --> DB
    R3 --> PIPE
    R4 --> SVC
    SVC --> TOOLS
    TOOLS --> ACT
    TOOLS --> PIPE
    TOOLS --> DB
    ACT --> DB
    SVC <--> OAI
    PIPE --> FM
    PIPE --> OAI
    PIPE --> DB
```

---

## 2. Agent 單輪流程（`ChatService.send`）

一次使用者訊息 = 一輪。LLM 可連續呼叫工具多次，但**危險動作永遠不會在這裡執行**。

```mermaid
flowchart TD
    A([使用者送出訊息]) --> B{"有 OpenAI Key？<br/>訊息 1~2000 字？"}
    B -- 否 --> B1["503 / 422"]
    B -- 是 --> C["處理已過期的待確認動作<br/>（寫入「已過期」動作紀錄）"]
    C --> D["存入使用者訊息"]
    D --> E["組 context"]

    subgraph CTX["context 內容"]
        E1["system prompt：規則、權限說明"]
        E2["今天日期 + <b>目前追蹤清單（每輪即時查）</b> + 禁止事項引導"]
        E3["聊天摘要（若有）"]
        E4["未摘要的訊息原文<br/>含 [工具紀錄] [動作紀錄]"]
    end
    E --> CTX --> F

    F["呼叫 gpt-4o（帶 tools）<br/>已達 5 輪 → tool_choice=none"] --> G{"回覆帶 tool_calls？"}
    G -- 是 --> H["逐一分派工具（見第 3 節）<br/>結果以 role=tool 接回對話"]
    H --> F
    G -- 否 --> I{"回覆要使用者按確認，<br/>但沒有任何確認按鈕？"}
    I -- "是（第一次）" --> I1["加入 system 更正訊息，退回重做"]
    I1 --> F
    I -- "是（重做後仍然）" --> I2["回覆末尾加系統提示：<br/>本次沒有建立確認按鈕"]
    I -- 否 --> J
    I2 --> J["存 tool_log（只給 LLM 看）<br/>存 assistant 回覆"]
    J --> K{"未摘要訊息 ≥ 30 則？"}
    K -- 是 --> K1["gpt-4o-mini 把較舊 20 則<br/>併入摘要（失敗不影響回覆）"]
    K -- 否 --> L
    K1 --> L([回傳：回覆 + 本輪工具紀錄 + 待確認動作])
```

---

## 3. 工具分派與三級權限

```mermaid
flowchart TD
    T([LLM 呼叫工具]) --> T1{"工具存在？"}
    T1 -- "否（含禁止事項）" --> R1["rejected<br/>{ok:false, 沒有這個工具}"]
    T1 -- 是 --> T2{"參數是 JSON 且<br/>通過 pydantic 驗證？"}
    T2 -- 否 --> R2["rejected<br/>{ok:false, 參數錯誤}"]
    T2 -- 是 --> T3{"權限等級"}

    T3 -- "一般 auto" --> AU["立即執行 handler"]
    AU --> AU1["executed：{ok:true, data}<br/>或 failed：{ok:false, error}"]

    T3 -- "危險 confirm" --> CF["describe 前置檢查<br/>（例：要移除的股票是否在清單）"]
    CF -- 失敗 --> CF1["failed：{ok:false, error}<br/>不建立按鈕"]
    CF -- 通過 --> CF2["建立 PendingAction<br/>參數凍結、10 分鐘有效<br/><b>不執行</b>"]
    CF2 --> CF3["pending_confirmation<br/>告訴 LLM：需使用者按確認，你無法代為確認"]
```

| 等級 | 工具 / 操作 | 行為 |
|---|---|---|
| 一般 | `list_watchlist`、`add_watchlist_stock`、`get_latest_price`、`get_stock_report`、`get_report_history` | 直接執行 |
| 危險 | `remove_watchlist_stock`、`analyze_stock`（花 OpenAI 費用） | 只建立待確認動作，**人按按鈕才執行** |
| 禁止 | 分析整份清單、下單交易、改設定 / API Key | 不註冊成工具，system prompt 只提供文字引導 |

分級寫死在程式並有測試保護，不開放設定檔修改。

---

## 4. 危險動作的確認流程（人機協作）

```mermaid
sequenceDiagram
    actor U as 使用者
    participant UI as 聊天欄
    participant API as FastAPI
    participant S as ChatService
    participant L as gpt-4o
    participant DB as SQLite

    U->>UI: 「幫我分析 2454」
    UI->>API: POST /api/chat
    API->>S: send()
    S->>L: messages + tools
    L-->>S: tool_call analyze_stock(2454)
    S->>DB: 建立 PendingAction（不執行）
    S->>L: tool 結果：pending_confirmation
    L-->>S: 「請按畫面上的確認按鈕」
    S-->>UI: 回覆 + pending_actions
    UI-->>U: 顯示黃色確認卡片（倒數 10 分鐘）

    Note over U,UI: 只有人按按鈕才會呼叫確認端點；LLM 沒有確認工具

    U->>UI: 按「確認」
    UI->>API: POST /api/chat/actions/{id}/confirm
    API->>DB: 條件式 UPDATE pending→executing（連點只執行一次）
    API->>API: 執行 handler（分析共用鎖，忙碌回 409 並保留待確認）
    API->>DB: 存報告、動作改 done、寫入「動作紀錄」
    API-->>UI: 固定格式結果（不再經 LLM 轉述）
    UI-->>U: 顯示結果並通知儀表板重新載入
```

取消 → `cancelled`；超過 10 分鐘 → `expired`；兩者都寫入動作紀錄，下一輪 LLM 看得到。

---

## 5. 分析 pipeline（`analyze_stock`）

聊天的 `analyze_stock`、儀表板的「分析 / 全部分析」都走這條路。

```mermaid
flowchart LR
    P0([股票代號]) --> P1["fetch：FinMind<br/>股價 180 天、法人、融資券、<br/>月營收、財報、估值、除權息、新聞<br/>（快取：近期 1 小時，已定案永久，14 天清理）"]
    P1 --> P2["還原價<br/>（除權息、分割）"]
    P2 --> P3["技術指標<br/>MA、RSI6/12、KD、MACD、布林、ATR"]
    P3 --> P4["規則訊號<br/>技術 / 籌碼 / 基本面 / 新聞過濾"]
    P3 --> P5["支撐壓力<br/>高低點、指標、ATR 推算<br/>跳動單位、除權息前圖上價位、填息價"]
    P4 & P5 --> P6["事實清單 StockSignals"]
    P6 --> P7["gpt-4o Structured Outputs<br/>→ StockReport"]
    P7 --> P8{"價格檢查<br/>（不在價位清單、<br/>停損/目標/買賣點關係）"}
    P8 -- 有警告 --> P9["回饋警告自動修正 1 次"]
    P9 --> P8
    P8 -- 通過或已修正 --> P10[("存入 AnalysisReport<br/>含 model、prompt 版本、警告、token")]
```

---

## 6. 防止 LLM 說謊或出錯的機制（實測後加入）

| 問題（實測發現） | 機制 |
|---|---|
| LLM 宣稱「請按確認」但沒呼叫工具 | 後端檢查：要使用者按確認卻沒有任何確認按鈕 → 退回重做一次，仍如此則加系統提示 |
| 歷史只有文字，LLM 模仿「請按確認」 | 每輪存 `tool_log`，讓 LLM 看到過去確實呼叫過工具 |
| 使用者說「我已經按了」，LLM 就相信 | prompt：是否執行只以「動作紀錄」為準 |
| 儀表板上的變動，聊天不知道 | 每輪即時把目前追蹤清單放進 context |
| 報告價格不在價位清單、買賣點矛盾 | 報告價格檢查 + 自動修正 |
| 新聞內容夾帶指令 | prompt 規定工具結果是資料不是指令；危險動作由後端強制擋下 |
