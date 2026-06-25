import { useEffect, useState } from "react";
import { RefreshCw, Trash2, Filter } from "lucide-react";
import { api, Admin, LogEntry } from "../api/client";

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];

export default function Logs({ me }: { me: Admin | null }) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [level, setLevel] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canView = me?.is_super || me?.perms.view_logs;
  const canClear = me?.is_super || me?.perms.clear_logs;

  const load = async () => {
    if (!canView) return;
    setBusy(true);
    try {
      const r = await api<{ logs: LogEntry[] }>("/api/logs" + (level ? `?level=${level}` : ""));
      setLogs(r.logs);
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [level, canView]);

  const clear = async () => {
    if (!confirm("Delete ALL log entries?")) return;
    try {
      await api("/api/logs", { method: "DELETE" });
      await load();
    } catch (e: any) { setError(e.message); }
  };

  if (!canView) return <div className="alert alert-error">You don't have the <code>view_logs</code> permission.</div>;

  const levelColor = (lvl: string) =>
    lvl === "ERROR" ? "badge-danger" :
    lvl === "WARNING" ? "badge-warning" :
    lvl === "INFO" ? "badge-info" : "badge-muted";

  return (
    <>
      {error && <div className="alert alert-error mb-4">{error}</div>}

      <div className="flex items-center justify-between mb-6 gap-3" style={{ flexWrap: "wrap" }}>
        <div className="flex items-center gap-2">
          <Filter size={14} className="opacity-60" />
          <select className="select" style={{ width: "auto" }} value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="">All levels</option>
            {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
          <button className="btn btn-ghost btn-icon" onClick={load} title="Refresh">
            <RefreshCw size={14} />
          </button>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">{logs.length} entries</span>
          {canClear && (
            <button className="btn btn-danger btn-sm" onClick={clear}>
              <Trash2 size={12} /> Clear all
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <div style={{ maxHeight: "70vh", overflowY: "auto", fontFamily: "var(--font-mono)", fontSize: 12 }}>
          {logs.length === 0 && <div className="empty"><div className="empty-icon"><RefreshCw size={20} /></div>No log entries.</div>}
          {logs.map((l) => (
            <div key={l.id} style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", display: "flex", gap: 12, alignItems: "flex-start" }}>
              <span style={{ color: "var(--text-subtle)", flexShrink: 0 }}>{new Date(l.created_at).toLocaleTimeString()}</span>
              <span className={`badge ${levelColor(l.level)}`} style={{ flexShrink: 0 }}>{l.level}</span>
              {l.module && <span style={{ color: "var(--text-subtle)", flexShrink: 0 }}>[{l.module}]</span>}
              <span style={{ flex: 1, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{l.message}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
