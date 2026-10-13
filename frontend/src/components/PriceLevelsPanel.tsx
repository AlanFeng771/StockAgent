import { FLAG_LABEL, fmtNumber, fmtPct, fmtPrice, LEVEL_CATEGORY_LABEL } from "../lib/format";
import type { PriceLevel, PriceLevels } from "../types/api";
import { Section } from "./ui";

function LevelRow({ level, tone }: { level: PriceLevel; tone: "support" | "resistance" }) {
  const color = tone === "resistance" ? "text-red-600" : "text-green-700";
  return (
    <tr className="border-t border-slate-100">
      <td className={`py-1.5 pr-3 font-semibold tabular-nums ${color}`}>{fmtPrice(level.price)}</td>
      <td className="py-1.5 pr-3 text-slate-500 tabular-nums">{fmtPct(level.distance_pct, 1)}</td>
      <td className="py-1.5 pr-3">
        {level.source}
        {level.date && <span className="text-slate-400">（{level.date}）</span>}
        {level.chart_price != null && (
          <div className="text-xs text-amber-700">除權息前圖上價位 {fmtPrice(level.chart_price)}，兩價之間為壓力/支撐區</div>
        )}
      </td>
      <td className="py-1.5 text-xs text-slate-400">{LEVEL_CATEGORY_LABEL[level.category]}</td>
    </tr>
  );
}

export function PriceLevelsPanel({ levels }: { levels: PriceLevels | null }) {
  if (!levels) {
    return (
      <Section title="支撐與壓力">
        <p className="text-sm text-slate-500">股價資料不足，無法計算價位</p>
      </Section>
    );
  }
  const flags = Object.entries(levels.flags).filter(([, on]) => on);
  const gap = levels.fill_gap;
  return (
    <Section title="支撐與壓力" extra={`以還原價計算、對齊跳動單位｜${levels.as_of}`}>
      <table className="w-full text-sm">
        <tbody>
          {[...levels.resistances].reverse().map((l, i) => (
            <LevelRow key={`r${i}`} level={l} tone="resistance" />
          ))}
          <tr className="border-y-2 border-slate-300 bg-slate-50">
            <td className="py-1.5 pr-3 font-bold tabular-nums">{fmtPrice(levels.close)}</td>
            <td colSpan={3} className="py-1.5 text-xs text-slate-500">
              收盤價
            </td>
          </tr>
          {levels.supports.map((l, i) => (
            <LevelRow key={`s${i}`} level={l} tone="support" />
          ))}
        </tbody>
      </table>

      {(flags.length > 0 || gap) && (
        <div className="mt-4 flex flex-wrap gap-2 text-xs">
          {flags.map(([name]) => (
            <span key={name} className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">
              {FLAG_LABEL[name] ?? name}
            </span>
          ))}
          {gap && (
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">
              {gap.ex_date} 除息 {fmtNumber(gap.dividend, 4)} 元，填息價 {fmtPrice(gap.fill_price)}：
              {gap.filled ? `已於 ${gap.filled_date} 填息` : "尚未填息"}
            </span>
          )}
        </div>
      )}
    </Section>
  );
}
