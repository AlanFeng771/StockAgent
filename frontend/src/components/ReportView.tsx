import { ASPECT_LABEL, BIAS_TEXT, CONFIDENCE_LABEL, fmtDateTime, fmtPrice, HOLDING_LABEL, LLM_STATUS_LABEL } from "../lib/format";
import type { PricePoint, ReportSummary, StockReport } from "../types/api";
import { BiasBadge, Section } from "./ui";

function PointsTable({ title, points, tone }: { title: string; points: PricePoint[]; tone: "buy" | "sell" }) {
  const color = tone === "buy" ? "text-red-600" : "text-green-700";
  return (
    <div>
      <h3 className="mb-1.5 text-sm font-medium text-slate-700">{title}</h3>
      {points.length === 0 ? (
        <p className="text-sm text-slate-500">無</p>
      ) : (
        <ul className="space-y-1.5">
          {points.map((p, i) => (
            <li key={i} className="flex gap-3 text-sm">
              <span className={`w-20 shrink-0 font-semibold tabular-nums ${color}`}>{fmtPrice(p.price)}</span>
              <span className="text-slate-700">
                {p.basis}
                <span className="text-slate-500">｜{p.condition}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PriceWithReason({ label, point, reason, color }: { label: string; point: PricePoint | null; reason: string; color: string }) {
  return (
    <div className="rounded-lg bg-slate-50 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-xl font-semibold tabular-nums ${color}`}>{point ? fmtPrice(point.price) : "—"}</div>
      {point && <div className="text-xs text-slate-600">{point.basis}｜{point.condition}</div>}
      <p className="mt-1.5 text-xs text-slate-500">{reason}</p>
    </div>
  );
}

function ReportBody({ report }: { report: StockReport }) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <BiasBadge bias={report.overall_bias} prefix="整體看法：" />
        <span className="text-sm text-slate-600">信心 {CONFIDENCE_LABEL[report.confidence]}</span>
      </div>
      <p className="text-base leading-relaxed text-slate-800">{report.summary}</p>

      <div className="grid gap-4 md:grid-cols-2">
        <PointsTable title="買點" points={report.entry_points} tone="buy" />
        <PointsTable title="賣點" points={report.exit_points} tone="sell" />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <PriceWithReason label="目標價" point={report.target_price} reason={report.target_price_reason} color="text-red-600" />
        <PriceWithReason label="停損價" point={report.stop_loss} reason={report.stop_loss_reason} color="text-green-700" />
      </div>

      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <div className="text-xs text-slate-500">建議持有</div>
          <div className="font-medium">{HOLDING_LABEL[report.holding_period]}</div>
          <p className="text-xs text-slate-500">{report.holding_period_reason}</p>
        </div>
        <div>
          <div className="text-xs text-slate-500">適合長期投資</div>
          <div className="font-medium">{report.long_term_suitable ? "是" : "否"}</div>
          <p className="text-xs text-slate-500">{report.long_term_reason}</p>
        </div>
      </div>

      <div>
        <h3 className="mb-1.5 text-sm font-medium text-slate-700">判斷依據</h3>
        <ul className="space-y-1.5 text-sm">
          {report.rationale.map((j, i) => (
            <li key={i} className="flex gap-2">
              <span className="w-14 shrink-0 text-xs leading-5 text-slate-500">{ASPECT_LABEL[j.aspect] ?? j.aspect}</span>
              <span className={`shrink-0 text-xs leading-5 font-medium ${BIAS_TEXT[j.bias]}`}>●</span>
              <span className="text-slate-700">{j.point}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h3 className="mb-1.5 text-sm font-medium text-slate-700">風險</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
            {report.risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-1.5 text-sm font-medium text-slate-700">資料限制</h3>
          {report.data_limitations.length === 0 ? (
            <p className="text-sm text-slate-500">無</p>
          ) : (
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
              {report.data_limitations.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <p className="text-xs text-slate-500">信心說明：{report.confidence_reason}</p>
    </div>
  );
}

export function ReportView({ summary }: { summary: ReportSummary }) {
  const tokens =
    summary.prompt_tokens != null ? `${summary.prompt_tokens.toLocaleString()} + ${summary.completion_tokens?.toLocaleString()} tokens` : "—";
  return (
    <Section title="分析報告" extra={`資料日期 ${summary.analysis_date}｜產生於 ${fmtDateTime(summary.generated_at)}`}>
      {summary.warnings.length > 0 && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <div className="font-medium">價格檢查警告（報告中的價位可能不一致，請自行判斷）</div>
          <ul className="mt-1 list-disc pl-5">
            {summary.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
      {summary.report ? (
        <ReportBody report={summary.report} />
      ) : (
        <div className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900">
          <div className="font-medium">{LLM_STATUS_LABEL[summary.llm_status]}</div>
          {summary.error && <p className="mt-1">{summary.error}</p>}
          <p className="mt-1">下方的技術、籌碼、基本面資料仍可參考。</p>
        </div>
      )}
      <p className="mt-5 border-t border-slate-100 pt-3 text-xs text-slate-400">
        模型 {summary.model}｜prompt {summary.prompt_version}｜{tokens}｜自動修正 {summary.repair_attempts} 次。
        本報告為規則訊號與 AI 判讀的參考，非投資建議。
      </p>
    </Section>
  );
}
