import { useEffect, useState } from "react";
import { api } from "./api/client";
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

function BackendStatus() {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    api.health().then(() => setOk(true), () => setOk(false));
  }, []);
  if (ok === null) return null;
  return (
    <span className={`text-xs ${ok ? "text-slate-500" : "text-red-600"}`}>
      {ok ? "● 後端已連線" : "● 後端未連線（請啟動 uvicorn）"}
    </span>
  );
}

export default function App() {
  const hash = useHash();
  const stockId = hash.match(/^#\/stock\/([0-9A-Za-z]+)$/)?.[1];
  const [chatOpen, setChatOpen] = useState(true);
  // 聊天欄（Stage 10）執行動作後遞增，讓儀表板重新載入
  const [refreshKey] = useState(0);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-slate-200 bg-white/90 px-6 backdrop-blur">
        <div className="flex items-baseline gap-4">
          <a href="#/" className="text-lg font-bold tracking-tight">
            StockAgent <span className="text-sm font-normal text-slate-500">台股分析</span>
          </a>
          <BackendStatus />
        </div>
        <button
          type="button"
          onClick={() => setChatOpen((open) => !open)}
          className="hidden rounded-lg px-3 py-1.5 text-sm text-slate-600 ring-1 ring-slate-300 hover:bg-slate-50 lg:block"
        >
          {chatOpen ? "收合聊天" : "開啟聊天"}
        </button>
      </header>

      <div className="flex">
        <main className="min-w-0 flex-1 p-6">
          {stockId ? <StockDetail stockId={stockId} refreshKey={refreshKey} /> : <Dashboard refreshKey={refreshKey} />}
        </main>
        {chatOpen && (
          <aside className="sticky top-14 hidden h-[calc(100vh-3.5rem)] w-96 shrink-0 flex-col border-l border-slate-200 bg-white lg:flex">
            <div className="border-b border-slate-200 px-4 py-3 font-semibold">聊天助理</div>
            <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-slate-400">
              聊天功能將在下一階段（Stage 10）加入
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
