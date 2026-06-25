import { useEffect, useState } from "react";
import { Trash2, Filter, ChevronLeft, ChevronRight } from "lucide-react";
import { api, Admin, HistoryEntry } from "../api/client";

const PAGE = 100;

export default function History({ me }: { me: Admin | null }) {
  const [rows, setRows] = useState<HistoryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [pairId, setPairId] = useState("");
  const [msgType, setMsgType] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canView = me?.is_super || me?.perms.view_history;
  const canClear = me?.is_super || me?.perms.clear_logs;

  const load = async () => {
    if (!canView) return;
    setBusy(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE));
      params.set("offset", String(offset));
      if (pairId) params.set("pair_id", pairId);
      if (msgType) params.set("msg_type", msgType);
      const r = await api<{ history: HistoryEntry[]; total: number }>(`/api/history?${params}`);
      setRows(r.history);
      setTotal(r.total);
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  useEffect(() => { load(); }, [offset, pairId, msgType, canView]);

  const clear = async () => {
    if (!confirm("Delete ALL history entries?")) return;
    try {
      await api("/api/history", { method: "DELETE" });
      setOffset(0);
      await load();
    } catch (e: any) { setError(e.message); }
  };

  if (!canView) return <div className="alert alert-error">You don't have the <code>view_history</code> permission.</div>;

  return (
    <>
      {error && <div className="alert alert-error mb-4">{error}</div>}

      <div className="flex items-center justify-between mb-6 gap-3" style={{ flexWrap: "wrap" }}>
        <div className="flex items-center gap-2">
          <Filter size={14} className="opacity-60" />
          <input className="input" style={{ width: 120 }} placeholder="Pair ID" value={pairId}
                 onChange={(e) => { setPairId(e.target.value); setOffset(0); }} />
          <select className="select" style={{ width: "auto" }} value={msgType}
                  onChange={(e) => { setMsgType(e.target.value); setOffset(0); }}>
            <option value="">All types</option>
            {["text", "photo", "video", "audio", "document", "contact", "location", "poll", "other"].map(t =>
              <option key={t} value={t}>{t}</option>
            )}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">{total} total</span>
          {canClear && (
            <button className="btn btn-danger btn-sm" onClick={clear}>
              <Trash2 size={12} /> Clear all
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Pair</th><th>Source → Dest</th><th>Type</th>
                <th>Preview</th><th>When</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => (
                <tr key={h.id}>
                  <td className="mono">#{h.pair_id}</td>
                  <td className="mono text-xs">
                    <div>{h.source_title}</div>
                    <div style={{ color: "var(--text-subtle)" }}>↓</div>
                    <div>{h.dest_title}</div>
                  </td>
                  <td><span className="badge badge-info">{h.msg_type}</span></td>
                  <td className="text-xs text-muted" style={{ maxWidth: 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {h.msg_preview || <span className="opacity-60">—</span>}
                  </td>
                  <td className="text-xs text-muted">{new Date(h.forwarded_at).toLocaleString()}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={5} className="text-muted text-center">No history yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between mt-6">
        <div className="text-xs text-muted">
          {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
        </div>
        <div className="flex gap-2">
          <button className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            <ChevronLeft size={14} /> Prev
          </button>
          <button className="btn btn-sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
            Next <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </>
  );
}
