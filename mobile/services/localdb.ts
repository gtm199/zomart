import * as SQLite from "expo-sqlite";

export type LocalProduct = {
  id: number; name: string; barcodes: string; selling_price: string; stock_qty: string;
  is_enabled: number; whole: number; pending_qty: number; unit: string; loose: number;
};
export type LocalCustomer = {
  id: number; name: string; phone: string; whatsapp_number: string; balance: string; is_active: number; credit_limit: string | null;
};
export type PendingSale = {
  txn_id: string; payload: string; summary: string; created_at: string;
  status: "waiting" | "failed" | "sent"; attempts: number; next_try: number; last_error: string; invoice: string;
};
export type HeldCart = { id: number; name: string; payload: string; created_at: string };

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

async function addMissingColumns(d: SQLite.SQLiteDatabase) {
  const need: [string, string, string][] = [
    ["products", "unit", "TEXT NOT NULL DEFAULT 'pc'"],
    ["products", "loose", "INTEGER NOT NULL DEFAULT 0"],
    ["customers", "credit_limit", "TEXT"],
  ];
  let added = false;
  for (const [table, col, def] of need) {
    const cols = await d.getAllAsync<{ name: string }>(`PRAGMA table_info(${table})`);
    if (!cols.some((c) => c.name === col)) {
      await d.execAsync(`ALTER TABLE ${table} ADD COLUMN ${col} ${def}`);
      added = true;
    }
  }
  if (added) await d.runAsync("DELETE FROM kv WHERE key = 'last_sync'"); // download everything again so the new columns fill in
}

export function db() {
  if (!dbPromise) {
    dbPromise = (async () => {
      const d = await SQLite.openDatabaseAsync("kirana.db");
      await d.execAsync(`
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY NOT NULL, value TEXT);
        CREATE TABLE IF NOT EXISTS products (
          id INTEGER PRIMARY KEY NOT NULL, name TEXT NOT NULL, barcodes TEXT NOT NULL DEFAULT '',
          selling_price TEXT NOT NULL, stock_qty TEXT NOT NULL, is_enabled INTEGER NOT NULL DEFAULT 1,
          whole INTEGER NOT NULL DEFAULT 0, pending_qty REAL NOT NULL DEFAULT 0,
          unit TEXT NOT NULL DEFAULT 'pc', loose INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS customers (
          id INTEGER PRIMARY KEY NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
          whatsapp_number TEXT NOT NULL DEFAULT '', balance TEXT NOT NULL DEFAULT '0', is_active INTEGER NOT NULL DEFAULT 1,
          credit_limit TEXT);
        CREATE TABLE IF NOT EXISTS pending_sales (
          txn_id TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'waiting', attempts INTEGER NOT NULL DEFAULT 0, next_try INTEGER NOT NULL DEFAULT 0,
          last_error TEXT NOT NULL DEFAULT '', invoice TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS held_carts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
      `);
      await addMissingColumns(d);
      return d;
    })();
  }
  return dbPromise;
}

// ---------- small key/value store ----------
export async function kvGet(key: string) {
  const d = await db();
  const r = await d.getFirstAsync<{ value: string }>("SELECT value FROM kv WHERE key = ?", [key]);
  return r?.value ?? null;
}
export async function kvSet(key: string, value: string) {
  const d = await db();
  await d.runAsync("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", [key, value]);
}

// ---------- housekeeping ----------
export async function clearAll() {
  const d = await db();
  await d.execAsync("DELETE FROM products; DELETE FROM customers; DELETE FROM pending_sales; DELETE FROM held_carts; DELETE FROM kv;");
}
/** A different shop on the same phone must never see the previous shop's data. */
export async function prepareLocalDb(shopId: number) {
  const current = await kvGet("shop_id");
  if (current !== String(shopId)) {
    await clearAll();
    await kvSet("shop_id", String(shopId));
  }
}

// ---------- products and customers (copied from the server) ----------
export async function upsertProducts(rows: any[]) {
  const d = await db();
  await d.withTransactionAsync(async () => {
    for (const r of rows) {
      await d.runAsync(
        `INSERT INTO products (id, name, barcodes, selling_price, stock_qty, is_enabled, whole, unit, loose) VALUES (?,?,?,?,?,?,?,?,?)
         ON CONFLICT(id) DO UPDATE SET name=excluded.name, barcodes=excluded.barcodes, selling_price=excluded.selling_price,
           stock_qty=excluded.stock_qty, is_enabled=excluded.is_enabled, whole=excluded.whole, unit=excluded.unit, loose=excluded.loose`,
        [r.id, r.name, "|" + r.barcodes.join("|") + "|", r.selling_price, r.stock_qty, r.is_enabled ? 1 : 0, r.whole ? 1 : 0,
         r.unit ?? "pc", r.loose ? 1 : 0]
      );
    }
  });
}
export async function upsertCustomers(rows: any[]) {
  const d = await db();
  await d.withTransactionAsync(async () => {
    for (const r of rows) {
      await d.runAsync(
        `INSERT INTO customers (id, name, phone, whatsapp_number, balance, is_active, credit_limit) VALUES (?,?,?,?,?,?,?)
         ON CONFLICT(id) DO UPDATE SET name=excluded.name, phone=excluded.phone, whatsapp_number=excluded.whatsapp_number,
           balance=excluded.balance, is_active=excluded.is_active, credit_limit=excluded.credit_limit`,
        [r.id, r.name, r.phone, r.whatsapp_number, r.balance, r.is_active ? 1 : 0, r.credit_limit ?? null]
      );
    }
  });
}

export async function searchProducts(term: string) {
  const d = await db();
  const like = `%${term.replace(/[%_]/g, "")}%`;
  return d.getAllAsync<LocalProduct>(
    "SELECT * FROM products WHERE is_enabled = 1 AND (name LIKE ? OR barcodes LIKE ?) ORDER BY name LIMIT 30", [like, like]);
}
export async function getProduct(id: number) {
  const d = await db();
  return d.getFirstAsync<LocalProduct>("SELECT * FROM products WHERE id = ?", [id]);
}
export async function findByBarcode(code: string) {
  const d = await db();
  const tries = [code];
  if (code.length === 12) tries.push("0" + code);          // UPC-A scanned as EAN-13 and the reverse
  if (code.length === 13 && code.startsWith("0")) tries.push(code.slice(1));
  for (const c of tries) {
    const row = await d.getFirstAsync<LocalProduct>("SELECT * FROM products WHERE barcodes LIKE ?", [`%|${c}|%`]);
    if (row) return row;
  }
  return null;
}
export async function searchCustomers(term: string) {
  const d = await db();
  const like = `%${term.replace(/[%_]/g, "")}%`;
  return d.getAllAsync<LocalCustomer>(
    "SELECT * FROM customers WHERE is_active = 1 AND (name LIKE ? OR phone LIKE ?) ORDER BY name LIMIT 20", [like, like]);
}
export async function getCustomer(id: number) {
  const d = await db();
  return d.getFirstAsync<LocalCustomer>("SELECT * FROM customers WHERE id = ?", [id]);
}

// ---------- bills put on hold (this phone only) ----------
export async function holdCart(name: string, payload: object) {
  const d = await db();
  await d.runAsync("INSERT INTO held_carts (name, payload, created_at) VALUES (?,?,?)", [name, JSON.stringify(payload), new Date().toISOString()]);
}
/** Held bills older than two days are dropped: the goods were surely sold or put back by then. */
export async function listHeld() {
  const d = await db();
  await d.runAsync("DELETE FROM held_carts WHERE created_at < ?", [new Date(Date.now() - 48 * 3600 * 1000).toISOString()]);
  return d.getAllAsync<HeldCart>("SELECT * FROM held_carts ORDER BY id DESC");
}
export async function deleteHeld(id: number) {
  const d = await db();
  await d.runAsync("DELETE FROM held_carts WHERE id = ?", [id]);
}

// ---------- the queue of bills waiting to upload ----------
export async function queueSale(txnId: string, payload: any, summary: string) {
  const d = await db();
  await d.withTransactionAsync(async () => {
    await d.runAsync("INSERT INTO pending_sales (txn_id, payload, summary, created_at) VALUES (?,?,?,?)",
      [txnId, JSON.stringify(payload), summary, new Date().toISOString()]);
    for (const it of payload.items) {
      await d.runAsync("UPDATE products SET pending_qty = pending_qty + ? WHERE id = ?", [Number(it.quantity), it.shop_product]);
    }
  });
}
export async function listAll() {
  const d = await db();
  return d.getAllAsync<PendingSale>("SELECT * FROM pending_sales ORDER BY created_at DESC");
}
export async function listDue() {
  const d = await db();
  return d.getAllAsync<PendingSale>(
    "SELECT * FROM pending_sales WHERE status = 'waiting' AND next_try <= ? ORDER BY created_at ASC", [Date.now()]);
}
export async function pendingCounts() {
  const d = await db();
  const rows = await d.getAllAsync<{ status: string; n: number }>(
    "SELECT status, COUNT(*) AS n FROM pending_sales WHERE status != 'sent' GROUP BY status");
  const get = (s: string) => rows.find((r) => r.status === s)?.n ?? 0;
  return { waiting: get("waiting"), failed: get("failed") };
}
export async function pendingCount() {
  const c = await pendingCounts();
  return c.waiting + c.failed;
}

/** Uploaded. The next delta sync brings the new stock; we only stop counting it as "pending" here. */
export async function markSent(txnId: string, invoice: string) {
  const d = await db();
  const row = await d.getFirstAsync<PendingSale>("SELECT * FROM pending_sales WHERE txn_id = ?", [txnId]);
  if (!row) return;
  const payload = JSON.parse(row.payload);
  await d.withTransactionAsync(async () => {
    for (const it of payload.items) {
      await d.runAsync("UPDATE products SET pending_qty = MAX(0, pending_qty - ?) WHERE id = ?", [Number(it.quantity), it.shop_product]);
    }
    await d.runAsync("UPDATE pending_sales SET status = 'sent', invoice = ?, last_error = '' WHERE txn_id = ?", [invoice, txnId]);
    await d.runAsync(
      "DELETE FROM pending_sales WHERE status = 'sent' AND txn_id NOT IN (SELECT txn_id FROM pending_sales WHERE status = 'sent' ORDER BY created_at DESC LIMIT 30)");
  });
}
export async function markFailed(txnId: string, message: string) {
  const d = await db();
  await d.runAsync("UPDATE pending_sales SET status = 'failed', last_error = ? WHERE txn_id = ?", [message, txnId]);
}
/** Try again later: waits 5s, 10s, 20s ... up to 5 minutes. */
export async function backoff(txnId: string, attempts: number, message: string) {
  const d = await db();
  const wait = Math.min(300000, 5000 * 2 ** attempts);
  await d.runAsync("UPDATE pending_sales SET attempts = ?, next_try = ?, last_error = ? WHERE txn_id = ?",
    [attempts + 1, Date.now() + wait, message, txnId]);
}
export async function retrySale(txnId: string) {
  const d = await db();
  await d.runAsync("UPDATE pending_sales SET status = 'waiting', attempts = 0, next_try = 0, last_error = '' WHERE txn_id = ?", [txnId]);
}
/** Throw away a bill that can never upload (the stock it reserved is released). */
export async function discardSale(txnId: string) {
  const d = await db();
  const row = await d.getFirstAsync<PendingSale>("SELECT * FROM pending_sales WHERE txn_id = ?", [txnId]);
  if (!row) return;
  const payload = JSON.parse(row.payload);
  await d.withTransactionAsync(async () => {
    for (const it of payload.items) {
      await d.runAsync("UPDATE products SET pending_qty = MAX(0, pending_qty - ?) WHERE id = ?", [Number(it.quantity), it.shop_product]);
    }
    await d.runAsync("DELETE FROM pending_sales WHERE txn_id = ?", [txnId]);
  });
}