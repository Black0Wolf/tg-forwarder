import { useEffect, useState } from "react";
import {
  Plus, Search, Trash2, Power, RefreshCw, ArrowRight, X, Radio,
} from "lucide-react";
import { api, Admin, Pair } from "../api/client";

type Dialog = { id: number; title: string; username: string | null; type: string };

export default function Channels({ me }: { me: Admin | null }) {
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [busy, setBusy] = useState(false);

  // Add pair state
  const [recent, setRecent] = useState<Dialog[] | null>(null);
  const [mode, setMode] = useState<"pick-src" | "pick-dst" | "manual">("pick-src");
  const [srcValue, setSrcValue] = useState("");
  const [dstValue, setDstValue] = useState("");
  const [pickedSrc, setPickedSrc] = useState<Dialog | null>(null);

  const canEdit = me?.is_super || me?.perms.edit_channels;

  const load = async () => {
    try { setPairs(await api<Pair[]>("/api/channels")); }
    catch (e: any) { setError(e.message); }
  };

  useEffect(() => { load(); }, []);

  const openAdd = async () => {
    setShowAdd(true);
    setMode("pick-src");
    setSrcValue(""); setDstValue(""); setPickedSrc(null);
    try {
      const r = await api<{ dialogs: Dialog[] }>("/api/channels/recent");
      setRecent(r.dialogs);
    } catch (e: any) {
      setError(e.message);
      setRecent([]);
    }
  };

  const resolve = async (v: string): Promise<Dialog | null> => {
    try {
      const r = await api<Dialog>("/api/channels/resolve", {
        method: "POST", body: JSON.stringify({ value: v }),
      });
      return r;
    } catch { return null; }
  };

  const pickSrc = (d: Dialog) => {
    setPickedSrc(d);
    setMode("pick-dst");
    // re-fetch recent for dst (same list usually but refresh)
    if (!recent) openAdd();
  };

  const pickDst = async (d: Dialog) => {
    if (!pickedSrc) return;
    setBusy(true); setError(null);
    try {
      await api("/api/channels", {
        method: "POST",
        body: JSON.stringify({
          source: String(pickedSrc.id),
          dest: String(d.id),
        }),
      });
      setShowAdd(false);
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  const submitManual = async () => {
    if (mode === "pick-src") {
      const info = await resolve(srcValue);
      if (!info) { setError(`Could not resolve source "${srcValue}"`); return; }
      setPickedSrc(info);
      setMode("pick-dst");
      setError(null);
    } else if (mode === "pick-dst") {
      if (!pickedSrc) { setMode("pick-src"); return; }
      const info = await resolve(dstValue);
      if (!info) { setError(`Could not resolve destination "${dstValue}"`); return; }
      setBusy(true); setError(null);
      try {
        await api("/api/channels", {
          method: "POST",
          body: JSON.stringify({
            source: String(pickedSrc.id),
            dest: String(info.id),
          }),
        });
        setShowAdd(false);
        await load();
      } catch (e: any) { setError(e.message); }
      finally { setBusy(false); }
    }
  };

  const toggle = async (p: Pair) => {
    try {
      await api(`/api/channels/${p.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !p.enabled }),
      });
      await load();
    } catch (e: any) { setError(e.message); }
  };

  const del = async (p: Pair) => {
    if (!confirm(`Delete pair #${p.id} (${p.source_title || p.source_id} → ${p.dest_title || p.dest_id})?`)) return;
    try {
      await api(`/api/channels/${p.id}`, { method: "DELETE" });
      await load();
    } catch (e: any) { setError(e.message); }
  };

  const backfill = async (p: Pair) => {
    try {
      await api("/api/settings/backfill", {
        method: "POST",
        body: JSON.stringify({ pair_id: p.id, from_msg_id: 0 }),
      });
      setError(`Backfill triggered for pair #${p.id}`);
      await load();
    } catch (e: any) { setError(e.message); }
  };

  return (
    <>
      {error && <div className="alert alert-error mb-4">{error}</div>}

      <div className="flex items-center justify-between mb-6">
        <div className="text-xs text-muted">{pairs.length} channel pair{pairs.length !== 1 ? "s" : ""}</div>
        {canEdit && (
          <button className="btn btn-primary" onClick={openAdd}>
            <Plus size={14} /> Add pair
          </button>
        )}
      </div>

      {/* Add pair flow */}
      {showAdd && (
        <div className="card mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="card-title" style={{ margin: 0 }}>
              {mode === "pick-src" && "Step 1: Pick source channel"}
              {mode === "pick-dst" && `Step 2: Pick destination (source: ${pickedSrc?.title})`}
            </div>
            <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setShowAdd(false)}>
              <X size={14} />
            </button>
          </div>

          {mode === "pick-src" && (
            <>
              <div className="text-xs text-muted mb-4">
                Your 15 most recent channels/groups (from the userbot account):
              </div>
              <div className="flex flex-col gap-2">
                {recent === null && <span className="spinner" />}
                {recent?.length === 0 && <div className="text-muted text-sm">No channels found.</div>}
                {recent?.map((d) => (
                  <button key={d.id} className="btn btn-ghost" style={{ justifyContent: "flex-start" }}
                          onClick={() => pickSrc(d)}>
                    <Radio size={14} />
                    <span className="font-bold">{d.title}</span>
                    <span className="text-xs text-muted">({d.type})</span>
                    {d.username && <span className="text-xs text-muted mono">@{d.username}</span>}
                    <span className="text-xs text-muted mono ml-auto">#{d.id}</span>
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2 mt-6">
                <button className="btn" onClick={() => setMode("manual")}>
                  <Search size={14} /> Enter ID / @username manually
                </button>
              </div>
            </>
          )}

          {mode === "pick-dst" && (
            <>
              <div className="text-xs text-muted mb-4">
                Pick the destination channel:
              </div>
              <div className="flex flex-col gap-2">
                {recent?.map((d) => (
                  <button key={d.id} className="btn btn-ghost" style={{ justifyContent: "flex-start" }}
                          onClick={() => pickDst(d)} disabled={busy}>
                    <Radio size={14} />
                    <span className="font-bold">{d.title}</span>
                    <span className="text-xs text-muted">({d.type})</span>
                    {d.username && <span className="text-xs text-muted mono">@{d.username}</span>}
                    <span className="text-xs text-muted mono ml-auto">#{d.id}</span>
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2 mt-6">
                <button className="btn" onClick={() => setMode("manual")}>
                  <Search size={14} /> Enter destination manually
                </button>
                <button className="btn btn-ghost" onClick={() => setMode("pick-src")}>← Back</button>
              </div>
            </>
          )}

          {mode === "manual" && (
            <>
              <label>{pickedSrc ? "Destination ID / @username" : "Source ID / @username"}</label>
              <input
                className="input"
                value={pickedSrc ? dstValue : srcValue}
                onChange={(e) => pickedSrc ? setDstValue(e.target.value) : setSrcValue(e.target.value)}
                placeholder="@mychannel or -1001234567890"
                autoFocus
              />
              <div className="flex items-center gap-2 mt-4">
                <button className="btn btn-primary" onClick={submitManual} disabled={busy}>
                  {busy ? <span className="spinner" /> : (pickedSrc ? "Create pair" : "Resolve & continue")}
                </button>
                <button className="btn" onClick={() => setMode(pickedSrc ? "pick-dst" : "pick-src")}>← Back</button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Pairs table */}
      <div className="card">
        <div className="card-title">All channel pairs</div>
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>#</th><th>Source</th><th></th><th>Destination</th>
                <th>Status</th><th>Cursor</th><th>Last forward</th>
                {canEdit && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {pairs.map((p) => (
                <tr key={p.id}>
                  <td className="mono">{p.id}</td>
                  <td>
                    <div className="font-bold">{p.source_title || p.source_id}</div>
                    {p.source_username && <div className="text-xs text-muted mono">@{p.source_username}</div>}
                  </td>
                  <td><ArrowRight size={14} className="opacity-40" /></td>
                  <td>
                    <div className="font-bold">{p.dest_title || p.dest_id}</div>
                    {p.dest_username && <div className="text-xs text-muted mono">@{p.dest_username}</div>}
                  </td>
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
                  <td className="text-xs text-muted">
                    {p.last_forwarded_at ? new Date(p.last_forwarded_at).toLocaleString() : "—"}
                  </td>
                  {canEdit && (
                    <td>
                      <div className="flex gap-1">
                        <button className="btn btn-ghost btn-icon btn-sm" onClick={() => toggle(p)} title={p.enabled ? "Disable" : "Enable"}>
                          <Power size={14} />
                        </button>
                        <button className="btn btn-ghost btn-icon btn-sm" onClick={() => backfill(p)} title="Backfill from start">
                          <RefreshCw size={14} />
                        </button>
                        <button className="btn btn-ghost btn-icon btn-sm" onClick={() => del(p)} title="Delete">
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
              {pairs.length === 0 && (
                <tr><td colSpan={8} className="text-muted text-center">No pairs yet. Click "Add pair" to create one.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
