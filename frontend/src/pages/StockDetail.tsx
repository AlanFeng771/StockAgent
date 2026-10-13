import { useState } from "react";
import { api, ApiError } from "../api/client";
import { NewsList, HistoryTable } from "../components/NewsAndHistory";
import { PriceLevelsPanel } from "../components/PriceLevelsPanel";
import { ReportView } from "../components/ReportView";
import { SignalPanels } from "../components/SignalPanels";
import { Button, ErrorBox, KeyValueGrid, Section, Spinner } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { changeClass, fmtPct, fmtPrice, FRESHNESS_LABEL } from "../lib/format";

export function StockDetail({ stockId, refreshKey }: { stockId: string; refreshKey: number }) {
  const report = useAsync(() => api.latestReport(stockId), [stockId, refreshKey]);
  const history = useAsync(() => api.reportHistory(stockId), [stockId, refreshKey]);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<unknown>(null);

  async function analyze() {
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      await api.runOne(stockId);
      report.reload();
      history.reload();
    } catch (err) {
      setAnalyzeError(err);
    } finally {
      setAnalyzing(false);
    }
  }

  const detail = report.data;
  const notFound = report.error instanceof ApiError && report.error.status === 404;
  const signals = detail?.signals;
  const profile = signals?.profile;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <a href="#/" className="text-sm text-slate-500 hover:text-slate-800">
            ← 回追蹤清單
          </a>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900">
            {stockId} {profile?.stock_name ?? detail?.stock_name ?? ""}
          </h1>
          {profile && (
            <p className="text-sm text-slate-500">
              {profile.industries.join("、")}｜{profile.market === "twse" ? "上市" : profile.market === "tpex" ? "上櫃" : profile.market}
            </p>
          )}
          {detail?.close != null && (
            <div className="mt-1 flex items-baseline gap-2 tabular-nums">
              <span className={`text-2xl font-semibold ${changeClass(detail.change_pct)}`}>{fmtPrice(detail.close)}</span>
              <span className={changeClass(detail.change_pct)}>{fmtPct(detail.change_pct)}</span>
              <span className="text-sm text-slate-500">{detail.price_date} 收盤（非即時）</span>
            </div>
          )}
        </div>
        <Button variant="primary" onClick={analyze} busy={analyzing}>
          {analyzing ? "分析中（約需數十秒）" : detail ? "重新分析" : "分析"}
        </Button>
      </div>

      <ErrorBox error={analyzeError} />
      {report.loading && !detail && <Spinner />}
      {notFound ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center text-slate-500">
          {stockId} 尚無分析報告，按右上角「分析」產生
        </div>
      ) : (
        <ErrorBox error={report.error} />
      )}

      {detail && signals && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div className="flex flex-col gap-5">
            <ReportView summary={detail} />
            <SignalPanels signals={signals} />
          </div>
          <div className="flex flex-col gap-5">
            <PriceLevelsPanel levels={signals.price_levels} />
            <Section title="資料日期" extra="各資料來源最新一筆的日期">
              <KeyValueGrid
                rows={Object.entries(signals.data_freshness).map(([key, value]) => [FRESHNESS_LABEL[key] ?? key, value ?? "無資料"])}
              />
            </Section>
            <NewsList news={signals.news} />
            {history.data && <HistoryTable history={history.data} />}
          </div>
        </div>
      )}
    </div>
  );
}
