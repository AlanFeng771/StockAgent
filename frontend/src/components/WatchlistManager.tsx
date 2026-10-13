import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { Button, ErrorBox } from "./ui";

/** 加入追蹤清單（代號格式、是否存在由後端檢查）。 */
export function WatchlistManager({ onAdded }: { onAdded: () => void }) {
  const [stockId, setStockId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!stockId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.addWatchlist(stockId.trim());
      setStockId("");
      onAdded();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <div className="flex gap-2">
        <input
          value={stockId}
          onChange={(e) => setStockId(e.target.value)}
          placeholder="股票代號，例如 2330"
          className="w-48 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
        />
        <Button type="submit" variant="primary" busy={busy}>
          加入追蹤
        </Button>
      </div>
      <ErrorBox error={error} />
    </form>
  );
}
