import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, errorMessage } from "../api/client";
import type { ActionLog, PendingAction } from "../types/api";
import { Button } from "./ui";

const SESSION_KEY = "stockagent.chat.session";
const TOOL_LABEL: Record<string, string> = {
  list_watchlist: "查追蹤清單",
  add_watchlist_stock: "加入追蹤",
  remove_watchlist_stock: "移除追蹤",
  get_latest_price: "查行情",
  get_stock_report: "查報告",
  get_report_history: "查歷史報告",
  analyze_stock: "分析",
};
// 會改變儀表板內容的工具：執行後通知儀表板重新載入
const MUTATING_TOOLS = new Set(["add_watchlist_stock"]);
const SUGGESTIONS = ["我的追蹤清單有哪些？", "台積電最近收盤多少？", "2330 最新報告的重點是什麼？"];

interface Item {
  key: string;
  role: "user" | "assistant" | "action" | "error";
  content: string;
  actions?: ActionLog[];
}

function loadSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function saveSession(sessionId: string | null) {
  try {
    if (sessionId) localStorage.setItem(SESSION_KEY, sessionId);
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    // 無法存取 localStorage 時只是不保留對話，不影響使用
  }
}

let itemSeq = 0;
const item = (role: Item["role"], content: string, actions?: ActionLog[]): Item => ({
  key: `i${++itemSeq}`,
  role,
  content,
  actions,
});

function ActionChips({ actions }: { actions: ActionLog[] }) {
  return (
    <ul className="mt-1.5 flex flex-wrap gap-1.5">
      {actions.map((a, i) => {
        const stockId = typeof a.arguments === "object" ? (a.arguments.stock_id as string | undefined) : undefined;
        const label = `${TOOL_LABEL[a.tool] ?? a.tool}${stockId ? ` ${stockId}` : ""}`;
        const style =
          a.status === "executed"
            ? "bg-slate-100 text-slate-600"
            : a.status === "pending_confirmation"
              ? "bg-amber-100 text-amber-800"
              : "bg-red-50 text-red-700";
        const mark = a.status === "executed" ? "✓" : a.status === "pending_confirmation" ? "⏳" : "✗";
        return (
          <li key={i} className={`rounded px-1.5 py-0.5 text-[11px] ${style}`} title={a.error ?? a.summary ?? undefined}>
            {mark} {label}
            {a.status === "pending_confirmation" && "（等待確認）"}
          </li>
        );
      })}
    </ul>
  );
}

function secondsLeft(expiresAt: string, now: number): number {
  return Math.max(0, Math.floor((new Date(expiresAt).getTime() - now) / 1000));
}

function PendingCard({
  action,
  now,
  onResolved,
}: {
  action: PendingAction;
  now: number;
  onResolved: (message: string, executed: boolean) => void;
}) {
  const [busy, setBusy] = useState<"confirm" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const left = secondsLeft(action.expires_at, now);
  const expired = left === 0;

  async function resolve(kind: "confirm" | "cancel") {
    setBusy(kind);
    setError(null);
    try {
      const outcome = kind === "confirm" ? await api.confirmAction(action.id) : await api.cancelAction(action.id);
      onResolved(outcome.message, outcome.status === "done");
    } catch (err) {
      setError(errorMessage(err));
      setBusy(null);
    }
  }

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
      <div className="text-xs font-medium text-amber-800">需要你確認才會執行</div>
      <div className="mt-1 font-medium text-slate-900">{action.summary}</div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-xs text-amber-700 tabular-nums">
          {expired ? "已過期" : `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} 內有效`}
        </span>
        <div className="flex gap-1.5">
          <Button onClick={() => resolve("cancel")} busy={busy === "cancel"} disabled={busy !== null || expired}>
            取消
          </Button>
          <Button variant="primary" onClick={() => resolve("confirm")} busy={busy === "confirm"} disabled={busy !== null || expired}>
            {busy === "confirm" && action.tool_name === "analyze_stock" ? "分析中" : "確認"}
          </Button>
        </div>
      </div>
      {error && <p className="mt-2 text-xs text-red-700">{error}</p>}
    </div>
  );
}

function Markdown({ text }: { text: string }) {
  return (
    <div className="chat-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ a: (props) => <a {...props} target="_blank" rel="noreferrer noopener" /> }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export function ChatPanel({ onChanged, onClose }: { onChanged: () => void; onClose: () => void }) {
  const [sessionId, setSessionId] = useState<string | null>(loadSession);
  const [items, setItems] = useState<Item[]>([]);
  const [pending, setPending] = useState<PendingAction[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [now, setNow] = useState(Date.now());
  const bottom = useRef<HTMLDivElement>(null);

  // 重新整理後接續上次的對話
  useEffect(() => {
    if (!sessionId) return;
    api
      .chatHistory(sessionId)
      .then((history) => {
        setItems(history.messages.map((m) => item(m.role, m.content)));
        setPending(history.pending_actions);
      })
      .catch((err) => setItems([item("error", `載入聊天紀錄失敗：${errorMessage(err)}`)]));
    // 只在掛載時載入一次
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, pending, sending]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || sending) return;
    setInput("");
    setItems((list) => [...list, item("user", message)]);
    setSending(true);
    try {
      const reply = await api.chat(message, sessionId ?? undefined);
      setSessionId(reply.session_id);
      saveSession(reply.session_id);
      setItems((list) => [...list, item("assistant", reply.reply, reply.actions_taken)]);
      setPending(reply.pending_actions);
      if (reply.actions_taken.some((a) => a.status === "executed" && MUTATING_TOOLS.has(a.tool))) onChanged();
    } catch (err) {
      setItems((list) => [...list, item("error", errorMessage(err))]);
    } finally {
      setSending(false);
    }
  }

  function resolved(action: PendingAction, message: string, executed: boolean) {
    setPending((list) => list.filter((p) => p.id !== action.id));
    setItems((list) => [...list, item("action", message)]);
    if (executed) onChanged();
  }

  function newConversation() {
    setSessionId(null);
    saveSession(null);
    setItems([]);
    setPending([]);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // 中文輸入法選字時按 Enter 不送出
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send(input);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
        <span className="font-semibold">聊天助理</span>
        <div className="flex gap-1.5">
          <Button onClick={newConversation} disabled={sending}>
            新對話
          </Button>
          <Button onClick={onClose} aria-label="關閉聊天">
            ✕
          </Button>
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {items.length === 0 && !sending && (
          <div className="space-y-2 pt-6 text-center text-sm text-slate-500">
            <p>可以請我管理追蹤清單、查行情或解讀報告</p>
            <div className="flex flex-col items-center gap-1.5 pt-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" onClick={() => send(s)} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700 hover:bg-slate-200">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {items.map((it) => {
          if (it.role === "user") {
            return (
              <div key={it.key} className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-slate-800 px-3 py-2 text-sm whitespace-pre-wrap text-white">{it.content}</div>
              </div>
            );
          }
          if (it.role === "action") {
            return (
              <div key={it.key} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm whitespace-pre-wrap text-slate-700">
                <div className="mb-0.5 text-[11px] text-slate-400">動作紀錄</div>
                {it.content}
              </div>
            );
          }
          if (it.role === "error") {
            return (
              <div key={it.key} className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {it.content}
              </div>
            );
          }
          return (
            <div key={it.key} className="max-w-[95%] text-sm text-slate-800">
              <Markdown text={it.content} />
              {it.actions && it.actions.length > 0 && <ActionChips actions={it.actions} />}
            </div>
          );
        })}

        {pending.map((p) => (
          <PendingCard key={p.id} action={p} now={now} onResolved={(message, executed) => resolved(p, message, executed)} />
        ))}

        {sending && <div className="text-sm text-slate-400">思考中…</div>}
        <div ref={bottom} />
      </div>

      <div className="border-t border-slate-200 p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            maxLength={2000}
            placeholder="輸入訊息，Enter 送出、Shift+Enter 換行"
            className="flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
          />
          <Button variant="primary" onClick={() => send(input)} busy={sending} disabled={!input.trim()}>
            送出
          </Button>
        </div>
        <p className="mt-1.5 text-[11px] text-slate-400">移除追蹤、分析等動作需要你按確認才會執行</p>
      </div>
    </div>
  );
}
