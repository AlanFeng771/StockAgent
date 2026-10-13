# StockAgent

台股分析與追蹤 Agent。根據自訂的追蹤清單，從 FinMind 抓取股價、籌碼、基本面與新聞資料，先用**規則引擎**算出可重現的客觀訊號與支撐壓力價位，再交給 **ChatGPT** 在這些事實上做綜合判斷，產出含買賣點、目標價、停損與持有建議的報告。

網頁介面分成兩部分並排使用：

- **儀表板**：瀏覽追蹤清單與每檔股票的完整報告、技術/籌碼/基本面數據、支撐壓力與歷史報告
- **聊天助理**：具備工具呼叫（tool use）能力的 Agent，可以用對話管理追蹤清單、查行情、解讀報告；會改變狀態或花錢的動作必須由人按確認按鈕才執行

> 本專案只在本機執行，報告是規則訊號加 AI 判讀的參考，**不是投資建議**。

---

## 目錄

- [功能](#功能)
- [快速開始](#快速開始)
- [技術棧](#技術棧)
- [FinMind 資料](#finmind-資料)
- [系統設計](#系統設計)
  - [分析流程：規則先算事實，LLM 再判斷](#分析流程規則先算事實llm-再判斷)
  - [聊天 Agent 與工具權限](#聊天-agent-與工具權限)
  - [防止 LLM 出錯的機制](#防止-llm-出錯的機制)
  - [安全性](#安全性)
- [專案結構](#專案結構)
- [設定](#設定)
- [開發方式與測試](#開發方式與測試)
- [目前狀態與待辦](#目前狀態與待辦)

---

## 功能

| 類別 | 內容 |
|---|---|
| 追蹤清單 | 新增（驗證代號存在）、移除（軟刪除，重新加入可恢復）、儀表板卡片一覽 |
| 技術面 | 還原價計算 MA5/20/60、RSI6/12、KD(9,3)、MACD(12,26,9)、布林通道、ATR14、量比；均線/KD/MACD 交叉、超買超賣、爆量/量縮等訊號 |
| 籌碼面 | 三大法人買賣超（張）、連續買賣超天數、5 日合計、融資融券餘額與增減、券資比 |
| 基本面 | 月營收年增/月增與連續成長月數、單季 EPS 與年增率、近四季 EPS、毛利率/營益率、本益比與歷史百分位、股價淨值比、殖利率 |
| 支撐壓力 | 20/60 日高低點、均線與布林、ATR 推算價位；對齊台股跳動單位；除權息前的「圖上價位」區間；填息價與是否已填息 |
| 新聞 | 近 7 天新聞，排除論壇文章並去除不同來源的重複標題 |
| AI 報告 | 整體看法、買點/賣點、目標價、停損（含理由）、建議持有期間、是否適合長期、判斷依據、風險、資料限制、信心度 |
| 報告檢查 | 報告中的價格必須來自價位清單；檢查停損/目標/買賣點的相對關係，有問題自動回饋 LLM 修正一次 |
| 分析觸發 | 單檔分析、全部分析（背景執行並顯示進度，先跳確認視窗）；同時只允許一個分析 |
| 聊天助理 | 管理清單、查最近收盤行情、查報告與歷史報告、要求分析；危險動作需按確認；聊天紀錄定期摘要 |

---

## 快速開始

### 需求

- Python 3.12 與 [uv](https://docs.astral.sh/uv/)
- Node.js 22 以上
- [FinMind](https://finmindtrade.com/) 帳號的 API Token（免費會員即可）
- OpenAI API Key（產生報告與聊天用；沒有 Key 時仍可計算訊號，但不會產生報告、無法聊天）

### 1. 安裝與設定

```bash
git clone https://github.com/AlanFeng771/StockAgent.git
cd StockAgent

uv sync                  # 建立虛擬環境並安裝後端依賴
cp .env.example .env     # 編輯 .env，填入 FINMIND_API_TOKEN 與 OPENAI_API_KEY

cd frontend
npm install
```

### 2. 啟動

開兩個終端機：

```bash
# 後端（專案根目錄）
uv run uvicorn backend.app.main:app --reload
```

```bash
# 前端
cd frontend
npm run dev
```

打開 **http://127.0.0.1:5173** 即可使用。

- 後端 API 文件（Swagger）：http://127.0.0.1:8000/docs
- ⚠️ **不要**在 uvicorn 加上 `--host 0.0.0.0`：API 沒有登入機制，只設計給本機使用

### 3. 第一次使用

1. 在儀表板輸入股票代號（例如 `2330`）加入追蹤
2. 按卡片上的「分析」，等待數十秒產生報告（會呼叫 OpenAI）
3. 點卡片看完整報告，或在右側聊天問「2330 為什麼停損設在這裡？」

### 其他指令

```bash
uv run pytest                                           # 後端測試
uv run python backend/scripts/explore_finmind.py        # 查看 FinMind 額度與各資料集實際回應
uv run python backend/scripts/analyze_one.py 2330 --dry-run   # 命令列分析單檔（--dry-run 不呼叫 OpenAI）
cd frontend && npm run build                            # 前端型別檢查＋打包
```

---

## 技術棧

| 層 | 技術 | 用途 |
|---|---|---|
| 語言與環境 | Python 3.12、uv | 後端；`pyproject.toml` + `uv.lock` 鎖定依賴 |
| 資料來源 | FinMind SDK 2.0 | 台股股價、籌碼、基本面、新聞 |
| 資料處理 | pandas | 還原價、技術指標、訊號計算（指標自行實作，`ta` 套件僅作測試對照） |
| LLM | OpenAI Python SDK（gpt-4o、gpt-4o-mini） | 報告用 Structured Outputs 強制 JSON 格式；聊天用 function calling；摘要用 gpt-4o-mini |
| 後端 | FastAPI、Uvicorn | REST API；`/docs` 自帶 Swagger |
| 資料庫 | SQLite + SQLAlchemy 2（WAL 模式） | 追蹤清單、報告、聊天紀錄、待確認動作、聊天摘要 |
| 設定 | pydantic-settings | 所有可調參數集中在 `backend/app/config.py`，由 `.env` 覆寫 |
| 前端 | React 19、Vite 8、TypeScript、Tailwind CSS 4 | 儀表板與聊天欄；`react-markdown` 顯示聊天回覆 |
| 測試 | pytest（後端，含 FastAPI TestClient） | 外部服務（FinMind、OpenAI）一律 mock |
| 排程（延後） | APScheduler | 每日收盤後自動分析，尚未啟用 |

---

## FinMind 資料

### 用到的資料集

| 資料集 | 用途 | 抓取範圍 |
|---|---|---|
| `taiwan_stock_info` | 股票名稱、產業、上市/上櫃、股票或 ETF（決定跳動單位） | 全市場 |
| `taiwan_stock_daily` | 日 K（開高低收量） | 近 180 天 |
| `taiwan_stock_dividend_result` | 除權息結果，用於自行計算還原價、填息價 | 近 180 天 |
| `taiwan_stock_split_price` | 分割/面額變更，用於還原價 | 近 180 天（全市場） |
| `taiwan_stock_institutional_investors` | 三大法人買賣超 | 近 60 天 |
| `taiwan_stock_margin_purchase_short_sale` | 融資融券 | 近 60 天 |
| `taiwan_stock_month_revenue` | 月營收 | 近 1130 天（約 3 年，計算連續成長月數） |
| `taiwan_stock_financial_statement` | 綜合損益表（EPS、毛利、營業利益） | 近 900 天 |
| `taiwan_stock_per_pbr` | 本益比、股價淨值比、殖利率 | 近 365 天（計算本益比歷史百分位） |
| `taiwan_stock_news` | 個股新聞 | 近 7 天 |
| `taiwan_stock_trading_date` | 交易日曆 | 已實作，供之後的自動排程使用 |

抓取天數集中在 `backend/app/signals/config.py` 的 `LookbackDays`。

### 實測得到的限制與處理方式

| 事實（以免費會員實測） | 處理方式 |
|---|---|
| 額度：登入 600 次/小時（未登入 300） | 本機快取：近期資料 1 小時有效，區間結束日早於 3 天前視為已定案永久有效，14 天未使用自動清除 |
| 還原股價 `taiwan_stock_daily_adj`、即時報價、全市場減資為**付費限定** | 用除權息結果與分割資料**自行計算還原價**；聊天查價格回最近一個交易日收盤，並標明「非即時」 |
| Token 無效時回 HTTP 400 `Token is illegal.` | 歸類為認證錯誤，與額度用完、付費限定分開提示 |
| 除權息資料的 `before_price` 是前一日收盤，不是除權息前參考價 | 還原因子改用 `reference_price ÷ before_price` |
| 月營收的 `date` 是公布月份 | 改用 `revenue_year` / `revenue_month` 判斷所屬期間 |
| 財報 EPS 是單季值 | 近四季 EPS 自行加總連續 4 季 |
| 三大法人單位是「股」，融資融券是「張」 | 統一換算成張 |
| 籌碼資料通常比股價晚一天 | 報告事實清單分別標示各資料來源的最新日期 |
| 股票基本資料有重複列、名稱含空白或 `*`、日期為字串 `"None"` | 取最新日期的列、清理名稱、日期解析失敗視為缺值 |

---

## 系統設計

更完整的流程圖（Mermaid）見 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)；開發決策與每個階段的規格見 [docs/PLAN.md](docs/PLAN.md)。

### 分析流程：規則先算事實，LLM 再判斷

```
FinMind（快取）→ 還原價 → 技術指標 → 規則訊號（技術/籌碼/基本面/新聞）
                                  └→ 支撐壓力價位（跳動單位、圖上價位、填息價）
                                          ↓
                               事實清單 StockSignals（JSON）
                                          ↓
                    gpt-4o Structured Outputs → StockReport
                                          ↓
                 價格檢查（不在價位清單 / 停損、目標、買賣點關係）
                        有警告 → 回饋 LLM 自動修正 1 次
                                          ↓
           存入 SQLite（含 model、prompt 版本、警告、token 用量，可追溯）
```

- **規則層**負責可重現的計算：同樣的資料一定算出同樣的指標與價位
- **LLM 層**只在事實清單上推論，所有價格必須取自價位清單，由程式事後驗證
- **指標用還原價**計算，避免除權息造成均線、高低點失真；支撐壓力另外標出除權息前在 K 線圖上看到的價位，兩者之間視為壓力/支撐區
- **Prompt 與程式分離**：放在 `backend/app/llm/prompts/<名稱>/*.md`；版本號是檔案內容的雜湊值，每份報告都記錄用了哪個 prompt 版本

### 聊天 Agent 與工具權限

聊天不只是問答，而是一個 agentic loop：ChatGPT 決定要呼叫哪些工具，後端依**權限等級**決定能不能執行，結果再交回 ChatGPT，最多連續 5 輪。

#### 三級權限

| 等級 | 工具 / 操作 | 行為 |
|---|---|---|
| **一般** | `list_watchlist` 查清單<br>`add_watchlist_stock` 加入追蹤<br>`get_latest_price` 查最近收盤<br>`get_stock_report` 查報告<br>`get_report_history` 查歷史報告 | 直接執行，回覆中說明做了什麼 |
| **危險** | `remove_watchlist_stock` 移除追蹤<br>`analyze_stock` 分析（會花 OpenAI 費用） | **後端不執行**，只建立「待確認動作」；聊天欄出現確認卡片，**只有人按按鈕才執行** |
| **禁止** | 分析整份清單、下單交易、修改設定或 API Key | **不註冊成工具**（LLM 無法呼叫），system prompt 只提供文字引導，例如「請到儀表板按全部分析」 |

權限等級寫死在程式並有測試保護，不開放設定檔修改，避免改錯設定讓危險動作自動執行。

#### 危險動作的確認流程

```
使用者：「幫我分析 2454」
  → ChatGPT 呼叫 analyze_stock(2454)
  → 後端前置檢查（代號存在）→ 建立 PendingAction（參數凍結、10 分鐘有效），不執行
  → ChatGPT 回覆「請按畫面上的確認按鈕」
  → 聊天欄顯示確認卡片（倒數計時）
使用者按「確認」
  → POST /api/chat/actions/{id}/confirm
  → 條件式 UPDATE 搶執行權（連點只會執行一次）→ 執行分析（與其他分析共用鎖）
  → 固定格式的結果寫入聊天「動作紀錄」，儀表板自動重新載入
```

- ChatGPT **沒有**「確認」這個工具，無法自己確認；也不接受用文字回覆「確認」
- 按「取消」或過期，都會寫入動作紀錄，下一輪 ChatGPT 看得到
- 確認後的結果直接用固定格式顯示（報告摘要、買賣點、目標、停損），不再經過 LLM 轉述，避免數字被改寫

#### 送給 ChatGPT 的內容

| 內容 | 說明 |
|---|---|
| System prompt | 回答原則（只根據工具結果、價格非即時要標日期）、權限規則、安全規則 |
| 即時資訊 | 今天日期、**目前追蹤清單（每輪即時查詢）**、禁止事項的引導文字 |
| 聊天摘要 | 舊訊息由 gpt-4o-mini 濃縮：未摘要訊息達 30 則時，把較舊的 20 則併入摘要 |
| 近期原文 | 尚未摘要的訊息，含 `[工具紀錄]`（每輪實際呼叫的工具）與 `[動作紀錄]`（確認、取消、過期結果） |

### 防止 LLM 出錯的機制

以下大多是實際使用時發現問題後加入的：

| 問題 | 機制 |
|---|---|
| ChatGPT 說「請按確認」，但根本沒呼叫工具（畫面沒有按鈕） | 後端檢查：回覆要使用者按確認、卻沒有任何確認按鈕 → 退回重做一次；仍然如此就在回覆末尾加上系統提示 |
| 歷史只存文字，ChatGPT 模仿過去的「請按確認」而不呼叫工具 | 每輪把實際呼叫的工具存成 `tool_log`（只給 LLM 看），歷史與實際情況一致 |
| 使用者說「我已經按了」，ChatGPT 就相信 | 是否執行只以「動作紀錄」為準 |
| 在儀表板上做的變動，聊天不知道 | 每輪即時把目前追蹤清單放進 context |
| 報告價格不在價位清單、目標價低於買點等矛盾 | 程式驗證價格與關係，自動回饋修正 |
| 新聞內容夾帶指令（prompt injection） | Prompt 規定工具結果是資料不是指令；危險動作由後端強制擋下，不受 LLM 影響 |

### 安全性

API 沒有登入機制，因此限制只能在本機使用：

| 防護 | 做法 |
|---|---|
| 只接受本機連線 | uvicorn 與 Vite 都只綁 `127.0.0.1` |
| DNS rebinding | `TrustedHostMiddleware` 只接受 `127.0.0.1`、`localhost` 的 Host 標頭，否則回 400 |
| 惡意網頁在背景觸發分析、花費額度 | 不開 CORS（前端經 Vite proxy 同源呼叫）；所有 POST 必須是 `application/json`，表單或純文字請求回 415 |
| 重複分析 | 單檔與全部分析共用一把鎖，忙碌時回 409 |
| 金鑰 | `.env` 不納入版控；程式與腳本不印出金鑰內容 |

---

## 專案結構

```
StockAgent/
├── backend/
│   ├── app/
│   │   ├── config.py              # 全專案設定（唯一來源）
│   │   ├── main.py                # FastAPI 入口（create_app 可注入相依，方便測試）
│   │   ├── data_sources/          # FinMind client、快取、股票基本資料
│   │   ├── indicators/            # 還原價、技術指標
│   │   ├── signals/               # 技術/籌碼/基本面訊號、支撐壓力、跳動單位、新聞過濾、門檻設定
│   │   ├── llm/                   # 報告產生、報告 schema、prompt 載入
│   │   │   └── prompts/           # stock_report / chat / chat_summary 的 .md prompt
│   │   ├── pipeline/              # 抓資料 → 分析 → 報告；分析工作管理（背景、鎖）
│   │   ├── chat/                  # 聊天 Agent：工具註冊表、待確認動作、報價、agentic loop
│   │   ├── db/                    # SQLAlchemy 模型與存取函式
│   │   └── api/                   # REST 路由、請求/回應格式、錯誤對應
│   ├── scripts/                   # 實測與驗證腳本（打真實 API）
│   └── tests/                     # pytest
├── frontend/
│   └── src/
│       ├── pages/                 # Dashboard、StockDetail
│       ├── components/            # 卡片、報告、價位、訊號、聊天欄、確認視窗…
│       ├── api/                   # 呼叫後端
│       ├── lib/                   # 格式化（紅漲綠跌）
│       └── types/                 # 對應後端的型別
├── data/                          # SQLite 與 FinMind 快取（不納入版控）
└── docs/
    ├── PLAN.md                    # 開發計畫、決策紀錄、各階段規格
    └── ARCHITECTURE.md            # 架構與 Agent 流程圖
```

---

## 設定

所有設定集中在 `backend/app/config.py`，可在 `.env` 覆寫（欄位名轉大寫即為環境變數名稱）。完整清單見 [.env.example](.env.example)。

| 設定 | 預設 | 說明 |
|---|---|---|
| `FINMIND_API_TOKEN` | — | 必填 |
| `OPENAI_API_KEY` | — | 沒有時報告為「未產生」、聊天無法使用 |
| `OPENAI_MODEL` | `gpt-4o` | 產生報告的模型 |
| `OPENAI_REPAIR_ATTEMPTS` | `1` | 報告有價格警告時自動修正次數 |
| `CHAT_MODEL` | `gpt-4o` | 聊天模型 |
| `CHAT_SUMMARY_MODEL` | `gpt-4o-mini` | 聊天摘要模型 |
| `CHAT_MAX_TOOL_ROUNDS` | `5` | 一次回答最多連續呼叫工具輪數 |
| `CHAT_RECENT_MESSAGES` / `CHAT_SUMMARY_EVERY` | `10` / `20` | 摘要後保留的原文則數 / 每多少則新訊息摘要一次 |
| `CHAT_ACTION_TTL_MINUTES` | `10` | 危險動作確認的有效時間 |
| `CACHE_TTL_SECONDS` / `CACHE_MAX_AGE_DAYS` | `3600` / `14` | FinMind 快取有效時間 / 自動清除天數 |

分析門檻（例如爆量倍數 2 倍、RSI6 80/20、法人連買 3 天、營收年增 20%）屬於分析邏輯，集中在 `backend/app/signals/config.py`。

---

## 開發方式與測試

採 **SDD + TDD**：每個階段先寫規格（寫在模組 docstring 與 PLAN.md），依規格寫測試並確認失敗，再實作到測試通過，最後用真實 API 實測。

- 後端測試約 470 個，外部服務（FinMind、OpenAI）一律 mock，不消耗額度
- 技術指標與券商 App 對照驗證；跳動單位依證交所營業細則
- 前端以人工驗收為主，`npm run build` 進行型別檢查

```bash
uv run pytest
```

---

## 目前狀態與待辦

已完成：資料抓取與快取、還原價與指標、規則訊號與支撐壓力、AI 報告、資料庫、REST API、聊天 Agent 與工具權限、儀表板、聊天介面。

待辦：

- [ ] 錯誤提示與使用體驗打磨（FinMind / OpenAI 額度用完的提示等）
- [ ] OpenAI 費用上限
- [ ] 每日自動排程（需先實測各資料集每天的更新時間）
- [ ] K 線圖
- [ ] 上櫃股票跳動單位規則驗證、減資資料

---

## 免責聲明

本專案僅供個人研究與學習。報告由規則計算與 AI 判讀產生，可能有錯誤或過時資訊，不構成任何投資建議，投資決策請自行判斷並承擔風險。
