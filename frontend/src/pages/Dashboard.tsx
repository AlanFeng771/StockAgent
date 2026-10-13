import { useState } from "react";
import { api, errorMessage } from "../api/client";
import { AnalysisControls } from "../components/AnalysisControls";
import { StockCard } from "../components/StockCard";
import { ConfirmDialog, ErrorBox, Spinner } from "../components/ui";
import { WatchlistManager } from "../components/WatchlistManager";
import { useAsync } from "../hooks/useAsync";
import type { WatchlistItem } from "../types/api";

export function Dashboard({ refreshKey }: { refreshKey: number }) {
  const { data, error, loading, reload } = useAsync(
    () => Promise.all([api.listWatchlist(), api.latestReports()]),
    [refreshKey],
  );
  const [analyzing, setAnalyzing] = useState<Set<string>>(new Set());
  const [removing, setRemoving] = useState<WatchlistItem | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [watchlist, reports] = data ?? [[], []];
  const reportOf = (stockId: string) => reports.find((r) => r.stock_id === stockId);

  async function analyze(stockId: string) {
    setActionError(null);
    setAnalyzing((s) => new Set(s).add(stockId));
    try {
      await api.runOne(stockId);
      reload();
    } catch (err) {
      setActionError(`${stockId} 分析失敗：${errorMessage(err)}`);
    } finally {
      setAnalyzing((s) => {
        const next = new Set(s);
        next.delete(stockId);
        return next;
      });
    }
  }

  async function confirmRemove() {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      await api.removeWatchlist(removing.stock_id);
      setRemoving(null);
      reload();
    } catch (err) {
      setActionError(errorMessage(err));
      setRemoving(null);
    } finally {
      setRemoveBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">追蹤清單</h1>
          <p className="mt-1 text-sm text-slate-500">價格為分析當時的收盤資料，非即時報價</p>
        </div>
        <AnalysisControls total={watchlist.length} onProgress={reload} />
      </div>

      <WatchlistManager onAdded={reload} />
      {actionError && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{actionError}</div>}
      <ErrorBox error={error} />
      {loading && !data && <Spinner />}

      {data && watchlist.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center text-slate-500">
          清單是空的，先在上方輸入股票代號加入追蹤
        </div>
      )}

      {/* 欄數依可用寬度自動決定（聊天欄開關會改變寬度） */}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,19rem),1fr))] gap-4">
        {watchlist.map((item) => (
          <StockCard
            key={item.stock_id}
            item={item}
            report={reportOf(item.stock_id)}
            analyzing={analyzing.has(item.stock_id)}
            onOpen={() => (window.location.hash = `#/stock/${item.stock_id}`)}
            onAnalyze={() => analyze(item.stock_id)}
            onRemove={() => setRemoving(item)}
          />
        ))}
      </div>

      <ConfirmDialog
        open={removing !== null}
        title="移除追蹤？"
        confirmLabel="移除"
        danger
        busy={removeBusy}
        onConfirm={confirmRemove}
        onCancel={() => setRemoving(null)}
      >
        <p>
          將 <b>{removing?.stock_id} {removing?.stock_name}</b> 從追蹤清單移除。
        </p>
        <p>歷史報告會保留，之後重新加入即可恢復。</p>
      </ConfirmDialog>
    </div>
  );
}
