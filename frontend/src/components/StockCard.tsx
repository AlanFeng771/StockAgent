import { changeClass, fmtDateTime, fmtPct, fmtPrice, LLM_STATUS_LABEL } from "../lib/format";
import type { ReportSummary, WatchlistItem } from "../types/api";
import { BiasBadge, Button } from "./ui";

export function StockCard({
  item,
  report,
  analyzing,
  onOpen,
  onAnalyze,
  onRemove,
}: {
  item: WatchlistItem;
  report: ReportSummary | undefined;
  analyzing: boolean;
  onOpen: () => void;
  onAnalyze: () => void;
  onRemove: () => void;
}) {
  const r = report?.report;
  const name = item.stock_name ?? report?.stock_name ?? "";
  return (
    <article
      onClick={onOpen}
      className="flex cursor-pointer flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-400 hover:shadow"
    >
      <header className="flex items-start justify-between gap-2">
        <div>
          <div className="text-lg font-semibold text-slate-900">
            {item.stock_id} <span className="font-medium">{name}</span>
          </div>
          {report?.close != null && (
            <div className="mt-0.5 flex items-baseline gap-2 tabular-nums">
              <span className={`text-xl font-semibold ${changeClass(report.change_pct)}`}>{fmtPrice(report.close)}</span>
              <span className={`text-sm ${changeClass(report.change_pct)}`}>{fmtPct(report.change_pct)}</span>
              <span className="text-xs text-slate-500">{report.price_date} 收盤</span>
            </div>
          )}
        </div>
        {r && <BiasBadge bias={r.overall_bias} />}
      </header>

      {!report && <p className="text-sm text-slate-500">尚未分析</p>}

      {report && r && (
        <>
          <p className="line-clamp-2 text-sm text-slate-700">{r.summary}</p>
          <div className="grid grid-cols-2 gap-2 text-sm tabular-nums">
            <div>
              <span className="text-slate-500">目標 </span>
              <span className="font-medium text-red-600">{r.target_price ? fmtPrice(r.target_price.price) : "—"}</span>
            </div>
            <div>
              <span className="text-slate-500">停損 </span>
              <span className="font-medium text-green-700">{r.stop_loss ? fmtPrice(r.stop_loss.price) : "—"}</span>
            </div>
          </div>
        </>
      )}

      {report && report.llm_status !== "success" && (
        <p className="rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-800">{LLM_STATUS_LABEL[report.llm_status]}</p>
      )}

      <footer className="mt-auto flex items-center justify-between gap-2 border-t border-slate-100 pt-3">
        <div className="text-xs text-slate-500">
          {report ? <>分析於 {fmtDateTime(report.generated_at)}</> : "—"}
          {report && report.warnings.length > 0 && (
            <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">⚠ {report.warnings.length} 則警告</span>
          )}
        </div>
        <div className="flex gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button onClick={onAnalyze} busy={analyzing}>
            {analyzing ? "分析中" : "分析"}
          </Button>
          <Button variant="danger" onClick={onRemove} disabled={analyzing}>
            移除
          </Button>
        </div>
      </footer>
    </article>
  );
}
