import type { Bias, LlmStatus, PriceLevel, StockReport } from "../types/api";

// 台灣習慣：紅漲綠跌、偏多紅偏空綠

export function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: digits });
}

export const fmtPrice = (value: number | null | undefined) => fmtNumber(value, 2);

export function fmtPct(value: number | null | undefined, digits = 2, signed = true): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function fmtSigned(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return sign + value.toLocaleString("zh-TW", { maximumFractionDigits: digits });
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return value.replace("T", " ").slice(0, 16);
}

export function changeClass(value: number | null | undefined): string {
  if (!value) return "text-slate-600";
  return value > 0 ? "text-red-600" : "text-green-700";
}

export const BIAS_LABEL: Record<Bias, string> = { bullish: "偏多", bearish: "偏空", neutral: "中性" };
export const BIAS_BADGE: Record<Bias, string> = {
  bullish: "bg-red-50 text-red-700 ring-red-200",
  bearish: "bg-green-50 text-green-800 ring-green-200",
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
};
export const BIAS_TEXT: Record<Bias, string> = {
  bullish: "text-red-600",
  bearish: "text-green-700",
  neutral: "text-slate-600",
};

export const CONFIDENCE_LABEL: Record<StockReport["confidence"], string> = { low: "低", medium: "中", high: "高" };

export const HOLDING_LABEL: Record<StockReport["holding_period"], string> = {
  short_term: "短線（數日至 2 週）",
  swing: "波段（數週至 3 個月）",
  long_term: "長期（3 個月以上）",
  not_recommended: "不建議持有",
};

export const LLM_STATUS_LABEL: Record<LlmStatus, string> = {
  success: "報告完成",
  pending: "未產生報告（未設定 OpenAI Key）",
  failed: "報告產生失敗",
};

export const ASPECT_LABEL: Record<string, string> = {
  technical: "技術面",
  chip: "籌碼面",
  fundamental: "基本面",
  news: "新聞",
  price_levels: "價位",
};

export const LEVEL_CATEGORY_LABEL: Record<PriceLevel["category"], string> = {
  high_low: "高低點",
  indicator: "指標",
  atr_projection: "ATR 推算",
};

export const FRESHNESS_LABEL: Record<string, string> = {
  price: "股價",
  institutional: "法人",
  margin: "融資券",
  revenue: "月營收",
  financials: "財報",
  valuation: "估值",
  news: "新聞",
};

export const FLAG_LABEL: Record<string, string> = {
  new_high_20d: "創 20 日新高",
  new_low_20d: "創 20 日新低",
  new_high_60d: "創 60 日新高",
  new_low_60d: "創 60 日新低",
};
