export type Role = "admin" | "supervisor" | "viewer";

export type User = { id: number; username: string; role: Role; is_active: boolean; created_at?: string };

const TOKEN = "el_token";

export function token() {
  return localStorage.getItem(TOKEN) || "";
}

export function setSession(value: string) {
  if (value) localStorage.setItem(TOKEN, value);
  else localStorage.removeItem(TOKEN);
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const current = token();
  if (current) headers.set("Authorization", `Bearer ${current}`);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && !path.endsWith("/login")) {
    setSession("");
    if (!location.pathname.startsWith("/login")) location.assign("/login");
    throw new Error("Authentication required");
  }
  if (!response.ok) {
    const text = await response.text();
    let detail = text || response.statusText;
    try {
      const parsed = JSON.parse(text);
      detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
    } catch {
      /* plain text */
    }
    throw new Error(detail);
  }
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) return response.json();
  return undefined as T;
}

export async function download(path: string) {
  const headers = new Headers();
  if (token()) headers.set("Authorization", `Bearer ${token()}`);
  const response = await fetch(path, { headers });
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {
      /* keep */
    }
    throw new Error(typeof detail === "string" ? detail : "Export failed");
  }
  const blob = await response.blob();
  const match = /filename="([^"]+)"/.exec(response.headers.get("content-disposition") || "");
  const anchor = document.createElement("a");
  const url = URL.createObjectURL(blob);
  anchor.href = url;
  anchor.download = match?.[1] || "export";
  anchor.click();
  URL.revokeObjectURL(url);
}

/** Fetch a file with the login token and return a temporary address that an <iframe> can show. */
export async function blobUrl(path: string): Promise<string> {
  const headers = new Headers();
  if (token()) headers.set("Authorization", `Bearer ${token()}`);
  const response = await fetch(path, { headers });
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {
      /* keep */
    }
    throw new Error(typeof detail === "string" ? detail : "Preview failed");
  }
  return URL.createObjectURL(await response.blob());
}

export function qs(params: Record<string, string | number | boolean | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}
