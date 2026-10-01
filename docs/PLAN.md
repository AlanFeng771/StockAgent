# 台股自動分析＋追蹤 Agent — 實作計畫

## Context

使用者想要一個能根據自訂股票清單，每天自動產生分析報告的 agent，報告需包含買點、賣點、風險、是否為長期投資、判斷依據與重要指標，並透過一個可互動的網頁（聊天介面＋儀表板）查看與詢問。

專案位置 `c:\Users\user\Desktop\Projects\StockAgent`，從零開始設計（Stage 0 建立骨架與 git repo），不需相容任何既有程式碼。

經過發散討論與查證（FinMind 官網確認其免費方案涵蓋股價/三大法人/融資融券/財報/月營收/新聞等資料集，且有 Python SDK），已與使用者拍板以下方向：

- **資料來源**：FinMind（免費、涵蓋技術/籌碼/基本面/消息面，免爬蟲）
- **分析面向**：技術面＋籌碼面＋基本面＋消息面全都要
- **判斷邏輯**：兩層式混合架構 — 規則引擎算出確定性結構化訊號，再交給 ChatGPT API（OpenAI）做綜合判斷與推論（而不只是把數字排版成文字），產出買點/賣點/風險/是否長期投資等結論與報告
- **排程**：每天自動執行，**本機常駐服務**（非雲端部署），因為免費、設定最簡單，使用者電腦有開機即可
- **介面**：本機網頁，**聊天介面＋報告儀表板**雙模式並存
- **LLM**：使用 OpenAI ChatGPT API；使用者**已有 API Key**，可直接串接開發，不需等待申請
- **聊天介面具備工具呼叫（tool use）能力**：聚焦在「股票資訊查詢」與「介面操作（清單管理）」兩類（新增/移除/列出追蹤清單、查即時基本資訊、查分析報告），其他情境（跨股票比較、排名彙整、排程狀態查詢）先不做，避免範圍發散
- **Python 環境管理**：使用 `uv`（而非傳統 venv+pip），專案用 `pyproject.toml` 管理依賴
- **開發流程**：採用 **SDD（規格驅動）+ TDD（測試驅動）**——每個階段先定規格，再依規格寫測試，最後實作到測試全過，不跳過先寫規格與測試這兩步

目標是先用最小可行流程驗證「單一股票能跑出一份正確報告」，再逐步疊加資料庫、排程、API、前端，避免一開始鋪陳過大架構；同時把整體計畫拆成可獨立檢驗、獨立驗收的階段任務，方便追蹤進度。

---

## 技術棧總結

| 項目 | 選擇 | 理由 |
|---|---|---|
| 資料來源 | FinMind（`uv add FinMind`） | 免費、台股資料最齊全、免爬蟲 |
| 判斷邏輯 | 規則引擎（Python）→ 結構化訊號 → ChatGPT API 綜合判斷 | 規則層負責可重現的客觀事實計算；LLM 負責在事實基礎上做推論判斷（買點/賣點/風險/長期與否）並組織成人類可讀敘述，而非單純文字排版 |
| 排程 | APScheduler，內嵌 FastAPI process | 本機常駐，免額外部署 |
| 資料庫 | SQLite | 單檔、免安裝、個人專案足夠 |
| 後端 | FastAPI | 成熟、`/docs` 自帶 Swagger 方便測試 |
| 前端 | React + Vite + TypeScript + TailwindCSS | 聊天介面需要客製互動（串流、卡片式報告），SPA 生態最成熟；Streamlit 類工具客製彈性不足 |
| 版控 | git（本機 `git init`） | 依使用者既有偏好 |
| Python 環境/套件管理 | `uv` | 依使用者指定；比venv+pip快，`pyproject.toml`+`uv.lock`一次管好環境與依賴版本鎖定 |
| 開發流程 | SDD + TDD | 依使用者指定；每階段先定規格、依規格寫測試、再實作到測試通過，確保行為可驗證、可回歸測試 |

---

## 專案目錄結構

```
StockAgent/
├── .gitignore
├── .env.example
├── README.md
├── pyproject.toml                 # uv管理的依賴清單（取代requirements.txt）
├── uv.lock                        # uv自動產生的鎖定檔，需進版控
│
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI入口 + APScheduler啟動(lifespan)
│   │   ├── config.py              # 設定統一管理處（pydantic-settings讀.env）：外部服務key、DB、快取等執行參數；分析門檻值另放signals/config.py
│   │   ├── data_sources/
│   │   │   ├── finmind_client.py  # 封裝FinMind SDK，每dataset一個method
│   │   │   └── cache.py           # FinMind原始回應的本機檔案快取
│   │   ├── indicators/
│   │   │   ├── price_adjust.py    # 用除權息/面額變更自行計算還原股價（FinMind還原股價為付費限定）
│   │   │   ├── technical.py       # MA/MACD/KD/RSI/布林通道/量能（輸入為還原股價）
│   │   │   ├── chip.py            # 三大法人、融資融券規則訊號
│   │   │   └── fundamental.py     # 本益比/殖利率/EPS成長/月營收YoY,MoM/ROE
│   │   ├── signals/
│   │   │   ├── config.py          # 規則門檻值集中定義處
│   │   │   └── signal_builder.py  # 彙整成StockSignals結構化訊號(pydantic model)
│   │   ├── llm/
│   │   │   ├── prompt_templates.py
│   │   │   └── report_generator.py # 組prompt→呼叫ChatGPT API做綜合判斷→解析JSON報告
│   │   ├── pipeline/
│   │   │   └── analyze_stock.py   # 串接全流程，供CLI/排程/API共用，不耦合DB
│   │   ├── scheduler/
│   │   │   └── jobs.py            # 每日定時跑全清單，單支失敗不影響其他
│   │   ├── chat/
│   │   │   ├── chat_service.py    # agentic loop：送訊息給ChatGPT、分派tool_calls、組裝tool回應
│   │   │   └── tools.py           # 工具schema定義＋分派表（見下方設計）
│   │   ├── db/
│   │   │   ├── database.py
│   │   │   ├── models.py
│   │   │   └── crud.py
│   │   └── api/
│   │       ├── routes_watchlist.py
│   │       ├── routes_reports.py
│   │       ├── routes_analysis.py
│   │       └── routes_chat.py
│   ├── scripts/
│   │   ├── explore_finmind.py     # Stage1用：人工探索FinMind真實回傳格式，非TDD範圍
│   │   └── analyze_one.py         # Stage3/4用：CLI單股驗證腳本
│   └── tests/
│       ├── test_config.py
│       ├── test_finmind_client.py
│       ├── test_finmind_cache.py
│       ├── test_price_adjust.py
│       ├── test_indicators_technical.py
│       ├── test_indicators_chip.py
│       ├── test_indicators_fundamental.py
│       ├── test_signal_builder.py
│       ├── test_report_generator.py
│       ├── test_pipeline.py
│       ├── test_crud.py
│       ├── test_scheduler_jobs.py
│       ├── test_api_watchlist.py
│       ├── test_api_reports.py
│       └── test_chat_service.py
│
├── data/
│   ├── stockagent.db              # git忽略
│   └── cache/                     # FinMind原始資料快取，git忽略
│
└── frontend/
    ├── index.html / package.json / vite.config.ts / tailwind.config.js
    └── src/
        ├── api/                   # 封裝fetch呼叫後端
        ├── pages/
        │   ├── Dashboard.tsx      # 儀表板模式
        │   └── Chat.tsx           # 聊天模式
        ├── components/
        │   ├── StockCard.tsx / ReportDetail.tsx
        │   ├── WatchlistManager.tsx / ChatWindow.tsx
        └── types/
```

---

## 核心設計重點

### 規則訊號層（第一層，確定性可測試）
把原始指標轉成結構化訊號，例如：
```json
{"type": "golden_cross", "detail": "MA5上穿MA20", "date": "2026-09-28"}
{"type": "foreign_buy_streak", "days": 3}
{"type": "revenue_yoy_growth", "value": 0.23, "threshold": 0.20, "triggered": true}
```
所有門檻值（連續買賣超天數、YoY成長門檻等）集中在 `signals/config.py` 管理，不寫死散落各處；具體數值在Stage2開發時與使用者一起拍板。

### LLM判斷與報告層（第二層）
LLM 在這層的角色是**根據結構化事實做判斷推論**，不是把數字套版成文字：
- System prompt 要求 ChatGPT 針對給定的訊號與新聞做綜合研判，輸出固定 JSON 欄位：買點、賣點、風險、是否長期投資(布林+理由)、判斷依據、信心程度——「是否長期投資」「判斷依據」這類欄位本身就需要 LLM 做推論與權衡，不是規則引擎能直接算出的數字
- 只把第一層算好的「事實清單」＋新聞摘要餵給 LLM，明確指示只能根據提供的事實做推論、不得自行假設未提供的數據，降低幻覺，但判斷與取捨仍由 LLM 完成
- 使用 OpenAI 的 Structured Outputs / JSON mode（`response_format={"type": "json_schema", ...}`）確保回傳格式穩定可解析，避免額外寫容錯很重的文字解析邏輯
- `OPENAI_API_KEY` 若未設定或呼叫失敗時，pipeline 仍可完成到訊號產出，報告標記 `llm_status="pending"`/`"failed"`，不讓整條 pipeline 因 LLM 這步出錯而跑不動

### 聊天層 = 具備工具呼叫（tool use）能力的 Agent

聊天不是單純「組context→問LLM→回文字」的問答，而是讓 ChatGPT 透過 **function calling** 實際執行後端操作。`chat_service.py` 要實作一個 agentic loop（對應 OpenAI Chat Completions API 的工具呼叫流程）：

1. 把使用者訊息＋已定義的工具（`tools` 參數，每個工具是 `{type:"function", function:{name, description, parameters(JSON schema)}}`）送給 ChatGPT
2. 若回傳的 assistant message 帶有 `tool_calls`（可能一次多筆），`chat_service` 依每筆 `tool_call.function.name` 查表分派呼叫對應的後端函式（直接重用 `db/crud.py`、`pipeline/analyze_stock.py`、`data_sources/finmind_client.py` 既有邏輯，不重寫一份），把執行結果包成 `role="tool"`、帶對應 `tool_call_id` 的訊息，加回對話歷史
3. 把更新後的對話歷史再送回 ChatGPT，重複直到 assistant message 不再帶 `tool_calls`、而是回傳最終文字回覆為止，再把回覆與過程中執行的動作一併回給前端

**初版工具集（聚焦兩大類，其他情境先不做）：**

| 情境分類 | 使用者可能的說法範例 | 對應工具 | 對應後端邏輯 |
|---|---|---|---|
| 介面操作（清單管理） | 「把2454加入追蹤」「把2330移除」「我現在清單有哪些」 | `add_watchlist_stock`／`remove_watchlist_stock`／`list_watchlist` | `crud.add_watchlist()`／`crud.soft_delete_watchlist()`／`crud.get_active_watchlist()` |
| 股票資訊查詢 | 「台積電現在多少錢」「2454基本資料」「台積電今天的分析報告」 | `get_latest_price(stock_id)`／`get_stock_report(stock_id, date?)` | `QuoteProvider`（MVP實作＝`finmind_client.get_price`取最近一筆收盤）／`crud.get_report()` |

> **報價不是即時價**：FinMind 即時報價 `taiwan_stock_tick_snapshot` 為 sponsor 付費限定（SDK docstring 註明），免費方案只能取最近交易日收盤。`get_latest_price` 回傳必須帶「YYYY-MM-DD 收盤」資料日期，回覆不得描述成「現在」價格。介面抽象成 `QuoteProvider`，之後升級 sponsor 只需替換實作。

**架構原則**：`chat/tools.py` 用「註冊表」模式設計：每個工具是 `{name, description, input_schema(pydantic model), handler}` 的一筆註冊項，`chat_service` 的 agentic loop 只依工具名稱查表分派，之後若要加新工具只需新增註冊項，不用動迴圈邏輯——但目前刻意不多做，等MVP跑通、使用者實際用過覺得有需要再擴充。

**設計原則（執行安全性）**：
- 讀取類工具（`list_watchlist`/`get_latest_price`/`get_stock_report`）可讓 ChatGPT 自由呼叫，無需使用者二次確認
- **會改變狀態的工具**（`add_watchlist_stock`/`remove_watchlist_stock`，尤其是刪除）執行後，回覆需明確告知使用者「已執行了什麼操作」；是否要在刪除前額外要求二次確認列入待確認事項
- 日常分析報告的取得仍**優先讀當天已算好的結果**（`get_stock_report`），不透過聊天隱式觸發即時重新分析

### 資料庫 Schema（SQLite + SQLAlchemy）
- `Watchlist`：stock_id, stock_name, is_active（軟刪除）
- `AnalysisReport`：stock_id + analysis_date（唯一鍵，MVP階段同日覆蓋；analysis_date 一律為交易日）、raw_signals_json、raw_indicators_json、llm_report_json、llm_status、data_freshness_json（各dataset最新資料日期）
- （以下兩表隨 Stage 6 延後，Stage 5 先不建）`AnalysisRun`：as_of_date、status（`success`/`skipped`/`failed`）、calendar_source（`calendar`/`weekday_fallback`）、reason——區分「確定休市而跳過」與「出錯而失敗」，補跑只重跑 failed/缺漏的交易日
- `TradingCalendar`：本地快取的交易日曆（每天最多向FinMind更新一次）
- `ChatMessage`：session_id, role, content, related_stock_id

### API 端點草案
```
GET/POST/DELETE /api/watchlist[/{stock_id}]
POST /api/analysis/run            # 全清單手動觸發
POST /api/analysis/run/{stock_id} # 單股手動觸發
GET  /api/reports/{stock_id}/latest
GET  /api/reports/{stock_id}/history?start=&end=
GET  /api/reports/latest          # 全清單各股最新一份報告（附analysis_date），假日/當日尚未產出時回最近交易日的報告
POST /api/chat                    # response需包含最終文字回覆 + 過程中執行的工具動作列表(actions_taken)
GET  /api/chat/history?session_id=
GET  /api/health
GET  /api/scheduler/status        # 隨 Stage 6 延後
```

---

## 開發方法論：SDD + TDD

每個開發階段（見下方「階段性任務」）都遵循同一套流程，不跳步：

1. **定規格（Spec）**：動手寫程式前，先用文字明確定義這個階段要實作的模組/函式的輸入、輸出、邊界條件與錯誤處理方式，具體到「看了規格就能直接寫出測試」的程度。本計畫已在每個階段先給出規格要點，實作前可視需要再補細節，但不省略這一步。
2. **依規格寫測試（Test First）**：根據規格撰寫 `pytest` 測試案例——純邏輯（indicators/signals）用unit test搭配構造好的假資料；牽涉外部服務（FinMind、OpenAI）的一律mock，不在自動化測試中打真實API（避免額度消耗與測試不穩定）。此時測試應該是失敗的（還沒實作）。
3. **實作到測試全過（Implement）**：寫最小必要的程式碼讓測試通過，通過後再視需要做輕量重構，不擴張規格外的功能。
4. **驗收（Definition of Done）**：每個階段都列出明確完成條件，全數滿足才算結束、可以推進下一階段——這是讓整個計畫可追蹤、可驗收的具體機制。

**例外（前端）**：React 介面的互動與視覺驗收用「啟動 `npm run dev` 後人工在瀏覽器操作確認」為主，不強制每個元件都寫自動化測試——前端在 MVP 階段用 TDD 的投資報酬率偏低，這點先用人工驗收取代，之後若前端邏輯變複雜（例如聊天狀態管理）再評估要不要補 Vitest/Testing Library。

---

## 環境建置（使用 uv）

```bash
cd "c:\Users\user\Desktop\Projects\StockAgent"
git init
uv init --name stockagent --python 3.12    # 產生 pyproject.toml / .python-version
uv add fastapi "uvicorn[standard]" apscheduler sqlalchemy pydantic pydantic-settings python-dotenv FinMind openai pandas ta
uv add --dev pytest pytest-mock httpx
```

- `uv add` 會自動建立/更新 `.venv`、寫入 `pyproject.toml`、鎖定版本到 `uv.lock`，不需要再手動 `python -m venv` 或維護 `requirements.txt`
- 執行指令一律透過 `uv run`，確保用到專案的 `.venv`：
  - `uv run pytest`
  - `uv run uvicorn backend.app.main:app --reload`
  - `uv run python backend/scripts/analyze_one.py 2330`

`.env.example`：
```
FINMIND_API_TOKEN=your_finmind_token_here
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o   # 依實際成本/品質需求挑選，開發時請對照OpenAI官方當前可用模型列表確認型號是否仍有效
DAILY_ANALYSIS_HOUR=17
DAILY_ANALYSIS_MINUTE=0
DATABASE_URL=sqlite:///./data/stockagent.db
```

`.gitignore`：`.venv/ __pycache__/ *.pyc .env data/*.db data/cache/ node_modules/ frontend/dist/ .pytest_cache/`

完成骨架後執行初始 commit：`git add .` → `git commit -m "chore: initial project scaffold"`

**Token 申請**：FinMind 到 https://finmind.github.io/ 免費註冊取得 token；OpenAI API Key 使用者已持有，直接填入 `.env` 即可。

---

## 階段性任務（Stage-based Tasks，每階段依 SDD+TDD 流程執行）

### Stage 0：專案骨架 ✅ 已完成（commit `05d53ed`）
- **規格**：專案需可重現——任何人 clone 下來，`uv sync` 一個指令就能還原開發環境
- **實作**：目錄結構、`uv init`＋套件安裝、`.env.example`、`.gitignore`、README、git init＋初始commit
- **驗收**：
  - [x] 全新環境下 `uv sync` 成功安裝所有依賴
  - [x] `uv run pytest` 可執行（無測試案例時顯示 0 collected，不報錯）
  - [x] git log 有初始 commit

### Stage 1：FinMind 資料擷取層 ✅ 已完成
- **規格**：定義 `finmind_client.py` 各method的輸入輸出contract，例如 `get_price(stock_id, start, end) -> DataFrame[date, open, high, low, close, volume]`；其餘 `get_institutional_investors`/`get_margin_trading`/`get_financial_statement`/`get_month_revenue`/`get_news` 同樣先寫好預期欄位；並定義錯誤情境行為（token無效/額度超過/股票代號不存在時的回應）
- **測試**：mock FinMind SDK 回傳，測試正常回應／API錯誤／空資料三種情境下是否符合規格；不打真實API
- **實作**：`data_sources/finmind_client.py`；另外用 `scripts/explore_finmind.py`（非TDD範圍）人工跑一次真實API，確認規格寫的欄位跟實際回傳相符，有落差就回頭修正規格與測試
- **人工驗證發現並修正的落差**：
  - `get_news`（`taiwan_stock_news`）實際上只接受單日查詢，帶非空`end_date`會報錯；已改成client內部逐日呼叫再合併，對外介面仍維持日期範圍不變
  - `get_news`實際回傳欄位沒有`description`，規格與實作已更正為`date, stock_id, title, link, source`
- **驗收**：
  - [x] `uv run pytest backend/tests/test_finmind_client.py` 全過
  - [x] `explore_finmind.py` 已人工驗證過各dataset真實欄位與規格一致

#### Stage 1 補強（2026-10-01 風險檢討後）✅ 已完成
- **真實API實測結果**（匿名呼叫，可用即代表免費方案可用）：
  - `taiwan_stock_daily_adj`（還原股價）：❌ sponsor 限定，回應 `Your level is free. Please update your user level.`
  - `taiwan_stock_tick_snapshot`（即時報價）：❌ sponsor 限定（SDK docstring）
  - `taiwan_stock_dividend_result`（除權息結果）：✅ 免費；`after_price` 依SDK說明為除權息後收盤價，調整基準改用 `reference_price`（實測0056歷次兩者相同）
  - `taiwan_stock_split_price`（面額變更/分割）：✅ 免費，**只能全市場查詢**（不接受stock_id）
  - `taiwan_stock_trading_date`（交易日曆）：✅ 免費；含未來日期但**只公布到當年底**（2026-10查2027回傳0筆）；2026-10-09、2026-12-25（皆週五）不在清單內，證實「週一到週五」規則會誤判
  - `taiwan_stock_capital_reduction_reference_price`（減資）：單股查詢免費但尚未找到有減資紀錄的股票驗證欄位；全市場查詢 sponsor 限定 → **暫不實作，待驗證**
- **實作**：
  - 新增 `get_dividend_result` / `get_split_price` / `get_trading_dates`
  - 新增 `FinMindSponsorRequiredError`（依 `update your user level` 訊息判斷）
  - 錯誤分類改成只依狀態碼（regex），修正原本「訊息子字串含402/401」會把股票代號、日期誤判的問題
  - 建構子 `login_by_token` 失敗改為丟出分類後的例外（原本會丟裸 `Exception("<Response [401]>")`）
  - **人工驗證再發現**：無效token實測回 `{"msg":"Token is illegal.","status":400}`（非原規格推測的401/403），且SDK login 對無效token仍判定成功 → 改依 `Token is illegal` 訊息轉成 `FinMindAuthError`，在第一次查資料時丟出
- **驗收**：
  - [x] `uv run pytest` 全過（38 passed）
  - [x] `explore_finmind.py` 對新dataset實測，欄位/型別與規格一致

#### Stage 1 快取（2026-10-01 使用者決定實作）✅ 已完成
- **規格**（詳見 `data_sources/cache.py` docstring）：
  - `FinMindClient(cache=FinMindCache(...))` 注入，不帶則不快取
  - 快取鍵＝dataset＋呼叫參數；存SDK原始回應（正規化前），pickle 存於 `data/cache/`
  - 查詢區間結束日 <= 今天 − `final_after_days`（預設3天）→ 視為已定案歷史資料，永久有效；否則 `ttl_seconds`（預設1小時）內有效
  - 例外不快取；空結果要快取（假日無新聞是有效結果）；快取檔損毀視為未命中並刪除
  - 建立快取時自動刪除超過 `max_age_days`（預設14天，需 >= 新聞回溯天數）未更新的檔案；大部分查詢結束日每天不同，舊檔不會再被讀到（實測單股一次完整分析約14檔、84KB）
  - 所有參數由 `config.py` 的 `Settings` 統一管理（`CACHE_DIR`/`CACHE_TTL_SECONDS`/`CACHE_FINAL_AFTER_DAYS`/`CACHE_MAX_AGE_DAYS`），`create_finmind_client()` 依設定建立；相對路徑以專案根目錄為基準
- **效益來源**：價格/法人等「一次呼叫可查任意區間」的dataset，當日首跑仍需呼叫（最新幾天未定案），省的是**重跑**；新聞逐日呼叫，已定案的日子永久命中，首跑也省
- **驗收**：
  - [x] `uv run pytest` 全過（62 passed）
  - [x] 真實API實測：同一組查詢（股價/法人/除權息/7天新聞）首跑 10 次呼叫，重跑 0 次、結果一致
  - [x] 使用者人工驗證（2026-10-01）：pytest 62 passed；`explore_finmind.py` 帶真實token無ERROR、欄位與規格一致、額度上限600；無效token各項皆為 `FinMindAuthError`；`verify_cache.py` 連跑兩次首跑14次呼叫、重跑0次

### Stage 2：規則訊號層（技術／籌碼／基本面）
- **規格**：逐一定義每個指標/訊號函式的輸入輸出與邊界，例如「MA5從下方穿越到上方MA20的當天才算golden_cross=true，持平不算、資料不足回傳None」；所有門檻值集中寫入 `signals/config.py`
  - **還原股價**（`indicators/price_adjust.py`）：每個除權息/面額變更事件的調整係數 = `參考價 / 前一日收盤價`（除權息用 `reference_price/before_price`，面額變更用 `after_price/before_price`），事件日**之前**的 OHLC 全部乘上係數（多事件連乘）；**最新一筆必等於原始價**。技術指標一律吃還原價；買賣點等「價位」與顯示用原始價。成交量只在面額變更/分割時反向調整（6763 分割後日量從約13萬股跳到231萬股）；配股因結果表未拆出股票股利比例，暫不調整成交量
    - ✅ 已完成（`indicators/price_adjust.py`，16 個測試）。真實資料驗證（`scripts/verify_price_adjust.py`）：6763 面額變更日原始漲跌 −90.51% → 還原 −5.09%；0056 除息日原始 −0.80% → 還原 +1.95%（實際上漲，原始價連方向都錯）；最新一筆還原價＝原始價
  - **回溯期間**：各dataset抓取天數集中定義在 `signals/config.py`（起始值於本Stage與使用者拍板），並寫一條測試確保 config 天數 ≥ 各指標最低需求（例如MA60需約90個日曆天）
  - ETF/無財報標的：基本面訊號在資料為空時回傳 None，不丟例外
- **測試**：針對每個函式用構造假資料寫邊界case（剛好穿越當天、穿越前一天、資料不足）；還原股價用真實事件數值當fixture（如6763面額變更491→49.1、0056除息）
- **實作**：`indicators/price_adjust.py`／`technical.py`／`chip.py`／`fundamental.py`／`signals/signal_builder.py`
- **驗收**：
  - [ ] `uv run pytest backend/tests/test_price_adjust.py backend/tests/test_indicators_*.py backend/tests/test_signal_builder.py` 全過，每個規則函式至少涵蓋一個邊界case

### Stage 3：LLM判斷層
- **規格**：定義丟給 ChatGPT 的輸入（事實清單 JSON schema）與輸出（買點/賣點/風險/長期與否/判斷依據/信心程度的 JSON schema），用 OpenAI Structured Outputs 強制格式
- **測試**：mock OpenAI API，驗證 1) prompt組裝內容包含必要事實欄位 2) 回傳能正確解析成內部 pydantic model 3) API失敗/未設Key時回傳`llm_status="failed"/"pending"`而不拋例外中斷
- **實作**：`llm/prompt_templates.py`／`llm/report_generator.py`
- **驗收**：
  - [ ] mock測試全過
  - [ ] 用真實Key人工跑 `analyze_one.py 2330`，人工檢視報告品質與格式（此項無法自動化，為人工驗收）

### Stage 4：Pipeline 整合
- **規格**：`analyze_stock(stock_id, as_of_date) -> AnalysisReport`，串接 Stage1-3；定義單支股票分析失敗時要拋出什麼例外，供上層（排程/API）決定如何處理
  - **資料新鮮度**：逐dataset檢查最新一筆date，產出 `data_freshness`（例：`{price: "2026-10-01", margin: "2026-09-30"}`）存入報告並當事實餵給LLM；股價本身不是 as_of_date 時不呼叫LLM（交給排程層判斷延遲/休市/個股停牌）
  - 依 `signals/config.py` 的回溯期間抓資料
- **測試**：mock掉 FinMind 與 OpenAI 兩層的整合測試，驗證資料流與呼叫順序正確
- **實作**：`pipeline/analyze_stock.py`
- **驗收**：
  - [ ] `uv run pytest backend/tests/test_pipeline.py` 全過
  - [ ] `scripts/analyze_one.py` 端到端人工跑通

### Stage 5：資料庫層
- **規格**：SQLAlchemy models 的 schema（見核心設計重點）；CRUD 函式的行為contract，例如「新增重複 stock_id 時要忽略還是報錯」需先拍板寫進規格
- **測試**：用 SQLite in-memory 測試每個 CRUD 函式的正常與例外情境
- **實作**：`db/models.py`／`database.py`／`crud.py`
- **驗收**：
  - [ ] `uv run pytest backend/tests/test_crud.py` 全過

### Stage 6：排程層 ⏸ 延後（2026-10-01 使用者決定：先實現功能，自動排程最後再做）
> 延後期間一律以手動觸發（`analyze_one.py`、`POST /api/analysis/run`）執行分析。手動觸發的 `as_of_date` 簡化為「抓到的股價資料最新一筆日期」，不依賴交易日曆，也自然避開盤中或假日觸發時拿不到當天資料的問題。以下規格保留，恢復時沿用。

- **規格**：定義排程 job 的行為——單支股票失敗要記錄log但不中斷其他股票
  - **APScheduler 設定**：`BackgroundScheduler`（不可用AsyncIOScheduler跑阻塞的pipeline）、`timezone="Asia/Taipei"`、`misfire_grace_time` 數小時、`coalesce=True`（預設寬限僅1秒，睡眠剛醒會直接漏跑）
  - **啟動補跑**：FastAPI 啟動時，若最近一個已過排程時間的交易日沒有 success/skipped 的 `AnalysisRun`，於背景補跑（`as_of_date` = 該交易日，不是今天）
  - **交易日判斷**：
    1. 本地 `TradingCalendar` 涵蓋今天 → 依日曆（`calendar_source=calendar`）
    2. 日曆查詢失敗或範圍不含今天（年初FinMind尚未公布新年度）→ 平日規則，週一到週五視為「推定交易日」（`calendar_source=weekday_fallback`），週末跳過
  - **新鮮度把關**（不論來源，呼叫LLM前一律確認當天股價已出）：
    | 交易日判斷 | 當天股價 | 處理 |
    |---|---|---|
    | 日曆：交易日 | 有 | 正常分析 |
    | 日曆：交易日 | 無 | 視為延遲，每隔一段時間重試至截止時間；仍無 → `skipped: no_market_data`（颱風臨時休市落在此），不呼叫LLM |
    | 平日推定 | 有 | 資料證明有開市，正常分析 |
    | 平日推定 | 無 | 無法區分假日或延遲，同上重試至截止時間後跳過 |
    | 休市/週末 | — | 直接跳過 |
  - 市場是否開市以「清單中**任一檔**有當天股價」判斷；開市但單檔無資料 → 個股停牌，只跳過該檔
  - 重試間隔與截止時間做成 config，數值待實測各dataset實際更新時間後再定
- **測試**：mock pipeline 呼叫，驗證「其中一支丟例外時，其他股票仍會被執行且結果有存入DB」；上表每一列情境各一個測試；補跑只針對 failed/缺漏的交易日
- **實作**：`scheduler/jobs.py`
- **驗收**：
  - [ ] `uv run pytest backend/tests/test_scheduler_jobs.py` 全過
  - [ ] `uv run uvicorn` 啟動後，log確認排程已註冊到正確時間

### Stage 7：REST API 層
- **規格**：依端點草案定義每個端點的 request/response schema 與狀態碼行為（例如新增重複股票回 409、刪除不存在股票回 404）
- **測試**：用 FastAPI `TestClient` 寫涵蓋正常與錯誤 case 的 API 測試
- **實作**：`api/routes_*.py`
- **驗收**：
  - [ ] `uv run pytest backend/tests/test_api_*.py` 全過
  - [ ] `/docs` Swagger 手動測試一輪

### Stage 8：聊天工具層
- **規格**：兩類工具（清單管理、股票資訊查詢）的 input/output schema；會改變狀態的工具執行後必須在回覆中明確告知使用者
- **測試**：mock OpenAI 的 `tool_calls` 回應，驗證 `chat_service` 能正確分派到對應 handler、組裝 `role="tool"` 回應格式正確、多輪迴圈能正確終止（不會無限loop）
- **實作**：`chat/tools.py`／`chat_service.py`
- **驗收**：
  - [ ] `uv run pytest backend/tests/test_chat_service.py` 全過
  - [ ] 用真實OpenAI Key人工測試：「幫我把2454加入追蹤清單」後 `Watchlist` 表真的新增一筆；「調出2330的基本資訊」能回報最近交易日收盤資料，且回覆中明確標示資料日期（非即時價）

### Stage 9：前端 - 儀表板模式
- **規格**：清單瀏覽／報告檢視頁面的互動行為描述
- **驗收**（人工為主，見「例外（前端）」說明）：
  - [ ] `npm run dev` 啟動後，瀏覽器可看到追蹤清單與當日報告，資料與後端API一致

### Stage 10：前端 - 聊天模式
- **規格**：聊天視窗的互動行為、工具執行結果的呈現方式
- **驗收**：
  - [ ] 瀏覽器實際操作「新增股票→手動觸發分析→儀表板看到報告→聊天問該股票問題並得到基於報告內容的回答」完整走一遍
  - [ ] 聊天輸入清單管理/查詢類指令，實際驗證有觸發對應工具且結果正確呈現

### Stage 11：打磨
- **規格**：錯誤處理、loading狀態、額度耗盡提示等使用者體驗細節
- **驗收**：人工體驗走一遍主要情境，確認沒有未處理的錯誤畫面

---

## 開發時需要確認/拍板的細節（非阻塞，於對應 Stage 處理）

- FinMind 各 dataset 確切名稱/欄位 → Stage1 已驗證；呼叫額度依官方 quickstart：匿名 300 次/小時、註冊帶token 600 次/小時；使用者帳號實際上限已確認為 **600**（2026-10-01 用 token 跑 explore 腳本，`/v2/user_info` 的 `api_request_limit`）。每次全清單分析約 (7 + 新聞天數) × 股票數 + 1 次呼叫；快取已實作（見 Stage 1 快取）
- 新聞相關性篩選方式（FinMind是否支援用stock_id查詢消息面）→ Stage1驗證後定案
- 技術指標參數預設值（MA5/20/60、RSI14、KD9、MACD12/26/9、布林20±2σ）沿用業界慣例，籌碼/基本面門檻（連續買超天數、YoY成長%等）→ Stage2與使用者一起拍板
- 各dataset每日實際更新時間 → 隨 Stage 6 延後；恢復時連續幾天於不同時段跑 explore 腳本實測，據以決定排程時間與重試截止時間
- 減資事件的還原 → 找到有減資紀錄的股票、驗證真實欄位後補進 Stage1 client 與 Stage2 還原邏輯
- CRUD對重複/不存在資料的行為（新增重複股票、刪除不存在股票）→ Stage5定案並寫入規格
- 股票清單輸入先走「前端表單逐一新增」，之後有需要再加CSV匯入
- 報告重跑策略先採「同日覆蓋」，不做版本歷史
- **刪除追蹤股票是否需要二次確認**：MVP階段先採「執行後明確告知使用者已刪除」，若使用者覺得誤刪風險高，之後可改成「LLM先用文字確認，等使用者下一句回覆再真的呼叫工具」
- 工具集刻意聚焦在「股票資訊查詢」與「介面操作（清單管理）」兩類，其他情境先不做，等MVP跑通後再評估擴充
- 第一輪風險檢討中的「安全性」（API無認證、跨站觸發燒額度、新聞prompt injection、成本上限、工具參數驗證）與「設計未定義處」（軟刪除重新加入、SQLite並發寫入、串流vs工具呼叫、聊天歷史截斷、LLM結果可追溯）尚未逐項拍板

## 已拍板決策（2026-10-01 風險檢討）

| # | 問題 | 決策 | 落實位置 |
|---|---|---|---|
| 1 | 免費方案無即時報價 | 取最近交易日收盤＋`QuoteProvider` 抽象，回覆必帶資料日期 | 聊天層工具表、Stage 8 |
| 2 | 股價未還原，除權息/面額變更造成假訊號 | FinMind還原股價為付費限定 → 用除權息結果＋面額變更**自行還原**；指標用還原價、價位用原始價 | Stage 1 補強、Stage 2 |
| 3 | 舊資料冒充當日 | 逐dataset標示 `data_freshness`；股價未出不呼叫LLM | Stage 4、Stage 6 |
| 4 | 回溯期間未定義 | config 集中定義＋最低需求測試 | Stage 2、Stage 4 |
| 5 | 本機排程漏跑 | 啟動補跑＋APScheduler misfire/coalesce/timezone 設定 | Stage 6 |
| 6 | 國定假日照跑 | 交易日曆為主、平日規則備援、新鮮度把關；寫入端跳過非交易日，讀取端回最近交易日報告 | Stage 5、Stage 6、Stage 7 |
