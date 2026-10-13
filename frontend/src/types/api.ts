// 對應後端 backend/app/api/schemas.py 與 signals 模型（日期皆為 YYYY-MM-DD 字串）

export type Bias = "bullish" | "bearish" | "neutral";
export type LlmStatus = "success" | "pending" | "failed";

export interface WatchlistItem {
  stock_id: string;
  stock_name: string | null;
  created_at: string;
}

export interface PricePoint {
  price: number;
  basis: string;
  condition: string;
}

export interface Judgement {
  aspect: "technical" | "chip" | "fundamental" | "news" | "price_levels";
  point: string;
  bias: Bias;
}

export interface StockReport {
  summary: string;
  overall_bias: Bias;
  entry_points: PricePoint[];
  exit_points: PricePoint[];
  target_price: PricePoint | null;
  target_price_reason: string;
  stop_loss: PricePoint | null;
  stop_loss_reason: string;
  holding_period: "short_term" | "swing" | "long_term" | "not_recommended";
  holding_period_reason: string;
  long_term_suitable: boolean;
  long_term_reason: string;
  risks: string[];
  rationale: Judgement[];
  confidence: "low" | "medium" | "high";
  confidence_reason: string;
  data_limitations: string[];
}

export interface ReportSummary {
  id: number;
  stock_id: string;
  stock_name: string | null;
  close: number | null;
  change_pct: number | null;
  price_date: string | null;
  analysis_date: string;
  generated_at: string;
  llm_status: LlmStatus;
  report: StockReport | null;
  error: string | null;
  warnings: string[];
  repair_attempts: number;
  model: string;
  prompt_version: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
}

export interface Signal {
  name: string;
  category: string;
  bias: Bias;
  description: string;
  date: string | null;
  days_ago: number | null;
  value: number | null;
  threshold: number | null;
}

export interface PriceLevel {
  source: string;
  category: "high_low" | "indicator" | "atr_projection";
  price: number;
  adjusted_price: number;
  chart_price: number | null;
  date: string | null;
  distance_pct: number;
}

export interface FillGap {
  ex_date: string;
  dividend: number;
  fill_price: number;
  filled: boolean;
  filled_date: string | null;
}

export interface PriceLevels {
  as_of: string;
  close: number;
  kind: string;
  supports: PriceLevel[];
  resistances: PriceLevel[];
  flags: Record<string, boolean>;
  fill_gap: FillGap | null;
}

export type Snapshot = Record<string, number | null>;

export interface StockSignals {
  stock_id: string;
  profile: { stock_id: string; stock_name: string; industries: string[]; market: string; kind: string } | null;
  data_freshness: Record<string, string | null>;
  price_levels: PriceLevels | null;
  technical: { as_of: string; snapshot: Snapshot; signals: Signal[] } | null;
  chip: { as_of_institutional: string | null; as_of_margin: string | null; snapshot: Snapshot; signals: Signal[] } | null;
  fundamental: {
    as_of_revenue: string | null;
    as_of_financials: string | null;
    as_of_valuation: string | null;
    snapshot: Snapshot;
    signals: Signal[];
  } | null;
  unavailable: Record<string, string>;
  news: { date: string; title: string; source: string; link: string }[];
}

export interface ReportDetail extends ReportSummary {
  signals: StockSignals;
}

export interface JobStatus {
  state: "idle" | "running" | "done";
  total: number;
  completed: number;
  succeeded: string[];
  failed: { stock_id: string; error: string }[];
  started_at: string | null;
  finished_at: string | null;
}

// ---- 聊天（Stage 8 後端） ----

export interface PendingAction {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  summary: string;
  created_at: string;
  expires_at: string;
}

export interface ActionLog {
  tool: string;
  arguments: Record<string, unknown> | string;
  level: "auto" | "confirm" | null;
  status: "executed" | "failed" | "pending_confirmation" | "rejected";
  summary: string | null;
  error: string | null;
  action_id: string | null;
}

export interface ChatReply {
  session_id: string;
  reply: string;
  actions_taken: ActionLog[];
  pending_actions: PendingAction[];
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant" | "action";
  content: string;
  created_at: string;
}

export interface ChatHistory {
  session_id: string;
  messages: ChatMessage[];
  pending_actions: PendingAction[];
}

export interface ActionOutcome {
  action_id: string;
  status: "done" | "failed" | "cancelled";
  message: string;
}
