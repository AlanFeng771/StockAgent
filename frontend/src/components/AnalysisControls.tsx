import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { JobStatus } from "../types/api";
import { Button, ConfirmDialog, ErrorBox } from "./ui";

const POLL_MS = 2000;

/** 全部分析：先確認（會花 OpenAI 費用）→ 背景執行 → 輪詢進度。 */
export function AnalysisControls({ total, onProgress }: { total: number; onProgress: () => void }) {
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const timer = useRef<number | undefined>(undefined);
  const lastCompleted = useRef(0);

  const poll = useCallback(async () => {
    try {
      const next = await api.analysisStatus();
      setStatus(next);
      if (next.completed !== lastCompleted.current) {
        lastCompleted.current = next.completed;
        onProgress(); // 每完成一檔就刷新卡片
      }
      if (next.state === "running") timer.current = window.setTimeout(poll, POLL_MS);
    } catch (err) {
      setError(err);
    }
  }, [onProgress]);

  useEffect(() => {
    // 進頁面時若已有工作在跑（例如重新整理），接續顯示進度
    api.analysisStatus().then((s) => {
      setStatus(s);
      lastCompleted.current = s.completed;
      if (s.state === "running") timer.current = window.setTimeout(poll, POLL_MS);
    }).catch(setError);
    return () => window.clearTimeout(timer.current);
  }, [poll]);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const started = await api.runAll();
      setStatus(started);
      lastCompleted.current = 0;
      setConfirming(false);
      timer.current = window.setTimeout(poll, POLL_MS);
    } catch (err) {
      setError(err);
      setConfirming(false);
    } finally {
      setStarting(false);
    }
  }

  const running = status?.state === "running";
  return (
    <div className="flex flex-col items-end gap-2">
      <Button variant="primary" onClick={() => setConfirming(true)} disabled={total === 0 || running}>
        {running ? "全部分析中…" : "全部分析"}
      </Button>

      {status && status.state !== "idle" && (
        <div className="w-64 text-xs text-slate-600">
          <div className="mb-1 flex justify-between">
            <span>{running ? "分析進度" : "上次全部分析"}</span>
            <span className="tabular-nums">
              {status.completed} / {status.total}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full bg-slate-700 transition-all"
              style={{ width: `${status.total ? (status.completed / status.total) * 100 : 0}%` }}
            />
          </div>
          {status.failed.length > 0 && (
            <ul className="mt-1 text-red-600">
              {status.failed.map((f) => (
                <li key={f.stock_id}>
                  {f.stock_id} 失敗：{f.error}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <ErrorBox error={error} />

      <ConfirmDialog
        open={confirming}
        title="分析整份追蹤清單？"
        confirmLabel={`分析 ${total} 檔`}
        busy={starting}
        onConfirm={start}
        onCancel={() => setConfirming(false)}
      >
        <p>
          將依序分析 <b>{total}</b> 檔股票，會呼叫 OpenAI 約 <b>{total}</b> 次並產生費用
          （報告有價格警告時會自動修正，可能再多呼叫幾次）。
        </p>
        <p>分析在背景執行，期間可以繼續瀏覽。</p>
      </ConfirmDialog>
    </div>
  );
}
