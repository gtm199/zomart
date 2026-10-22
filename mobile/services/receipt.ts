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
export type ReceiptData = { ref: string; whenISO: string; customer?: string; lines: ReceiptLine[]; totalC: number; paidC: number };
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
    <div class="foot">Thank you! Please visit again.<br>Computer generated receipt. Not a tax invoice.</div>
  </body></html>`;
}

function base64ToBytes(b64: string) {
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