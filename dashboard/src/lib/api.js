// API client. The operator key for write routes is a per-viewer convenience
// kept in localStorage (wrapped: storage can be unavailable in private windows).

const KEY = "ushma.apiKey";

export function getApiKey() {
  try {
    return localStorage.getItem(KEY) || "ushma-dev-key";
  } catch {
    return "ushma-dev-key";
  }
}

export function setApiKey(v) {
  try {
    localStorage.setItem(KEY, v);
  } catch {
    /* storage unavailable: key lasts for this page only */
  }
}

async function request(method, path, body) {
  const res = await fetch(`/v1${path}`, {
    method,
    headers: { "content-type": "application/json", ...(method === "GET" ? {} : { "x-api-key": getApiKey() }) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text && res.headers.get("content-type")?.includes("json") ? JSON.parse(text) : text;
  if (!res.ok) throw new Error(data?.error ? `${data.error}${data.detail ? `: ${data.detail}` : ""}` : `HTTP ${res.status}`);
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b ?? {}),
  del: (p) => request("DELETE", p),
  // Subscriptions and deliveries expose operator data, so they need the key on GET too.
  getAuth: (p) =>
    fetch(`/v1${p}`, { headers: { "x-api-key": getApiKey() } }).then(async (r) => {
      const d = await r.json();
      if (!r.ok) throw new Error(d.error ?? `HTTP ${r.status}`);
      return d;
    }),
};
