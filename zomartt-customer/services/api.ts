import * as SecureStore from "expo-secure-store";

export const BASE = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

let token: string | null = null;
export const setToken = (t: string | null) => { token = t; };

export const keep = {
  get: (k: string) => SecureStore.getItemAsync(k),
  set: (k: string, v: string) => SecureStore.setItemAsync(k, v),
  del: (k: string) => SecureStore.deleteItemAsync(k),
};

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) { super(message); }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Shopper ${token}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 70000);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: opts.method ?? (opts.body ? "POST" : "GET"),
      headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
    });
  } catch {
    throw new ApiError("Cannot reach the server. Check your internet and try again.", 0, "network");
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const first = typeof data === "object" ? Object.values(data as object).flat()[0] : null;
    throw new ApiError((data as any).detail ?? (typeof first === "string" ? first : "Request failed"), res.status, (data as any).code);
  }
  return data as T;
}