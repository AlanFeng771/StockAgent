import { useCallback, useEffect, useState } from "react";
import { api } from "./api/client";
import { ChatPanel } from "./components/ChatPanel";
import { Dashboard } from "./pages/Dashboard";
import { StockDetail } from "./pages/StockDetail";

function useHash(): string {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => {
      setHash(window.location.hash);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

const HEALTH_POLL_MS = 30_000;

/** 後端連線狀態：載入時與之後每 30 秒檢查一次；綠點正常、紅點連不上。 */
function BackendStatus() {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    const check = () => api.health().then(() => setOk(true), () => setOk(false));
    check();
    const timer = window.setInterval(check, HEALTH_POLL_MS);
    return () => window.clearInterval(timer);
  }, []);
  if (ok === null) return null;
  return (
    <span className="flex items-center gap-1.5 text-xs text-slate-500" title="每 30 秒自動檢查">
      <span className={`h-2 w-2 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`} />
      {ok ? "後端已連線" : <span className="text-red-600">後端未連線（請啟動 uvicorn）</span>}
    </span>
  );
}

export default function App() {
  const hash = useHash();
  const stockId = hash.match(/^#\/stock\/([0-9A-Za-z]+)$/)?.[1];
  // ≥768px 並排（預設開啟）；更窄時預設關閉，開啟時以覆蓋面板顯示
  const [chatOpen, setChatOpen] = useState(() => window.matchMedia("(min-width: 768px)").matches);
  // 聊天中的動作（加入、確認移除/分析）完成後遞增，讓儀表板重新載入
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-slate-200 bg-white/90 px-6 backdrop-blur">
        <div className="flex items-center gap-4">
          <a href="#/" className="text-lg font-bold tracking-tight">
            StockAgent <span className="text-sm font-normal text-slate-500">台股分析</span>
          </a>
          <BackendStatus />
        </div>
        <button
          type="button"
          onClick={() => setChatOpen((open) => !open)}
          className="rounded-lg px-3 py-1.5 text-sm text-slate-600 ring-1 ring-slate-300 hover:bg-slate-50"
        >
          {chatOpen ? "收合聊天" : "聊天助理"}
        </button>
      </header>

      <div className="flex">
        <main className="min-w-0 flex-1 p-6">
          {stockId ? <StockDetail stockId={stockId} refreshKey={refreshKey} /> : <Dashboard refreshKey={refreshKey} />}
        </main>
        {/* 關閉時只隱藏不卸載，保留對話與輸入中的內容 */}
        <aside
          className={`${chatOpen ? "flex" : "hidden"} fixed inset-0 z-50 flex-col bg-white shadow-xl md:sticky md:inset-auto md:top-14 md:z-auto md:h-[calc(100vh-3.5rem)] md:w-80 md:shrink-0 md:border-l md:border-slate-200 md:shadow-none xl:w-96`}
        >
          <ChatPanel onChanged={refresh} onClose={() => setChatOpen(false)} />
        </aside>
      </div>
    </div>
  );
}
