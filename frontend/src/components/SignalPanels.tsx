import type { ReactNode } from "react";
import { BIAS_TEXT, BIAS_LABEL, fmtNumber, fmtPct, fmtSigned } from "../lib/format";
import type { Signal, Snapshot, StockSignals } from "../types/api";
import { KeyValueGrid, Section } from "./ui";

type Row = [label: string, render: (s: Snapshot) => ReactNode];
const v = (s: Snapshot, key: string) => s[key] ?? null;
const num = (key: string, digits = 2): Row[1] => (s) => fmtNumber(v(s, key), digits);
const pct = (key: string, signed = true): Row[1] => (s) => fmtPct(v(s, key), 2, signed);
const lots = (key: string): Row[1] => (s) => fmtSigned(v(s, key), 0);
const streak = (key: string): Row[1] => (s) => {
  const days = v(s, key);
  if (days === null) return "—";
  if (days === 0) return "—";
  return days > 0 ? `連買 ${days} 天` : `連賣 ${-days} 天`;
};

const TECHNICAL_ROWS: Row[] = [
  ["收盤", num("close")],
  ["漲跌幅", pct("change_pct")],
  ["成交量（張）", (s) => fmtNumber(v(s, "volume") === null ? null : v(s, "volume")! / 1000, 0)],
  ["量比（對 20 日均量）", num("volume_ratio")],
  ["MA5", num("ma5")],
  ["MA20", num("ma20")],
  ["MA60", num("ma60")],
  ["RSI6", num("rsi6")],
  ["RSI12", num("rsi12")],
  ["K9", num("k")],
  ["D9", num("d")],
  ["DIF", num("macd_dif")],
  ["MACD", num("macd_signal")],
  ["OSC", num("macd_hist")],
  ["布林上軌", num("bb_upper")],
  ["布林中軌", num("bb_middle")],
  ["布林下軌", num("bb_lower")],
  ["ATR14", num("atr")],
];

const CHIP_ROWS: Row[] = [
  ["外資買賣超（張）", lots("foreign_net_lots")],
  ["外資 5 日（張）", lots("foreign_net_5d_lots")],
  ["外資連續", streak("foreign_streak")],
  ["投信買賣超（張）", lots("trust_net_lots")],
  ["投信 5 日（張）", lots("trust_net_5d_lots")],
  ["投信連續", streak("trust_streak")],
  ["自營商買賣超（張）", lots("dealer_net_lots")],
  ["自營商 5 日（張）", lots("dealer_net_5d_lots")],
  ["外資+投信 5 日佔成交量", pct("foreign_trust_net_5d_ratio_pct")],
  ["融資餘額（張）", num("margin_balance_lots", 0)],
  ["融資 5 日增減", pct("margin_change_5d_pct")],
  ["股價 5 日漲跌", pct("price_change_5d_pct")],
  ["融券餘額（張）", num("short_balance_lots", 0)],
  ["券資比", pct("short_margin_ratio_pct", false)],
];

const FUNDAMENTAL_ROWS: Row[] = [
  ["月營收（億元）", (s) => fmtNumber(v(s, "revenue") === null ? null : v(s, "revenue")! / 1e8, 2)],
  ["營收年增率", pct("revenue_yoy_pct")],
  ["營收月增率", pct("revenue_mom_pct")],
  [
    "年增率連續",
    (s) => {
      const months = v(s, "revenue_yoy_streak");
      if (!months) return "—";
      const atLeast = v(s, "revenue_yoy_streak_capped") ? "至少 " : "";
      return `${atLeast}${Math.abs(months)} 個月${months > 0 ? "成長" : "衰退"}`;
    },
  ],
  ["單季 EPS", num("eps")],
  ["EPS 年增率", pct("eps_yoy_pct")],
  ["近四季 EPS", num("ttm_eps")],
  ["毛利率", pct("gross_margin_pct", false)],
  ["毛利率年變化（百分點）", (s) => fmtSigned(v(s, "gross_margin_change_pp"), 2)],
  ["營業利益率", pct("operating_margin_pct", false)],
  ["本益比", num("pe_ratio")],
  ["本益比歷史百分位", pct("pe_percentile", false)],
  ["股價淨值比", num("pb_ratio")],
  ["殖利率", pct("dividend_yield", false)],
];

function SignalList({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) return <p className="text-sm text-slate-500">目前沒有觸發訊號</p>;
  return (
    <ul className="space-y-1.5 text-sm">
      {signals.map((s) => (
        <li key={s.name + s.date} className="flex gap-2">
          <span className={`w-10 shrink-0 text-xs leading-5 font-medium ${BIAS_TEXT[s.bias]}`}>{BIAS_LABEL[s.bias]}</span>
          <span className="text-slate-700">
            {s.description}
            {s.date && (
              <span className="text-xs text-slate-400">
                （{s.date}
                {s.days_ago ? `，${s.days_ago} 個交易日前` : ""}）
              </span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Panel({
  title,
  extra,
  rows,
  snapshot,
  signals,
}: {
  title: string;
  extra: string;
  rows: Row[];
  snapshot: Snapshot;
  signals: Signal[];
}) {
  return (
    <Section title={title} extra={extra}>
      <KeyValueGrid rows={rows.map(([label, render]) => [label, render(snapshot)])} />
      <h3 className="mt-4 mb-1.5 text-sm font-medium text-slate-700">訊號</h3>
      <SignalList signals={signals} />
    </Section>
  );
}

function Unavailable({ title, reason }: { title: string; reason?: string }) {
  return (
    <Section title={title}>
      <p className="text-sm text-slate-500">無資料{reason ? `：${reason}` : ""}</p>
    </Section>
  );
}

export function SignalPanels({ signals }: { signals: StockSignals }) {
  const { technical, chip, fundamental, unavailable } = signals;
  return (
    <>
      {technical ? (
        <Panel title="技術面" extra={`還原價計算｜${technical.as_of}`} rows={TECHNICAL_ROWS} snapshot={technical.snapshot} signals={technical.signals} />
      ) : (
        <Unavailable title="技術面" reason={unavailable.technical} />
      )}
      {chip ? (
        <Panel
          title="籌碼面"
          extra={`法人 ${chip.as_of_institutional ?? "—"}｜融資券 ${chip.as_of_margin ?? "—"}`}
          rows={CHIP_ROWS}
          snapshot={chip.snapshot}
          signals={chip.signals}
        />
      ) : (
        <Unavailable title="籌碼面" reason={unavailable.chip} />
      )}
      {fundamental ? (
        <Panel
          title="基本面"
          extra={`營收 ${fundamental.as_of_revenue?.slice(0, 7) ?? "—"} 月｜財報 ${fundamental.as_of_financials ?? "—"}｜估值 ${fundamental.as_of_valuation ?? "—"}`}
          rows={FUNDAMENTAL_ROWS}
          snapshot={fundamental.snapshot}
          signals={fundamental.signals}
        />
      ) : (
        <Unavailable title="基本面" reason={unavailable.fundamental} />
      )}
    </>
  );
}
