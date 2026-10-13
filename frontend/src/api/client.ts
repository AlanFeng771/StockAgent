import type { JobStatus, ReportDetail, ReportSummary, WatchlistItem } from "../types/api";

/** 後端錯誤：status 為 HTTP 狀態碼，error 為後端例外類別名（例如 WatchlistAlreadyExistsError）。 */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public error?: string,
  ) {
    super(message);
  }
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? String(d)).join("；"); // FastAPI 驗證錯誤
  return fallback;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  // 後端所有 POST 只收 application/json（擋跨站表單），所以 POST 一律帶 JSON body
  const init: RequestInit = { method };
  if (method !== "GET" && method !== "DELETE") {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body ?? {});
  }
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, "無法連線到後端，請確認 uvicorn 是否已啟動");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(response.status, detailMessage(payload?.detail, response.statusText), payload?.error);
  }
  return response.json() as Promise<T>;
}

const id = encodeURIComponent;

export const api = {
  health: () => request<{ status: string; database: string }>("GET", "/api/health"),
  listWatchlist: () => request<WatchlistItem[]>("GET", "/api/watchlist"),
  addWatchlist: (stockId: string) => request<WatchlistItem>("POST", "/api/watchlist", { stock_id: stockId }),
  removeWatchlist: (stockId: string) => request<WatchlistItem>("DELETE", `/api/watchlist/${id(stockId)}`),
  latestReports: () => request<ReportSummary[]>("GET", "/api/reports/latest"),
  latestReport: (stockId: string) => request<ReportDetail>("GET", `/api/reports/${id(stockId)}/latest`),
  reportHistory: (stockId: string) => request<ReportSummary[]>("GET", `/api/reports/${id(stockId)}/history`),
  runAll: () => request<JobStatus>("POST", "/api/analysis/run"),
  analysisStatus: () => request<JobStatus>("GET", "/api/analysis/status"),
  runOne: (stockId: string) => request<ReportDetail>("POST", `/api/analysis/run/${id(stockId)}`),
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.error === "AnalysisBusyError") return "已有分析在執行中，請稍後再試";
    return err.message;
  }
  return err instanceof Error ? err.message : String(err);
}
