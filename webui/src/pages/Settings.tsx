import { useEffect, useState } from "react";
import { Pause, Play, RefreshCw, Save } from "lucide-react";
import { api, Admin } from "../api/client";

export default function Settings({ me }: { me: Admin | null }) {
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = async () => {
    try { setData(await api("/api/settings")); }
    catch (e: any) { setError(e.message); }
  };
  useEffect(() => { load(); }, []);

  const canPause = me?.is_super || me?.perms.pause_resume;
  const canBackfill = me?.is_super || me?.perms.backfill;

  const togglePause = async () => {
    setBusy(true);
    try {
      await api("/api/settings/pause", {
        method: "POST",
        body: JSON.stringify({ paused: !data.paused }),
      });
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  const backfillAll = async () => {
    if (!confirm("Trigger backfill on ALL pairs from message id 0? This will re-scan every source channel from the very beginning.")) return;
    setBusy(true);
    try {
      const r = await api("/api/settings/backfill", {
        method: "POST",
        body: JSON.stringify({ pair_id: null, from_msg_id: 0 }),
      });
      setMsg(`Backfill triggered on ${r.triggered} pair(s).`);
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  if (!data) return <div className="empty"><span className="spinner" style={{ width: 28, height: 28 }} /></div>;

  return (
    <>
      {error && <div className="alert alert-error mb-4">{error}</div>}
      {msg && <div className="alert alert-success mb-4">{msg}</div>}

      <div className="grid grid-2 mb-6">
        <div className="card">
          <div className="card-title">Forwarder state</div>
          <div className="flex items-center gap-3 mb-6">
            {data.paused
              ? <><Pause size={22} color="var(--warning)" /> <span className="font-bold" style={{ fontSize: 18 }}>Paused</span></>
              : <><Play size={22} color="var(--success)" /> <span className="font-bold" style={{ fontSize: 18 }}>Running</span></>}
          </div>
          <button
            className="btn btn-primary"
            onClick={togglePause}
            disabled={!canPause || busy}
          >
            {busy ? <span className="spinner" /> : data.paused ? <><Play size={14} /> Resume</> : <><Pause size={14} /> Pause</>}
          </button>
          {!canPause && <div className="text-xs text-muted mt-4">You don't have the <code>pause_resume</code> permission.</div>}
        </div>

        <div className="card">
          <div className="card-title">Backfill</div>
          <div className="text-sm mb-4">
            Trigger a full re-scan of every source channel from the very first message.
            Useful after changing the destination channel or recovering from a corrupt cursor.
          </div>
          <button
            className="btn btn-primary"
            onClick={backfillAll}
            disabled={!canBackfill || busy}
          >
            <RefreshCw size={14} /> Backfill all pairs
          </button>
          {!canBackfill && <div className="text-xs text-muted mt-4">You don't have the <code>backfill</code> permission.</div>}
        </div>
      </div>

      <div className="card">
        <div className="card-title">Runtime configuration</div>
        <div className="grid grid-2">
          <Field label="Forward mode" value={data.forward_mode} />
          <Field label="Initial backfill" value={data.initial_backfill ? "yes" : "no"} />
          <Field label="Backfill batch size" value={data.backfill_batch_size} />
          <Field label="Backfill delay (ms)" value={data.backfill_delay_ms} />
          <Field label="Live poll interval (s)" value={data.live_poll_interval_s} />
          <Field label="Web port" value={data.web_port} />
          <Field label="Web base URL" value={data.web_base_url} />
        </div>
        <div className="text-xs text-muted mt-4">
          To change these values, edit <code>config.yaml</code> and restart the service.
        </div>
      </div>
    </>
  );
}

function Field({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <div className="text-xs text-muted" style={{ textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>{label}</div>
      <div className="font-mono mt-4" style={{ fontWeight: 600 }}>{String(value)}</div>
    </div>
  );
}
