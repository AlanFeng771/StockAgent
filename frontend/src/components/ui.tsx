import type { ButtonHTMLAttributes, ReactNode } from "react";
import { errorMessage } from "../api/client";
import { BIAS_BADGE, BIAS_LABEL } from "../lib/format";
import type { Bias } from "../types/api";

export function Section({ title, extra, children }: { title: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-800">{title}</h2>
        {extra && <div className="text-xs text-slate-500">{extra}</div>}
      </div>
      {children}
    </section>
  );
}

export function BiasBadge({ bias, prefix }: { bias: Bias; prefix?: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${BIAS_BADGE[bias]}`}>
      {prefix}
      {BIAS_LABEL[bias]}
    </span>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{errorMessage(error)}</div>;
}

export function Spinner({ label = "載入中…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
      {label}
    </div>
  );
}

type ButtonVariant = "primary" | "secondary" | "danger";
const BUTTON_STYLE: Record<ButtonVariant, string> = {
  primary: "bg-slate-800 text-white hover:bg-slate-700",
  secondary: "bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50",
  danger: "bg-white text-red-600 ring-1 ring-red-200 hover:bg-red-50",
};

export function Button({
  variant = "secondary",
  busy,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; busy?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || busy}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_STYLE[variant]} ${className}`}
    >
      {busy && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = "確認",
  danger,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onCancel}>
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <div className="mt-3 space-y-2 text-sm text-slate-600">{children}</div>
        <div className="mt-6 flex justify-end gap-2">
          <Button onClick={onCancel} disabled={busy}>
            取消
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} busy={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function KeyValueGrid({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
      {rows.map(([label, value]) => (
        <div key={label} className="flex flex-col">
          <dt className="text-xs text-slate-500">{label}</dt>
          <dd className="font-medium text-slate-800 tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
