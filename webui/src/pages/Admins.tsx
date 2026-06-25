import { useEffect, useState } from "react";
import { UserPlus, Trash2, Shield, Crown } from "lucide-react";
import { api, Admin } from "../api/client";

const PERM_LABELS: Record<string, string> = {
  manage_admins: "Manage admins",
  edit_channels: "Edit channels",
  edit_settings: "Edit settings",
  pause_resume: "Pause / resume",
  view_logs: "View logs",
  view_history: "View history",
  backfill: "Trigger backfill",
  clear_logs: "Clear history / logs",
};

export default function Admins({ me }: { me: Admin | null }) {
  const [admins, setAdmins] = useState<Admin[]>([]);
  const [permsList, setPermsList] = useState<string[]>(Object.keys(PERM_LABELS));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [newUid, setNewUid] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [newPerms, setNewPerms] = useState<Record<string, boolean>>({});

  const load = async () => {
    try {
      const [list, permsResp] = await Promise.all([
        api<Admin[]>("/api/admins"),
        api<{ perms: { value: string }[] }>("/api/admins/perms"),
      ]);
      setAdmins(list);
      setPermsList(permsResp.perms.map(p => p.value));
    } catch (e: any) { setError(e.message); }
  };

  useEffect(() => { load(); }, []);

  const canManage = me?.is_super || me?.perms.manage_admins;

  const add = async () => {
    setBusy(true); setError(null);
    try {
      await api("/api/admins", {
        method: "POST",
        body: JSON.stringify({
          tg_user_id: parseInt(newUid, 10),
          tg_username: newUsername || null,
          perms: Object.entries(newPerms).filter(([, v]) => v).map(([k]) => k),
        }),
      });
      setNewUid(""); setNewUsername(""); setNewPerms({});
      setShowAdd(false);
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  const remove = async (uid: number) => {
    if (!confirm(`Remove admin ${uid}?`)) return;
    try {
      await api(`/api/admins/${uid}`, { method: "DELETE" });
      await load();
    } catch (e: any) { setError(e.message); }
  };

  const togglePerm = async (uid: number, perm: string, enabled: boolean) => {
    try {
      await api(`/api/admins/${uid}/toggle`, {
        method: "POST",
        body: JSON.stringify({ perm, enabled }),
      });
      await load();
    } catch (e: any) { setError(e.message); }
  };

  return (
    <>
      {error && <div className="alert alert-error mb-4">{error}</div>}

      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="text-xs text-muted">Total: {admins.length} admin{admins.length !== 1 ? "s" : ""}</div>
        </div>
        {canManage && (
          <button className="btn btn-primary" onClick={() => setShowAdd(!showAdd)}>
            <UserPlus size={14} /> Add admin
          </button>
        )}
      </div>

      {showAdd && canManage && (
        <div className="card mb-6">
          <div className="card-title">Add new admin</div>
          <div className="grid grid-2">
            <div>
              <label>Telegram user ID</label>
              <input className="input" value={newUid} onChange={(e) => setNewUid(e.target.value)} placeholder="123456789" />
            </div>
            <div>
              <label>Username (optional)</label>
              <input className="input" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} placeholder="@alice" />
            </div>
          </div>
          <label className="mt-4">Initial permissions</label>
          <div className="grid grid-2">
            {permsList.map((p) => (
              <label key={p} className="flex items-center gap-3" style={{ textTransform: "none", letterSpacing: 0, color: "var(--text)", fontWeight: 400, fontSize: 13, marginBottom: 8 }}>
                <input
                  type="checkbox"
                  checked={!!newPerms[p]}
                  onChange={(e) => setNewPerms({ ...newPerms, [p]: e.target.checked })}
                />
                {PERM_LABELS[p] || p}
              </label>
            ))}
          </div>
          <div className="flex gap-2 mt-4">
            <button className="btn btn-primary" disabled={busy || !newUid} onClick={add}>
              {busy ? <span className="spinner" /> : "Add admin"}
            </button>
            <button className="btn" onClick={() => setShowAdd(false)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-title">All admins</div>
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th></th><th>User ID</th><th>Username</th><th>Level</th>
                {permsList.map(p => <th key={p} title={PERM_LABELS[p] || p} style={{ fontSize: 10 }}>{(PERM_LABELS[p] || p).split(" ")[0]}</th>)}
                {canManage && <th></th>}
              </tr>
            </thead>
            <tbody>
              {admins.map((a) => (
                <tr key={a.id}>
                  <td>
                    {a.is_super
                      ? <Crown size={14} color="var(--warning)" />
                      : <Shield size={14} color="var(--text-subtle)" />}
                  </td>
                  <td className="mono">{a.tg_user_id}</td>
                  <td>{a.tg_username || a.tg_first_name || "—"}</td>
                  <td>
                    {a.is_super
                      ? <span className="badge badge-warning">super</span>
                      : <span className="badge badge-muted">L{a.level}</span>}
                  </td>
                  {permsList.map(p => (
                    <td key={p} className="text-center">
                      {a.is_super ? (
                        <span className="badge badge-success">✓</span>
                      ) : (
                        <label className="switch">
                          <input
                            type="checkbox"
                            checked={!!a.perms[p]}
                            onChange={(e) => togglePerm(a.tg_user_id, p, e.target.checked)}
                            disabled={!canManage}
                          />
                          <span className="switch-track"><span className="switch-thumb" /></span>
                        </label>
                      )}
                    </td>
                  ))}
                  {canManage && (
                    <td>
                      {!a.is_super && (
                        <button className="btn btn-ghost btn-icon btn-sm" onClick={() => remove(a.tg_user_id)} title="Remove">
                          <Trash2 size={14} />
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
