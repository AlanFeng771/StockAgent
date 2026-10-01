# StockAgent

台股自動分析＋追蹤 Agent。根據自訂追蹤清單，每日自動抓取 FinMind 資料、計算技術/籌碼/基本面訊號，交由 ChatGPT API 綜合判斷產出報告，並提供聊天介面（具工具呼叫能力）與儀表板瀏覽。

## 開發環境

```bash
uv sync
cp .env.example .env   # 填入 FINMIND_API_TOKEN 與 OPENAI_API_KEY
uv run pytest
uv run uvicorn backend.app.main:app --reload   # 只綁 127.0.0.1；不要加 --host 0.0.0.0（API 沒有登入機制）
```

API 文件與手動測試：啟動後開 http://127.0.0.1:8000/docs

前端：

```bash
cd frontend
npm install
npm run dev
```

## 開發流程

採 SDD + TDD：每個階段先定規格、依規格寫測試、再實作到測試通過。詳見開發計畫文件。
