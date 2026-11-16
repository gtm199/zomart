import { AppState } from "react-native";
import { api, ApiError } from "./api";
import { GstConfig, getGstConfig, saveGstConfig } from "./gst";
import { backoff, kvGet, kvSet, listDue, markFailed, markSent, pendingCounts, upsertCustomers, upsertProducts } from "./localdb";

type Listener = () => void;
const listeners = new Set<Listener>();
export const onSyncChange = (l: Listener) => { listeners.add(l); return () => { listeners.delete(l); }; };
export const notifySync = () => listeners.forEach((l) => l());

let running = false;

/** Sends waiting bills one by one. Returns false when there is no internet. */
async function uploadPending(): Promise<boolean> {
  const rows = await listDue();
  for (const r of rows) {
    try {
      const sale = await api<{ invoice_number: string }>("/shop/sales/", { body: JSON.parse(r.payload) });
      await markSent(r.txn_id, sale.invoice_number);
    } catch (e: any) {
      if (e instanceof ApiError) {
        if (e.status === 0) { await backoff(r.txn_id, r.attempts, "No internet connection"); return false; }
        if (e.status === 401) { await backoff(r.txn_id, r.attempts, "Please sign in again"); return true; }
        if (e.status === 429 || e.status >= 500) { await backoff(r.txn_id, r.attempts, e.message); return true; }
        await markFailed(r.txn_id, e.message); // the server said no: needs a human
      } else {
        await backoff(r.txn_id, r.attempts, "Unexpected error");
      }
    }
  }
  return true;
}

type SyncResponse = { server_time: string; products: any[]; customers: any[]; gst?: GstConfig };

/** Downloads only what changed since the last successful sync. When the shop's GST settings changed, it downloads
 *  every product again so each one carries its GST rate (or loses it when GST was switched off). */
export async function syncDown() {
  const since = await kvGet("last_sync");
  const r = await api<SyncResponse>(`/shop/sync/${since ? `?since=${encodeURIComponent(since)}` : ""}`);
  const gst: GstConfig = r.gst ?? { enabled: false };
  const before = await getGstConfig();
  const changed = before.enabled !== gst.enabled || (before.scheme ?? "") !== (gst.scheme ?? "");
  await saveGstConfig(gst);
  if (changed && since) {
    const full = await api<SyncResponse>("/shop/sync/");
    await upsertProducts(full.products);
    await upsertCustomers(full.customers);
    await kvSet("last_sync", full.server_time);
    return;
  }
  await upsertProducts(r.products);
  await upsertCustomers(r.customers);
  await kvSet("last_sync", r.server_time);
}

/** After changing GST settings or a product's GST details: refresh the phone's copy now. */
export async function refreshAfterGstChange() {
  await kvSet("last_sync", "");
  return runSync();
}

export async function runSync(): Promise<boolean> {
  if (running) return false;
  running = true;
  let online = false;
  try {
    online = await uploadPending(); // upload first, so the download already contains our own sales
    if (online) await syncDown();
  } catch {
    /* offline or server trouble: the loop tries again later */
  } finally {
    running = false;
    notifySync();
  }
  return online;
}

export async function getStatus() {
  const c = await pendingCounts();
  return { waiting: c.waiting, failed: c.failed, lastSync: await kvGet("last_sync") };
}

export function startSyncLoop() {
  runSync();
  const timer = setInterval(() => { runSync(); }, 20000);
  const sub = AppState.addEventListener("change", (s) => { if (s === "active") runSync(); });
  return () => { clearInterval(timer); sub.remove(); };
}