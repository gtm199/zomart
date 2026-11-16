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

/** "" when fine, otherwise a message to show. maxMonths comes from the server (/shop/reports/limits/). */
export function validateExportRange(from: string, to: string, maxMonths = MAX_EXPORT_MONTHS): string {
  const a = parseIso(from), b = parseIso(to);
  if (!a || !b) return "Enter both dates as YYYY-MM-DD.";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  if (a > b) return "From date must be on or before To date.";
  if (b > today) return "To date cannot be in the future.";
  const max = addMonths(a, maxMonths);
  if (b > max) return `This covers at most ${maxMonths} months. For this From date, the latest To date is ${iso(max)}.`;
  return "";
}

/** Indian financial year (1 April - 31 March) that contains the date; offset -1 = the year before. */
export function financialYear(d: Date, offset = 0): [Date, Date] {
  const startYear = (d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1) + offset;
  return [new Date(startYear, 3, 1), new Date(startYear + 1, 2, 31)];
}

export const GST_REPORT_DISCLAIMER =
  "This report is an aid for filing, not a filed return. It is made from the rates and details entered in the app. Check it with your CA before filing.";

/** GST report (server totals only - the phone never adds up bills). The header repeats on every printed page. */
export function buildGstReportHtml(r: any) {
  const gst = (rows: any[], cols: [string, string][], rightFrom = 1) =>
    table(cols.map((c) => c[0]), rows.map((row) => cols.map(([, k]) => esc(row[k]))), rightFrom);
  const block = (title: string, b: any, roundOff = false) => `
    <tr><td>${esc(title)} (${esc(b.count)})</td><td class="r">${esc(b.taxable)}</td><td class="r">${esc(b.cgst)}</td>
      <td class="r">${esc(b.sgst)}</td><td class="r">${esc(b.igst)}</td><td class="r">${esc(b.tax)}</td><td class="r">${esc(b.total)}</td></tr>
    ${roundOff && Number(b.round_off) !== 0 ? `<tr><td colspan="6">Round off included in total</td><td class="r">${esc(b.round_off)}</td></tr>` : ""}`;
  const composition = r.shop.scheme === "composition";
  const truncated = (n: number) => (n > r.list_limit ? `<p class="muted">Showing the first ${r.list_limit} of ${n}. Totals above cover all of them.</p>` : "");
  const body = `
    <h2>Summary</h2>
    <table><thead><tr><th></th><th class="r">Taxable</th><th class="r">CGST</th><th class="r">SGST</th><th class="r">IGST</th><th class="r">Total tax</th><th class="r">Value</th></tr></thead>
      <tbody>${block(composition ? "Bills of supply" : "Invoices", r.invoices, true)}${block("Credit notes", r.credit_notes)}
        <tr class="total"><td>Net</td><td class="r">${esc(r.net.taxable)}</td><td class="r">${esc(r.net.cgst)}</td><td class="r">${esc(r.net.sgst)}</td>
          <td class="r">${esc(r.net.igst)}</td><td class="r">${esc(r.net.tax)}</td><td class="r">${esc(r.net.total)}</td></tr></tbody></table>
    <p class="muted">Invoice numbers ${esc(r.first_invoice ?? "-")} to ${esc(r.last_invoice ?? "-")}.
      ${r.plain_bills_in_range ? `${esc(r.plain_bills_in_range)} plain (non-GST) bill(s) in this period are not included.` : ""}
      ${r.items_missing ? `<b>${esc(r.items_missing)} GST bill(s) have no item details (archived); rate and HSN tables do not include them.</b>` : ""}</p>

    <h2>${r.period === "day" ? "Daily" : "Monthly"} sales</h2>
    ${gst(r.by_period, [["Period", "period"], ["Bills", "count"], ["Taxable", "taxable"], ["CGST", "cgst"], ["SGST", "sgst"], ["IGST", "igst"], ["Value", "total"]])}

    ${composition ? "" : `<h2>GST by rate (invoices)</h2>
    ${gst(r.by_rate, [["Rate %", "rate"], ["Taxable", "taxable"], ["CGST", "cgst"], ["SGST", "sgst"], ["IGST", "igst"], ["Total tax", "tax"], ["Value", "value"]])}`}

    <h2>HSN-wise summary</h2>
    ${gst(r.by_hsn, [["HSN", "hsn"], ["Rate %", "rate"], ["Unit", "unit"], ["Qty", "quantity"], ["Taxable", "taxable"], ["CGST", "cgst"], ["SGST", "sgst"], ["IGST", "igst"], ["Value", "value"]], 3)}

    <h2>Credit notes by rate</h2>
    ${gst(r.credit_notes_by_rate, [["Rate %", "rate"], ["Taxable", "taxable"], ["CGST", "cgst"], ["SGST", "sgst"], ["IGST", "igst"], ["Value", "value"]])}

    <h2>Credit notes</h2>
    ${gst(r.credit_note_list, [["Number", "number"], ["Date", "date"], ["Against", "against"], ["Taxable", "taxable"], ["CGST", "cgst"], ["SGST", "sgst"], ["Value", "total"]], 3)}
    ${truncated(r.credit_notes.count)}

    <h2>Invoices to registered businesses (B2B)</h2>
    ${gst(r.b2b_invoices, [["Invoice", "invoice"], ["Date", "date"], ["Buyer GSTIN", "customer_gstin"], ["Buyer", "customer_name"], ["Taxable", "taxable"], ["CGST", "cgst"], ["SGST", "sgst"], ["Value", "total"]], 4)}
    ${truncated(r.b2b_count)}

    <h2>Purchases (input tax as recorded)</h2>
    <p>${esc(r.purchases.count)} purchase(s), ${esc(r.purchases.with_supplier_gstin)} with supplier GSTIN ·
      value ${esc(r.purchases.value)} · GST ${esc(r.purchases.gst)}</p>
    ${gst(r.purchases.by_rate, [["Rate %", "rate"], ["Value", "value"], ["GST", "gst"]])}
    ${gst(r.purchases.by_supplier, [["Supplier", "supplier"], ["GSTIN", "supplier_gstin"], ["Bills", "bills"], ["Value", "value"], ["GST", "gst"]], 2)}
    <p class="muted">${esc(r.purchases.note)}</p>
    <p class="muted">${esc(r.delivery_fee_note)}</p>
    <p><b>${esc(r.disclaimer)}</b></p>`;

  // A one-cell outer table whose <thead> holds the header: print engines repeat it on every page.
  return `<!doctype html><html><head><meta charset="utf-8"/>
<style>
  body { font-family: -apple-system, Roboto, Arial, sans-serif; color: #111827; font-size: 10px; margin: 20px; }
  h1 { font-size: 15px; margin: 0; color: #0f766e; }
  h2 { font-size: 12px; margin: 14px 0 4px; border-bottom: 1px solid #d1d5db; padding-bottom: 2px; }
  .muted { color: #6b7280; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 4px; }
  th, td { padding: 3px 4px; border-bottom: 1px solid #eef0f2; text-align: left; }
  th { background: #f6f7f8; font-weight: 600; }
  .r { text-align: right; } .total td { font-weight: 700; }
  tr { page-break-inside: avoid; }
  table.page > thead { display: table-header-group; }
  table.page > thead td { border-bottom: 2px solid #0f766e; padding-bottom: 6px; }
</style></head><body>
<table class="page"><thead><tr><td>
  <h1>${esc(r.shop.legal_name)} · GST report</h1>
  <div>GSTIN ${esc(r.shop.gstin)} · ${esc(composition ? "Composition scheme" : "Regular scheme")}</div>
  <div class="muted">Period ${esc(r.from)} to ${esc(r.to)} · Generated ${esc(new Date(r.generated_at).toLocaleString("en-IN"))}</div>
</td></tr></thead><tbody><tr><td>${body}</td></tr></tbody></table>
</body></html>`;
}

const esc = (v: unknown) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
const rs = (v: unknown) => `₹${esc(v)}`;

const table = (headers: string[], rows: (string | number)[][], rightFrom = 1) =>
  rows.length === 0
    ? `<p class="muted">Nothing in this period.</p>`
    : `<table><thead><tr>${headers.map((h, i) => `<th class="${i >= rightFrom ? "r" : ""}">${esc(h)}</th>`).join("")}</tr></thead>
       <tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td class="${i >= rightFrom ? "r" : ""}">${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;

/** exTax: true = sales shown without GST (taxable value). Profit is always without GST either way. */
export function buildReportHtml(o: { from: string; to: string; pl: any; sa: any; ag: any; shopName?: string; exTax?: boolean }) {
  const ex = !!o.exTax;
  const sales = (r: any) => rs(ex ? r.sales_ex_tax ?? r.sales : r.sales);
  const salesHead = ex ? "Sales (excl. GST)" : "Sales (incl. GST)";
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
  ${o.exTax !== undefined ? `<div class="muted">Sales amounts are shown ${ex ? "without GST (taxable value)" : "including GST (what customers paid)"}. Profit is always worked out without GST.</div>` : ""}

  <h2>Profit &amp; loss</h2>
  <table>
    ${ex
      ? `<tr><td>Sales after returns (excl. GST)</td><td class="r">${rs(pl.sales_excluding_tax)}</td></tr>
         <tr><td class="muted">GST collected on these sales (not income)</td><td class="r muted">${rs(pl.tax_included_in_sales)}</td></tr>`
      : `<tr><td>Sales after returns (incl. GST)</td><td class="r">${rs(pl.net_sales)}</td></tr>
         <tr><td>Tax included in sales</td><td class="r">${rs(pl.tax_included_in_sales)}</td></tr>`}
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
  ${table(["Category", salesHead, "Profit"], sa.by_category.map((c: any) => [esc(c.category), sales(c), rs(c.profit)]))}

  <h2>Sales by product</h2>
  ${table(["Product", "Category", "Qty", salesHead, "Profit"],
    sa.all_products.map((p: any) => [esc(p.product), esc(p.category), esc(p.quantity), sales(p), rs(p.profit)]), 2)}

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
