import { useEffect, useRef, useState } from "react";
import {
  Users, Radio, Send, Activity, Pause, Play, Clock, Zap,
} from "lucide-react";
import { api, Admin, DashboardData } from "../api/client";

export default function Dashboard({ me }: { me: Admin | null }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);

  const fetchOnce = async () => {
    try { setData(await api<DashboardData>("/api/dashboard")); }
    catch (e: any) { setError(e.message); }
  };

  useEffect(() => {
    fetchOnce();
    if (!live) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/ws/dashboard`);
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        setData((prev) => prev ? { ...prev, ...msg } : prev);
      } catch {}
    };
    return () => ws.close();
  }, [live]);

  if (error) return <div className="alert alert-error">{error}</div>;
  if (!data) return <div className="empty"><span className="spinner" style={{ width: 28, height: 28 }} /></div>;

  return (
    <>
      {/* Top stat tiles */}
      <div className="stat-grid">
        <StatTile icon={<Users size={18} />} label="Admins" value={data.admins} />
        <StatTile icon={<Radio size={18} />} label="Channel pairs" value={data.pairs} sub={`${data.active_pairs} active`} />
        <StatTile icon={<Send size={18} />} label="Forwarded (total)" value={data.forwarded_total} />
        <StatTile icon={<Activity size={18} />} label="Last 24h" value={data.forwarded_24h} trend={`${data.forwarded_1h} in last hour`} />
      </div>

      {/* Status row */}
      <div className="grid grid-3 mb-6">
        <div className="card">
          <div className="card-title">Forwarder State</div>
          <div className="flex items-center gap-3">
            {data.paused ? (
              <><Pause size={20} color="var(--warning)" /> <span className="font-bold">Paused</span></>
            ) : (
              <><Play size={20} color="var(--success)" /> <span className="font-bold">Running</span></>
            )}
          </div>
          <div className="text-xs text-muted mt-4">Mode: <span className="mono">{data.forward_mode}</span></div>
        </div>

        <div className="card">
          <div className="card-title">Throughput</div>
          <div className="flex items-center gap-3">
            <Zap size={20} color="var(--brand)" />
            <span className="font-bold">{data.forwarded_1h}/h</span>
          </div>
          <div className="text-xs text-muted mt-4">7-day total: <span className="mono">{data.forwarded_7d}</span></div>
        </div>

        <div className="card">
          <div className="card-title">Active pairs</div>
          <div className="flex items-center gap-3">
            <Radio size={20} color="var(--accent)" />
            <span className="font-bold">{data.active_pairs}/{data.pairs}</span>
          </div>
          <div className="text-xs text-muted mt-4">
            {data.pairs_detail.filter(p => p.backfill_complete).length} backfilled
          </div>
        </div>
      </div>

      {/* 24h sparkline */}
      <div className="card mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className="card-title" style={{ margin: 0 }}>24-hour throughput</div>
          <div className="flex items-center gap-2">
            <Clock size={14} className="opacity-60" />
            <span className="text-xs text-muted">updates every 2s</span>
            <label className="switch" title="Live updates">
              <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
              <span className="switch-track"><span className="switch-thumb" /></span>
            </label>
          </div>
        </div>
        <div className="sparkline">
          {data.sparkline_24h.map((s, i) => {
            const max = Math.max(1, ...data.sparkline_24h.map(x => x.count));
            const h = Math.max(2, (s.count / max) * 100);
            return (
              <div key={i} className="spark-bar" style={{ height: `${h}%` }}
                   title={`${s.hour} — ${s.count} messages`} />
            );
          })}
        </div>
        <div className="flex justify-between mt-4 text-xs text-muted">
          <span>{data.sparkline_24h[0]?.hour}</span>
          <span>now</span>
        </div>
      </div>

      {/* Pair breakdown */}
      <div className="card mb-6">
        <div className="card-title">Channel pairs</div>
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>#</th><th>Source</th><th>Destination</th>
                <th>Status</th><th>Cursor</th><th>Forwarded</th><th>Last</th>
              </tr>
            </thead>
            <tbody>
              {data.pairs_detail.map((p) => (
                <tr key={p.id}>
                  <td className="mono">{p.id}</td>
                  <td>{p.source_title || p.source_id}</td>
                  <td>{p.dest_title || p.dest_id}</td>
                  <td>
                    {p.enabled
                      ? <span className="badge badge-success">enabled</span>
                      : <span className="badge badge-danger">disabled</span>}
                    {" "}
                    {p.backfill_complete
                      ? <span className="badge badge-muted">synced</span>
                      : <span className="badge badge-warning">backfilling</span>}
                  </td>
                  <td className="mono">#{p.last_source_msg_id}</td>
                  <td className="mono">{p.forwarded_total}</td>
                  <td className="text-xs text-muted">
                    {p.last_forwarded_at
                      ? new Date(p.last_forwarded_at).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              ))}
              {data.pairs_detail.length === 0 && (
                <tr><td colSpan={7} className="text-muted text-center">No channel pairs yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent activity */}
      <div className="card">
        <div className="card-title">Recent activity (last 30 forwards)</div>
        <div style={{ maxHeight: 400, overflowY: "auto" }}>
          <table className="table">
            <thead>
              <tr><th>Pair</th><th>Source msg</th><th>Dest msg</th><th>Type</th><th>Preview</th><th>When</th></tr>
            </thead>
            <tbody>
              {data.recent_activity.map((a) => (
                <tr key={a.id}>
                  <td className="mono">#{a.pair_id}</td>
                  <td className="mono">#{a.source_msg_id}</td>
                  <td className="mono">#{a.dest_msg_id}</td>
                  <td><span className="badge badge-info">{a.msg_type}</span></td>
                  <td className="text-xs text-muted" style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {a.msg_preview || <span className="opacity-60">—</span>}
                  </td>
                  <td className="text-xs text-muted">{new Date(a.forwarded_at).toLocaleTimeString()}</td>
                </tr>
              ))}
              {data.recent_activity.length === 0 && (
                <tr><td colSpan={6} className="text-muted text-center">No activity yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function StatTile({ icon, label, value, sub, trend }: {
  icon: React.ReactNode; label: string; value: number | string;
  sub?: string; trend?: string;
}) {
  return (
    <div className="stat">
      <div className="stat-icon">{icon}</div>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="text-xs text-muted mt-4">{sub}</div>}
      {trend && <div className="stat-trend">{trend}</div>}
    </div>
  );
}
