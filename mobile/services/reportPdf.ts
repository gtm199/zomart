import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import { File, Paths } from "expo-file-system";
import { base64ToBytes } from "./receipt";

export const MAX_EXPORT_MONTHS = 3;

export const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export function parseIso(s: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s.trim())) return null;
  const [y, m, d] = s.trim().split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d ? dt : null;
}

/** Same day n months later (or earlier), clamped to month end — matches the backend. */
export function addMonths(d: Date, n: number) {
  const first = new Date(d.getFullYear(), d.getMonth() + n, 1);
  const lastDay = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  return new Date(first.getFullYear(), first.getMonth(), Math.min(d.getDate(), lastDay));
}

/** "" when fine, otherwise a message to show. */
export function validateExportRange(from: string, to: string): string {
  const a = parseIso(from), b = parseIso(to);
  if (!a || !b) return "Enter both dates as YYYY-MM-DD.";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  if (a > b) return "From date must be on or before To date.";
  if (b > today) return "To date cannot be in the future.";
  const max = addMonths(a, MAX_EXPORT_MONTHS);
  if (b > max) return `PDF export covers at most ${MAX_EXPORT_MONTHS} months. For this From date, the latest To date is ${iso(max)}.`;
  return "";
}

const esc = (v: unknown) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
const rs = (v: unknown) => `₹${esc(v)}`;

const table = (headers: string[], rows: (string | number)[][], rightFrom = 1) =>
  rows.length === 0
    ? `<p class="muted">Nothing in this period.</p>`
    : `<table><thead><tr>${headers.map((h, i) => `<th class="${i >= rightFrom ? "r" : ""}">${esc(h)}</th>`).join("")}</tr></thead>
       <tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td class="${i >= rightFrom ? "r" : ""}">${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;

export function buildReportHtml(o: { from: string; to: string; pl: any; sa: any; ag: any; shopName?: string }) {
  const { pl, sa, ag } = o;
  const collected = Object.entries(pl.money_collected_by_method ?? {}).map(([k, v]) => [esc(k.toUpperCase()), rs(v)]);
  const ageing = (title: string, block: any) => `
    <h2>${esc(title)}: ${rs(block.total)}</h2>
    ${table(["Bucket", "Amount"], Object.entries(block.buckets).map(([k, v]) => [esc(k), rs(v)]))}
    ${table(["Name", "Phone", "Balance"], block.rows.map((r: any) => [esc(r.name), esc(r.phone), rs(r.balance)]), 2)}`;

  return `<!doctype html><html><head><meta charset="utf-8"/>
<style>
  body { font-family: -apple-system, Roboto, Arial, sans-serif; color: #111827; font-size: 11px; margin: 28px; }
  h1 { font-size: 18px; margin: 0; color: #0f766e; }
  h2 { font-size: 13px; margin: 18px 0 6px; border-bottom: 1px solid #d1d5db; padding-bottom: 3px; }
  .muted { color: #6b7280; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 6px; }
  th, td { padding: 4px 6px; border-bottom: 1px solid #eef0f2; text-align: left; }
  th { background: #f6f7f8; font-weight: 600; }
  .r { text-align: right; }
  .total td { font-weight: 700; }
  tr { page-break-inside: avoid; }
</style></head><body>
  <h1>${esc(o.shopName || "Business report")}</h1>
  <div class="muted">Period: ${esc(o.from)} to ${esc(o.to)} · Generated ${esc(new Date().toLocaleString())}</div>

  <h2>Profit &amp; loss</h2>
  <table>
    <tr><td>Sales (after returns)</td><td class="r">${rs(pl.net_sales)}</td></tr>
    <tr><td>Tax included in sales</td><td class="r">${rs(pl.tax_included_in_sales)}</td></tr>
    <tr><td>Cost of goods sold</td><td class="r">${rs(pl.cost_of_goods_sold)}</td></tr>
    <tr class="total"><td>Gross profit</td><td class="r">${rs(pl.gross_profit)}</td></tr>
    <tr><td>Expenses</td><td class="r">${rs(pl.expenses_total)}</td></tr>
    <tr class="total"><td>Net profit</td><td class="r">${rs(pl.net_profit)}</td></tr>
  </table>

  <h2>Expenses by category</h2>
  ${table(["Category", "Amount"], pl.expenses_by_category.map((e: any) => [esc(e.category), rs(e.amount)]))}

  <h2>Money collected</h2>
  ${table(["Method", "Amount"], collected)}

  <h2>Sales by category</h2>
  ${table(["Category", "Sales", "Profit"], sa.by_category.map((c: any) => [esc(c.category), rs(c.sales), rs(c.profit)]))}

  <h2>Sales by product</h2>
  ${table(["Product", "Category", "Qty", "Sales", "Profit"],
    sa.all_products.map((p: any) => [esc(p.product), esc(p.category), esc(p.quantity), rs(p.sales), rs(p.profit)]), 2)}

  <h2>Not selling (in stock, no sales in period)</h2>
  ${table(["Product", "Stock", "Value at cost"], sa.slow_movers.map((p: any) => [esc(p.product), esc(p.stock), rs(p.stock_value_at_cost)]))}

  <p class="muted" style="margin-top:14px">Balances below are as of today, not for the selected period.</p>
  ${ageing("Customers owe you", ag.receivables)}
  ${ageing("You owe suppliers", ag.payables)}

  <p class="muted" style="margin-top:14px">${esc(pl.note)}</p>
</body></html>`;
}

/** Renders A4 PDF, saves it with a readable name, opens the share sheet (falls back to print window). */
export async function shareReportPdf(html: string, name: string) {
  let shareUri = "";
  try {
    const { uri, base64 } = await Print.printToFileAsync({ html, width: 595, height: 842, base64: true });
    shareUri = uri;
    if (base64) {
      const file = new File(Paths.cache, `${name.replace(/[^A-Za-z0-9_-]/g, "_")}.pdf`);
      if (file.exists) await file.delete();
      await file.create();
      await file.write(base64ToBytes(base64));
      shareUri = file.uri;
    }
  } catch {
    // keep whatever file we have
  }
  if (shareUri && (await Sharing.isAvailableAsync())) {
    await Sharing.shareAsync(shareUri, { mimeType: "application/pdf", dialogTitle: "Share report", UTI: "com.adobe.pdf" });
    return;
  }
  await Print.printAsync({ html });
}
