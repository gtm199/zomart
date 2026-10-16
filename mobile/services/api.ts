import * as SecureStore from "expo-secure-store";

export const BASE = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

let token: string | null = null;
let shopId: number | null = null;

export function setAuth(t: string | null, s: number | null) { token = t; shopId = s; }

export async function saveStored(key: string, value: string | null) {
  if (value === null) await SecureStore.deleteItemAsync(key);
  else await SecureStore.setItemAsync(key, value);
}
export const loadStored = (key: string) => SecureStore.getItemAsync(key);

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) { super(message); }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Token ${token}`;
  if (shopId) headers["X-Shop-ID"] = String(shopId);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: opts.method ?? (opts.body ? "POST" : "GET"),
      headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError("Cannot reach the server. Check your internet / API address.", 0, "network");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const first = typeof data === "object" ? Object.values(data as object).flat()[0] : null;
    throw new ApiError((data as any).detail ?? (typeof first === "string" ? first : "Request failed"), res.status, (data as any).code);
  }
  return data as T;
}
