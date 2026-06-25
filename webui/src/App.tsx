import { useEffect, useState } from "react";
import { NavLink, Route, Routes, Navigate, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Users, Radio, Settings as SettingsIcon,
  ScrollText, History as HistoryIcon, Plug, Menu, X, Sun, Moon,
  LogOut, Bot,
} from "lucide-react";
import { useTheme } from "./hooks/useTheme";
import { api, Admin } from "./api/client";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Admins from "./pages/Admins";
import Channels from "./pages/Channels";
import Settings from "./pages/Settings";
import Logs from "./pages/Logs";
import History from "./pages/History";
import Connections from "./pages/Connections";

const NAV = [
  { section: "Overview", items: [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  ]},
  { section: "Management", items: [
    { to: "/admins", label: "Admins", icon: Users },
    { to: "/channels", label: "Channels", icon: Radio },
    { to: "/history", label: "History", icon: HistoryIcon },
    { to: "/connections", label: "Connections", icon: Plug },
  ]},
  { section: "System", items: [
    { to: "/settings", label: "Settings", icon: SettingsIcon },
    { to: "/logs", label: "Logs", icon: ScrollText },
  ]},
];

export default function App() {
  const { theme, toggle } = useTheme();
  const [me, setMe] = useState<Admin | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [bootChecked, setBootChecked] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (location.pathname === "/login") {
      setBootChecked(true);
      return;
    }
    api<Admin>("/api/auth/me")
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setBootChecked(true));
  }, [location.pathname]);

  if (!bootChecked) {
    return <div style={{ display: "grid", placeItems: "center", height: "100vh" }}>
      <span className="spinner" style={{ width: 24, height: 24 }} />
    </div>;
  }

  if (!me && location.pathname !== "/login") {
    return <Navigate to="/login" replace />;
  }

  if (location.pathname === "/login") {
    return <Login onLogin={(a) => { setMe(a); navigate("/"); }} />;
  }

  return (
    <div className="app-shell">
      {/* Mobile backdrop */}
      <div className={`backdrop ${sidebarOpen ? "show" : ""}`} onClick={() => setSidebarOpen(false)} />

      {/* Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-logo"><Bot size={18} /></div>
          <div>
            <div className="brand-name">tg-forwarder</div>
            <div className="brand-sub">control panel</div>
          </div>
        </div>

        <nav className="nav">
          {NAV.map((group) => (
            <div key={group.section}>
              <div className="nav-section">{group.section}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                  onClick={() => setSidebarOpen(false)}
                >
                  <item.icon size={18} />
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="flex items-center gap-3" style={{ padding: "0 4px" }}>
            <div className="brand-logo" style={{ width: 28, height: 28 }}>
              {(me?.tg_first_name || me?.tg_username || "?").slice(0, 1).toUpperCase()}
            </div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis" }}>
                {me?.tg_first_name || me?.tg_username || me?.tg_user_id}
              </div>
              <div className="text-xs text-muted">
                {me?.is_super ? "super-admin" : `level ${me?.level}`}
              </div>
            </div>
          </div>
          <button
            className="btn btn-ghost btn-sm"
            onClick={async () => { await api("/api/auth/logout", { method: "POST" }); setMe(null); navigate("/login"); }}
          >
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="main">
        <header className="topbar">
          <div className="flex items-center gap-3">
            <button className="btn btn-ghost btn-icon mobile-menu-btn" onClick={() => setSidebarOpen(true)}>
              <Menu size={18} />
            </button>
            <div className="topbar-title">{pageTitle(location.pathname)}</div>
          </div>
          <div className="topbar-actions">
            <button className="btn btn-ghost btn-icon" onClick={toggle} title="Toggle theme">
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>
        </header>

        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard me={me} />} />
            <Route path="/admins" element={<Admins me={me} />} />
            <Route path="/channels" element={<Channels me={me} />} />
            <Route path="/history" element={<History me={me} />} />
            <Route path="/connections" element={<Connections me={me} />} />
            <Route path="/settings" element={<Settings me={me} />} />
            <Route path="/logs" element={<Logs me={me} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

function pageTitle(path: string): string {
  if (path === "/") return "Dashboard";
  if (path.startsWith("/admins")) return "Admins";
  if (path.startsWith("/channels")) return "Channels";
  if (path.startsWith("/history")) return "History";
  if (path.startsWith("/connections")) return "Connections";
  if (path.startsWith("/settings")) return "Settings";
  if (path.startsWith("/logs")) return "Logs";
  return "tg-forwarder";
}
