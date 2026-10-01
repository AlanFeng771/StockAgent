# 台股自動分析＋追蹤 Agent — 實作計畫

## Context

使用者想要一個能根據自訂股票清單，每天自動產生分析報告的 agent，報告需包含買點、賣點、風險、是否為長期投資、判斷依據與重要指標，並透過一個可互動的網頁（聊天介面＋儀表板）查看與詢問。

專案位置 `c:\Users\user\Desktop\Projects\StockAgent` 目前完全空白，尚未是 git repo，可從零開始設計，不需相容任何既有程式碼。

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
│   │   ├── config.py              # pydantic-settings讀.env
│   │   ├── data_sources/
│   │   │   └── finmind_client.py  # 封裝FinMind SDK，每dataset一個method，含快取
│   │   ├── indicators/
│   │   │   ├── technical.py       # MA/MACD/KD/RSI/布林通道/量能
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
│       ├── test_finmind_client.py
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
| 股票資訊查詢 | 「台積電現在多少錢」「2454基本資料」「台積電今天的分析報告」 | `get_stock_quote(stock_id)`／`get_stock_report(stock_id, date?)` | `finmind_client` 即時查詢／`crud.get_report()` |

**架構原則**：`chat/tools.py` 用「註冊表」模式設計：每個工具是 `{name, description, input_schema(pydantic model), handler}` 的一筆註冊項，`chat_service` 的 agentic loop 只依工具名稱查表分派，之後若要加新工具只需新增註冊項，不用動迴圈邏輯——但目前刻意不多做，等MVP跑通、使用者實際用過覺得有需要再擴充。

**設計原則（執行安全性）**：
- 讀取類工具（`list_watchlist`/`get_stock_quote`/`get_stock_report`）可讓 ChatGPT 自由呼叫，無需使用者二次確認
- **會改變狀態的工具**（`add_watchlist_stock`/`remove_watchlist_stock`，尤其是刪除）執行後，回覆需明確告知使用者「已執行了什麼操作」；是否要在刪除前額外要求二次確認列入待確認事項
- 日常分析報告的取得仍**優先讀當天已算好的結果**（`get_stock_report`），不透過聊天隱式觸發即時重新分析

### 資料庫 Schema（SQLite + SQLAlchemy）
- `Watchlist`：stock_id, stock_name, is_active（軟刪除）
- `AnalysisReport`：stock_id + analysis_date（唯一鍵，MVP階段同日覆蓋）、raw_signals_json、raw_indicators_json、llm_report_json、llm_status
- `ChatMessage`：session_id, role, content, related_stock_id

### API 端點草案
```
GET/POST/DELETE /api/watchlist[/{stock_id}]
POST /api/analysis/run            # 全清單手動觸發
POST /api/analysis/run/{stock_id} # 單股手動觸發
GET  /api/reports/{stock_id}/latest
GET  /api/reports/{stock_id}/history?start=&end=
GET  /api/reports/today
POST /api/chat                    # response需包含最終文字回覆 + 過程中執行的工具動作列表(actions_taken)
GET  /api/chat/history?session_id=
GET  /api/health, /api/scheduler/status
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

### Stage 1：FinMind 資料擷取層
- **規格**：定義 `finmind_client.py` 各method的輸入輸出contract，例如 `get_price(stock_id, start, end) -> DataFrame[date, open, high, low, close, volume]`；其餘 `get_institutional_investors`/`get_margin_trading`/`get_financial_statement`/`get_month_revenue`/`get_news` 同樣先寫好預期欄位；並定義錯誤情境行為（token無效/額度超過/股票代號不存在時的回應）
- **測試**：mock FinMind SDK 回傳，測試正常回應／API錯誤／空資料三種情境下是否符合規格；不打真實API
- **實作**：`data_sources/finmind_client.py`；另外用 `scripts/explore_finmind.py`（非TDD範圍）人工跑一次真實API，確認規格寫的欄位跟實際回傳相符，有落差就回頭修正規格與測試
- **驗收**：
  - [ ] `uv run pytest backend/tests/test_finmind_client.py` 全過
  - [ ] `explore_finmind.py` 已人工驗證過各dataset真實欄位與規格一致

### Stage 2：規則訊號層（技術／籌碼／基本面）
- **規格**：逐一定義每個指標/訊號函式的輸入輸出與邊界，例如「MA5從下方穿越到上方MA20的當天才算golden_cross=true，持平不算、資料不足回傳None」；所有門檻值集中寫入 `signals/config.py`
- **測試**：針對每個函式用構造假資料寫邊界case（剛好穿越當天、穿越前一天、資料不足）
- **實作**：`indicators/technical.py`／`chip.py`／`fundamental.py`／`signals/signal_builder.py`
- **驗收**：
  - [ ] `uv run pytest backend/tests/test_indicators_*.py backend/tests/test_signal_builder.py` 全過，每個規則函式至少涵蓋一個邊界case

### Stage 3：LLM判斷層
- **規格**：定義丟給 ChatGPT 的輸入（事實清單 JSON schema）與輸出（買點/賣點/風險/長期與否/判斷依據/信心程度的 JSON schema），用 OpenAI Structured Outputs 強制格式
- **測試**：mock OpenAI API，驗證 1) prompt組裝內容包含必要事實欄位 2) 回傳能正確解析成內部 pydantic model 3) API失敗/未設Key時回傳`llm_status="failed"/"pending"`而不拋例外中斷
- **實作**：`llm/prompt_templates.py`／`llm/report_generator.py`
- **驗收**：
  - [ ] mock測試全過
  - [ ] 用真實Key人工跑 `analyze_one.py 2330`，人工檢視報告品質與格式（此項無法自動化，為人工驗收）

### Stage 4：Pipeline 整合
- **規格**：`analyze_stock(stock_id, as_of_date) -> AnalysisReport`，串接 Stage1-3；定義單支股票分析失敗時要拋出什麼例外，供上層（排程/API）決定如何處理
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

### Stage 6：排程層
- **規格**：定義排程 job 的行為——單支股票失敗要記錄log但不中斷其他股票；非交易日判斷先簡化為「週一到週五」
- **測試**：mock pipeline 呼叫，驗證「其中一支丟例外時，其他股票仍會被執行且結果有存入DB」
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
  - [ ] 用真實OpenAI Key人工測試：「幫我把2454加入追蹤清單」後 `Watchlist` 表真的新增一筆；「調出2330的基本資訊」能即時回報現價等快照資料

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

- FinMind 各 dataset 確切名稱/欄位/呼叫額度上限 → Stage1驗證
- 新聞相關性篩選方式（FinMind是否支援用stock_id查詢消息面）→ Stage1驗證後定案
- 技術指標參數預設值（MA5/20/60、RSI14、KD9、MACD12/26/9、布林20±2σ）沿用業界慣例，籌碼/基本面門檻（連續買超天數、YoY成長%等）→ Stage2與使用者一起拍板
- 非交易日判斷：先簡化為「週一到週五」，如需精確可用「FinMind當天是否回傳股價資料」判斷是否交易日
- CRUD對重複/不存在資料的行為（新增重複股票、刪除不存在股票）→ Stage5定案並寫入規格
- 股票清單輸入先走「前端表單逐一新增」，之後有需要再加CSV匯入
- 報告重跑策略先採「同日覆蓋」，不做版本歷史
- **刪除追蹤股票是否需要二次確認**：MVP階段先採「執行後明確告知使用者已刪除」，若使用者覺得誤刪風險高，之後可改成「LLM先用文字確認，等使用者下一句回覆再真的呼叫工具」
- 工具集刻意聚焦在「股票資訊查詢」與「介面操作（清單管理）」兩類，其他情境先不做，等MVP跑通後再評估擴充
