/**
 * Thin API client. All endpoints return JSON; throws on non-2xx.
 */
export async function api<T = any>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
    ...init,
  });
  if (res.status === 401) {
    // redirect to login
    if (location.pathname !== "/login") {
      location.href = "/login";
    }
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || JSON.stringify(j);
    } catch {}
    throw new Error(detail);
  }
  if (res.status === 204) return null as any;
  return res.json();
}

export type Admin = {
  id: number;
  tg_user_id: number;
  tg_username: string | null;
  tg_first_name: string | null;
  level: number;
  is_super: boolean;
  added_at: string;
  perms: Record<string, boolean>;
};

export type Pair = {
  id: number;
  name: string;
  source_id: number;
  source_title: string | null;
  source_username: string | null;
  dest_id: number;
  dest_title: string | null;
  dest_username: string | null;
  enabled: boolean;
  last_source_msg_id: number;
  backfill_complete: boolean;
  last_forwarded_at: string | null;
};

export type DashboardData = {
  admins: number;
  pairs: number;
  active_pairs: number;
  forwarded_total: number;
  forwarded_24h: number;
  forwarded_1h: number;
  forwarded_7d: number;
  paused: boolean;
  forward_mode: string;
  pairs_detail: Array<{
    id: number; name: string;
    source_id: number; source_title: string | null;
    dest_id: number; dest_title: string | null;
    enabled: boolean;
    last_source_msg_id: number;
    backfill_complete: boolean;
    last_forwarded_at: string | null;
    forwarded_total: number;
    last_msg_type: string | null;
    last_msg_preview: string | null;
  }>;
  recent_activity: Array<{
    id: number; pair_id: number;
    source_msg_id: number; dest_msg_id: number;
    msg_type: string; msg_preview: string | null;
    forwarded_at: string;
  }>;
  sparkline_24h: Array<{ hour: string; count: number }>;
};

export type LogEntry = {
  id: number;
  level: string;
  message: string;
  module: string | null;
  created_at: string;
};

export type HistoryEntry = {
  id: number;
  pair_id: number;
  source_title: string;
  dest_title: string;
  source_msg_id: number;
  dest_msg_id: number;
  msg_type: string;
  msg_preview: string | null;
  forwarded_at: string;
};

export type Connection = {
  id: number;
  kind: string;
  admin_id: number | null;
  ip: string | null;
  user_agent: string | null;
  detail: string | null;
  connected_at: string;
};
