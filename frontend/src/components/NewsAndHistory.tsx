import { BIAS_LABEL, BIAS_TEXT, fmtDateTime, fmtPrice, LLM_STATUS_LABEL } from "../lib/format";
import type { ReportSummary, StockSignals } from "../types/api";
import { Section } from "./ui";

export function NewsList({ news }: { news: StockSignals["news"] }) {
  return (
    <Section title="相關新聞" extra="已排除論壇文章並去除重複">
      {news.length === 0 ? (
        <p className="text-sm text-slate-500">近期沒有新聞</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {news.map((n) => (
            <li key={n.link} className="flex gap-3">
              <span className="w-20 shrink-0 text-xs leading-5 text-slate-400">{n.date}</span>
              <span>
                <a href={n.link} target="_blank" rel="noreferrer noopener" className="text-slate-800 hover:text-blue-700 hover:underline">
                  {n.title}
                </a>
                <span className="ml-2 text-xs text-slate-400">{n.source}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function HistoryTable({ history }: { history: ReportSummary[] }) {
  return (
    <Section title="歷史報告" extra="每個分析日取最新一份">
      {history.length === 0 ? (
        <p className="text-sm text-slate-500">尚無歷史報告</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-1.5 pr-3 font-normal">資料日期</th>
                <th className="py-1.5 pr-3 font-normal">收盤</th>
                <th className="py-1.5 pr-3 font-normal">看法</th>
                <th className="py-1.5 pr-3 font-normal">目標</th>
                <th className="py-1.5 pr-3 font-normal">停損</th>
                <th className="py-1.5 font-normal">摘要</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id} className="border-t border-slate-100 align-top">
                  <td className="py-1.5 pr-3 whitespace-nowrap tabular-nums" title={`產生於 ${fmtDateTime(h.generated_at)}`}>
                    {h.analysis_date}
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums">{fmtPrice(h.close)}</td>
                  <td className={`py-1.5 pr-3 whitespace-nowrap ${h.report ? BIAS_TEXT[h.report.overall_bias] : ""}`}>
                    {h.report ? BIAS_LABEL[h.report.overall_bias] : "—"}
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums">{fmtPrice(h.report?.target_price?.price)}</td>
                  <td className="py-1.5 pr-3 tabular-nums">{fmtPrice(h.report?.stop_loss?.price)}</td>
                  <td className="py-1.5 text-slate-600">{h.report?.summary ?? LLM_STATUS_LABEL[h.llm_status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
