import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import { File, Paths } from "expo-file-system";
import { api } from "./api";
import { kvGet, kvSet } from "./localdb";
import { fmtQty } from "./units";

export const toCents = (s: string) => Math.round(Number(s) * 100);
export const rs = (cents: number) => (cents / 100).toFixed(2);

/** price per unit x quantity, rounded to the paisa the same way the server does (half up). */
export function lineCents(price: string, qty: number) {
  const milli = Math.round(qty * 1000);
  return Math.floor((toCents(price) * milli + 500) / 1000);
}

export type ReceiptLine = { name: string; qty: number; unit?: string; price: string; totalC?: number };
export type ReceiptData = {
  ref: string; whenISO: string; customer?: string; lines: ReceiptLine[]; totalC: number; paidC: number;
  note?: string; // extra footer line, e.g. "tax invoice available after upload"
};
export type ShopInfo = { name: string; address: string; phone: string; gstin: string };

const lineTotal = (l: ReceiptLine) => l.totalC ?? lineCents(l.price, l.qty);

// ---------- WhatsApp text ----------
export function receiptText(shop: string, ref: string, lines: ReceiptLine[], totalC: number, paidC: number) {
  const out = [`*${shop}*`, `Bill: ${ref}`, new Date().toLocaleString("en-IN"), "------------------------"];
  for (const l of lines) out.push(`${l.name}\n  ${fmtQty(l.qty, l.unit ?? "")} x ${l.price} = ${rs(lineTotal(l))}`);
  out.push("------------------------", `*Total: Rs ${rs(totalC)}*`, `Paid: Rs ${rs(paidC)}`);
  if (paidC < totalC) out.push(`Due (credit): Rs ${rs(totalC - paidC)}`);
  out.push("Thank you! Please visit again.");
  return out.join("\n");
}

/** Opens a chat with this number, even if it is not in your contacts. */
export function waLink(raw: string, text: string) {
  let d = (raw || "").replace(/\D/g, "");
  if (d.length === 11 && d.startsWith("0")) d = d.slice(1);
  if (d.length === 10) d = "91" + d;
  return `https://wa.me/${d}?text=${encodeURIComponent(text)}`;
}

/** The message for a customer who owes money. You read it, then tap send yourself. */
export function reminderText(shop: string, customer: string, owedC: number) {
  return `Namaste ${customer}, this is a gentle reminder from ${shop}: your balance with us is Rs ${rs(owedC)}. Please pay when you can. Thank you!`;
}

// ---------- shop details for the PDF header (saved on the phone for offline use) ----------
export async function getShopInfo(fallbackName: string): Promise<ShopInfo> {
  try {
    const s = await api<any>("/shop/");
    const info: ShopInfo = { name: s.name, address: s.address ?? "", phone: s.phone ?? "", gstin: s.gstin ?? "" };
    await kvSet("shop_info", JSON.stringify(info));
    return info;
  } catch {
    const saved = await kvGet("shop_info");
    return saved ? JSON.parse(saved) : { name: fallbackName, address: "", phone: "", gstin: "" };
  }
}

// ---------- PDF ----------
const esc = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));

export function receiptHtml(shop: ShopInfo, d: ReceiptData) {
  const when = new Date(d.whenISO).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  const rows = d.lines
    .map((l) => `<tr><td>${esc(l.name)}</td><td class="r">${esc(fmtQty(l.qty, l.unit ?? ""))}</td><td class="r">${esc(l.price)}</td><td class="r">${rs(lineTotal(l))}</td></tr>`)
    .join("");
  const due = d.totalC - d.paidC;
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body{font-family:Arial,sans-serif;font-size:13px;color:#111;padding:8px}
    h1{font-size:20px;margin:0 0 2px;text-align:center}
    .c{text-align:center;color:#444}
    table{width:100%;border-collapse:collapse;margin-top:10px}
    th,td{padding:5px 3px;border-bottom:1px solid #ddd;text-align:left}
    .r{text-align:right}
    .tot td{font-weight:bold;font-size:15px;border-top:2px solid #111}
    .foot{margin-top:16px;text-align:center;color:#666;font-size:11px}
  </style></head><body>
    <h1>${esc(shop.name)}</h1>
    ${shop.address ? `<div class="c">${esc(shop.address)}</div>` : ""}
    ${shop.phone ? `<div class="c">Phone: ${esc(shop.phone)}</div>` : ""}
    ${shop.gstin ? `<div class="c">GSTIN: ${esc(shop.gstin)}</div>` : ""}
    <p><b>Bill:</b> ${esc(d.ref)} &nbsp; <b>Date:</b> ${esc(when)}${d.customer ? `<br><b>Customer:</b> ${esc(d.customer)}` : ""}</p>
    <table>
      <thead><tr><th>Item</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Amount</th></tr></thead>
      <tbody>${rows}
        <tr class="tot"><td colspan="3">Total</td><td class="r">Rs ${rs(d.totalC)}</td></tr>
        <tr><td colspan="3">Paid</td><td class="r">Rs ${rs(d.paidC)}</td></tr>
        ${due > 0 ? `<tr><td colspan="3"><b>Due (credit)</b></td><td class="r"><b>Rs ${rs(due)}</b></td></tr>` : ""}
      </tbody>
    </table>
    <div class="foot">Thank you! Please visit again.<br>Computer generated receipt. Not a tax invoice.${d.note ? `<br>${esc(d.note)}` : ""}</div>
  </body></html>`;
}

// ---------- GST tax invoice / bill of supply / credit note (built only from the server's saved copy) ----------
export type GstItem = {
  id: number; product_name: string; quantity: string; unit: string; unit_price: string; discount: string;
  tax_rate: string; line_total: string; hsn_code?: string; taxable_value?: string; cgst?: string; sgst?: string; igst?: string;
};
export type GstRateRow = { rate: string; taxable_value: string; cgst: string; sgst: string; igst: string; tax: string };
export type CreditNote = {
  id: number; number: string; original_invoice_number: string; created_at: string; total: string; taxable_total: string;
  cgst_total: string; sgst_total: string; igst_total: string; seller_gstin: string; seller_legal_name: string;
  items: { product_name: string; hsn_code: string; quantity: string; gst_rate: string; taxable_value: string;
           cgst: string; sgst: string; igst: string; line_total: string }[];
};
export type GstSale = {
  invoice_number: string; created_at: string; document_type: "bill" | "tax_invoice" | "bill_of_supply";
  total: string; amount_paid: string; amount_due: string; discount_total: string; customer_name?: string;
  seller_gstin?: string; seller_legal_name?: string; seller_trade_name?: string; seller_address?: string;
  place_of_supply?: string; customer_gstin?: string; customer_gst_name?: string;
  taxable_total?: string; cgst_total?: string; sgst_total?: string; igst_total?: string; round_off?: string;
  gst_summary?: GstRateRow[]; amount_in_words?: string; bill_of_supply_note?: string; credit_notes?: CreditNote[];
  items: GstItem[];
};

const GST_STYLE = `
  body{font-family:Arial,sans-serif;font-size:11px;color:#111;padding:6px}
  h1{font-size:17px;margin:0;text-align:center} h2{font-size:14px;margin:8px 0 4px;text-align:center;letter-spacing:1px}
  .c{text-align:center;color:#333} .r{text-align:right}
  table{width:100%;border-collapse:collapse;margin-top:6px}
  th,td{padding:3px 2px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}
  th{background:#f1f5f9} .tot td{font-weight:bold;font-size:13px;border-top:2px solid #111}
  .foot{margin-top:12px;text-align:center;color:#555;font-size:10px}`;

const fmtWhen = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

function sellerHeader(s: { seller_legal_name?: string; seller_trade_name?: string; seller_address?: string; seller_gstin?: string }) {
  return `<h1>${esc(s.seller_legal_name ?? "")}</h1>
    ${s.seller_trade_name ? `<div class="c">${esc(s.seller_trade_name)}</div>` : ""}
    ${s.seller_address ? `<div class="c">${esc(s.seller_address)}</div>` : ""}
    <div class="c"><b>GSTIN: ${esc(s.seller_gstin ?? "")}</b></div>`;
}

export function gstInvoiceHtml(s: GstSale) {
  const bos = s.document_type === "bill_of_supply";
  const anyIgst = (s.gst_summary ?? []).some((r) => Number(r.igst) > 0);
  const rows = s.items.map((i) => bos
    ? `<tr><td>${esc(i.product_name)}</td><td class="r">${esc(fmtQty(Number(i.quantity), i.unit))}</td><td class="r">${esc(i.unit_price)}</td><td class="r">${esc(i.line_total)}</td></tr>`
    : `<tr><td>${esc(i.product_name)}</td><td>${esc(i.hsn_code || "-")}</td><td class="r">${esc(fmtQty(Number(i.quantity), i.unit))}</td>
         <td class="r">${esc(i.unit_price)}</td><td class="r">${esc(i.taxable_value ?? "")}</td><td class="r">${esc(i.tax_rate)}%</td>
         <td class="r">${esc(i.line_total)}</td></tr>`).join("");
  const head = bos
    ? `<tr><th>Item</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Amount</th></tr>`
    : `<tr><th>Item</th><th>HSN</th><th class="r">Qty</th><th class="r">Price</th><th class="r">Taxable</th><th class="r">GST</th><th class="r">Amount</th></tr>`;
  const cols = bos ? 3 : 6;
  const summary = bos ? "" : `<table><thead><tr><th>GST rate</th><th class="r">Taxable</th>
      ${anyIgst ? `<th class="r">IGST</th>` : `<th class="r">CGST</th><th class="r">SGST</th>`}<th class="r">Total tax</th></tr></thead><tbody>
      ${(s.gst_summary ?? []).map((r) => `<tr><td>${esc(r.rate)}%</td><td class="r">${esc(r.taxable_value)}</td>
        ${anyIgst ? `<td class="r">${esc(r.igst)}</td>` : `<td class="r">${esc(r.cgst)}</td><td class="r">${esc(r.sgst)}</td>`}
        <td class="r">${esc(r.tax)}</td></tr>`).join("")}</tbody></table>`;
  const due = toCents(s.amount_due);
  return `<!doctype html><html><head><meta charset="utf-8"><style>${GST_STYLE}</style></head><body>
    ${sellerHeader(s)}
    <h2>${bos ? "BILL OF SUPPLY" : "TAX INVOICE"}</h2>
    <p><b>No:</b> ${esc(s.invoice_number)} &nbsp; <b>Date:</b> ${esc(fmtWhen(s.created_at))}
      ${bos ? "" : `<br><b>Place of supply:</b> ${esc(s.place_of_supply ?? "")}`}
      ${s.customer_gstin ? `<br><b>Buyer:</b> ${esc(s.customer_gst_name || "-")} &nbsp; <b>GSTIN:</b> ${esc(s.customer_gstin)}`
        : s.customer_name ? `<br><b>Customer:</b> ${esc(s.customer_name)}` : ""}</p>
    <table><thead>${head}</thead><tbody>${rows}
      ${Number(s.discount_total) > 0 ? `<tr><td colspan="${cols}">Discount given (included above)</td><td class="r">${esc(s.discount_total)}</td></tr>` : ""}
      ${bos ? "" : `<tr><td colspan="${cols}">Taxable value</td><td class="r">${esc(s.taxable_total ?? "")}</td></tr>
        ${anyIgst ? `<tr><td colspan="${cols}">IGST</td><td class="r">${esc(s.igst_total ?? "")}</td></tr>`
          : `<tr><td colspan="${cols}">CGST</td><td class="r">${esc(s.cgst_total ?? "")}</td></tr>
             <tr><td colspan="${cols}">SGST</td><td class="r">${esc(s.sgst_total ?? "")}</td></tr>`}`}
      ${Number(s.round_off ?? 0) !== 0 ? `<tr><td colspan="${cols}">Round off</td><td class="r">${esc(s.round_off ?? "")}</td></tr>` : ""}
      <tr class="tot"><td colspan="${cols}">Total</td><td class="r">Rs ${esc(s.total)}</td></tr>
      <tr><td colspan="${cols}">Paid</td><td class="r">Rs ${esc(s.amount_paid)}</td></tr>
      ${due > 0 ? `<tr><td colspan="${cols}"><b>Due (credit)</b></td><td class="r"><b>Rs ${esc(s.amount_due)}</b></td></tr>` : ""}
    </tbody></table>
    <p><b>${esc(s.amount_in_words ?? "")}</b></p>
    ${summary}
    ${bos && s.bill_of_supply_note ? `<p><b>${esc(s.bill_of_supply_note)}</b></p>` : ""}
    ${(s.credit_notes ?? []).length ? `<p>Credit notes issued: ${(s.credit_notes ?? []).map((n) => `${esc(n.number)} (Rs ${esc(n.total)})`).join(", ")}</p>` : ""}
    <div class="foot">Thank you! Please visit again.<br>Computer generated ${bos ? "bill of supply" : "invoice"}.</div>
  </body></html>`;
}

export function creditNoteHtml(sale: GstSale, n: CreditNote) {
  const rows = n.items.map((i) => `<tr><td>${esc(i.product_name)}</td><td>${esc(i.hsn_code || "-")}</td>
      <td class="r">${esc(fmtQty(Number(i.quantity), ""))}</td><td class="r">${esc(i.taxable_value)}</td><td class="r">${esc(i.gst_rate)}%</td>
      <td class="r">${esc((Number(i.cgst) + Number(i.sgst) + Number(i.igst)).toFixed(2))}</td><td class="r">${esc(i.line_total)}</td></tr>`).join("");
  const igst = Number(n.igst_total) > 0;
  return `<!doctype html><html><head><meta charset="utf-8"><style>${GST_STYLE}</style></head><body>
    ${sellerHeader(sale)}
    <h2>CREDIT NOTE</h2>
    <p><b>No:</b> ${esc(n.number)} &nbsp; <b>Date:</b> ${esc(fmtWhen(n.created_at))}<br>
      <b>Against invoice:</b> ${esc(n.original_invoice_number)} dated ${esc(fmtWhen(sale.created_at))}
      ${sale.customer_gstin ? `<br><b>Buyer GSTIN:</b> ${esc(sale.customer_gstin)}` : ""}</p>
    <table><thead><tr><th>Item returned</th><th>HSN</th><th class="r">Qty</th><th class="r">Taxable</th><th class="r">GST</th><th class="r">Tax</th><th class="r">Amount</th></tr></thead>
      <tbody>${rows}
        <tr><td colspan="6">Taxable value</td><td class="r">${esc(n.taxable_total)}</td></tr>
        ${igst ? `<tr><td colspan="6">IGST reversed</td><td class="r">${esc(n.igst_total)}</td></tr>`
          : `<tr><td colspan="6">CGST reversed</td><td class="r">${esc(n.cgst_total)}</td></tr>
             <tr><td colspan="6">SGST reversed</td><td class="r">${esc(n.sgst_total)}</td></tr>`}
        <tr class="tot"><td colspan="6">Credit note total</td><td class="r">Rs ${esc(n.total)}</td></tr>
      </tbody></table>
    <div class="foot">Computer generated credit note.</div>
  </body></html>`;
}

export function base64ToBytes(b64: string) {
  const bin: string = (globalThis as any).atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

/** Makes a PDF, saves it as a file the app owns under a proper name, and opens the share sheet. */
export async function shareReceiptPdf(html: string, name = "Bill") {
  let shareUri = "";
  try {
    // base64: true also gives us the PDF's content, so we can write our own copy where the app may read it
    const { uri, base64 } = await Print.printToFileAsync({ html, width: 420, height: 595, base64: true });
    shareUri = uri;
    if (base64) {
      const safe = name.replace(/[^A-Za-z0-9_-]/g, "_");
      const file = new File(Paths.cache, `${safe}.pdf`);
      if (file.exists) await file.delete();
      await file.create();
      await file.write(base64ToBytes(base64));
      shareUri = file.uri;
    }
  } catch {
    // keep whatever file we have and try that
  }
  try {
    if (shareUri && (await Sharing.isAvailableAsync())) {
      await Sharing.shareAsync(shareUri, { mimeType: "application/pdf", dialogTitle: "Share receipt", UTI: "com.adobe.pdf" });
      return shareUri;
    }
  } catch {
    // sharing refused the file: fall through to the print window
  }
  // last resort: the phone's own print window, which has "Save as PDF" and can be shared from Files
  await Print.printAsync({ html });
  return shareUri;
}

/** Opens the phone's print window (a normal printer or "Save as PDF"). */
export const printReceipt = (html: string) => Print.printAsync({ html });