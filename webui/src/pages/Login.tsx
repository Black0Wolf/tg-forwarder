import { useState } from "react";
import { Bot, ArrowRight } from "lucide-react";
import { api, Admin } from "../api/client";
import { useTheme } from "../hooks/useTheme";
import { Sun, Moon } from "lucide-react";

export default function Login({ onLogin }: { onLogin: (a: Admin) => void }) {
  const { theme, toggle } = useTheme();
  const [tgUserId, setTgUserId] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"request" | "verify">("request");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const request = async () => {
    setBusy(true); setError(null);
    try {
      await api("/api/auth/request", {
        method: "POST",
        body: JSON.stringify({ tg_user_id: parseInt(tgUserId, 10) }),
      });
      setStep("verify");
    } catch (e: any) {
      setError(e.message || "Failed to send OTP");
    } finally { setBusy(false); }
  };

  const verify = async () => {
    setBusy(true); setError(null);
    try {
      const res = await api<{ ok: boolean; admin: Admin }>("/api/auth/verify", {
        method: "POST",
        body: JSON.stringify({ tg_user_id: parseInt(tgUserId, 10), code }),
      });
      onLogin(res.admin);
    } catch (e: any) {
      setError(e.message || "Invalid or expired code");
    } finally { setBusy(false); }
  };

  return (
    <div className="login-screen">
      <button className="btn btn-ghost btn-icon" onClick={toggle}
              style={{ position: "absolute", top: 20, right: 20 }}>
        {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
      </button>
      <div className="login-card">
        <div className="login-logo"><Bot size={28} /></div>
        <h1 className="login-title">Welcome back</h1>
        <p className="login-sub">Sign in with your Telegram account. We'll DM you a one-time code via the bot.</p>

        {error && <div className="alert alert-error">{error}</div>}

        {step === "request" ? (
          <>
            <label>Telegram user ID</label>
            <input
              className="input"
              placeholder="e.g. 123456789"
              value={tgUserId}
              onChange={(e) => setTgUserId(e.target.value)}
              inputMode="numeric"
              autoFocus
            />
            <button
              className="btn btn-primary mt-6"
              style={{ width: "100%", justifyContent: "center" }}
              disabled={busy || !tgUserId}
              onClick={request}
            >
              {busy ? <span className="spinner" /> : <>Send code <ArrowRight size={14} /></>}
            </button>
          </>
        ) : (
          <>
            <label>One-time code</label>
            <input
              className="input"
              placeholder="000000"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
              maxLength={6}
              style={{ textAlign: "center", letterSpacing: "0.4em", fontSize: 18 }}
              autoFocus
            />
            <button
              className="btn btn-primary mt-6"
              style={{ width: "100%", justifyContent: "center" }}
              disabled={busy || code.length < 6}
              onClick={verify}
            >
              {busy ? <span className="spinner" /> : <>Verify & sign in</>}
            </button>
            <button
              className="btn btn-ghost mt-4"
              style={{ width: "100%", justifyContent: "center" }}
              onClick={() => { setStep("request"); setCode(""); }}
            >
              ← Use a different account
            </button>
          </>
        )}
        <div style={{ marginTop: 24, fontSize: 11, color: "var(--text-subtle)", textAlign: "center" }}>
          Don't know your Telegram user ID? Message <code>@userinfobot</code> on Telegram.
        </div>
      </div>
    </div>
  );
}
