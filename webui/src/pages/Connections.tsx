import { useEffect, useState } from "react";
import { RefreshCw, Plug } from "lucide-react";
import { api, Admin, Connection } from "../api/client";

export default function Connections({ me }: { me: Admin | null }) {
  const [rows, setRows] = useState<Connection[]>([]);
  const [kind, setKind] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const r = await api<{ connections: Connection[] }>("/api/connections" + (kind ? `?kind=${kind}` : ""));
      setRows(r.connections);
    } catch (e: any) { setError(e.message); }
  };

  useEffect(() => { load(); }, [kind]);

  return (
    <>
      {error && <div className="alert alert-error mb-4">{error}</div>}

      <div className="flex items-center justify-between mb-6 gap-3">
        <select className="select" style={{ width: "auto" }} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All kinds</option>
          <option value="web">Web</option>
          <option value="bot">Bot</option>
        </select>
        <button className="btn btn-ghost btn-icon" onClick={load} title="Refresh"><RefreshCw size={14} /></button>
      </div>

      <div className="card">
        <div className="card-title">Recent connections</div>
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr><th>Kind</th><th>Admin ID</th><th>IP</th><th>User agent</th><th>Detail</th><th>When</th></tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>
                    <span className={`badge ${c.kind === "web" ? "badge-info" : "badge-muted"}`}>
                      <Plug size={10} /> {c.kind}
                    </span>
                  </td>
                  <td className="mono">{c.admin_id ?? "—"}</td>
                  <td className="mono">{c.ip || "—"}</td>
                  <td className="text-xs text-muted" style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {c.user_agent || "—"}
                  </td>
                  <td><span className="badge badge-muted">{c.detail || "—"}</span></td>
                  <td className="text-xs text-muted">{new Date(c.connected_at).toLocaleString()}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={6} className="text-muted text-center">No connections yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
