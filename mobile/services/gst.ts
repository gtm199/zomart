/**
 * GST helpers for the phone. The server (services/gst_service.py) is the source of truth; this file mirrors its
 * line maths so offline bills show the same total the server will record. Whole paise only (integers), no floats
 * in money maths. Rounding: half up to the paisa, exactly like the server.
 */
import { kvGet, kvSet } from "./localdb";

export type GstScheme = "regular" | "composition";
export type GstConfig = { enabled: boolean; scheme?: GstScheme; state_code?: string };

export const FORMAT_ONLY_NOTE =
  "This only checks that the GSTIN is written correctly. It cannot tell whether it is registered or active - check it on the GST portal.";
export const GST_DISCLAIMER =
  "The app makes invoices and summaries from the rates and details you enter. Please confirm product rates, invoice wording and your scheme with your CA.";

// ---------- shop GST settings saved on the phone (for offline billing) ----------
export async function getGstConfig(): Promise<GstConfig> {
  const raw = await kvGet("gst_config");
  try { return raw ? JSON.parse(raw) : { enabled: false }; } catch { return { enabled: false }; }
}
export const saveGstConfig = (c: GstConfig) => kvSet("gst_config", JSON.stringify(c));

/** Products need a confirmed rate only on regular-scheme GST shops (composition shops charge no tax). */
export const needsRate = (c: GstConfig) => c.enabled && c.scheme !== "composition";

// ---------- money maths (mirror of gst_service.compute_line, intra-state) ----------
/** round(num / den) half up, for num >= 0 and den > 0 */
const rhu = (num: number, den: number) => Math.floor((2 * num + den) / (2 * den));
const basisPoints = (rate: string) => Math.round(Number(rate) * 100); // "18.00" -> 1800

export type GstLine = { totalC: number; taxableC: number; cgstC: number; sgstC: number };

export function gstLine(grossC: number, rate: string | null, includesGst: boolean, c: GstConfig): GstLine {
  if (!c.enabled || c.scheme === "composition" || rate === null || rate === undefined) {
    return { totalC: grossC, taxableC: grossC, cgstC: 0, sgstC: 0 };
  }
  const bp = basisPoints(rate);
  if (includesGst) {
    const tax = grossC - rhu(grossC * 10000, 10000 + bp);
    const half = rhu(tax, 2);
    return { totalC: grossC, taxableC: grossC - 2 * half, cgstC: half, sgstC: half };
  }
  const half = rhu(grossC * bp, 20000);
  return { totalC: grossC + 2 * half, taxableC: grossC, cgstC: half, sgstC: half };
}

// ---------- GSTIN format check (mirror of services/gstin.py) ----------
const CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

export const normalizeGstin = (s: string) => (s || "").trim().toUpperCase().replace(/\s/g, "");

function checkChar(first14: string) {
  let total = 0;
  for (let i = 0; i < 14; i++) {
    const p = CHARS.indexOf(first14[i]) * (i % 2 ? 2 : 1);
    total += Math.floor(p / 36) + (p % 36);
  }
  return CHARS[(36 - (total % 36)) % 36];
}

/** Returns an error message, or "" when the format is right. Format only - not a registration check. */
export function gstinError(raw: string, stateCode?: string): string {
  const g = normalizeGstin(raw);
  if (g.length !== 15) return "GSTIN must be exactly 15 characters.";
  if (!PATTERN.test(g)) return "GSTIN format is wrong. Expected: state code, PAN, entity number, Z, check character.";
  const st = Number(g.slice(0, 2));
  if (!((st >= 1 && st <= 38) || st === 97 || st === 99)) return `GSTIN starts with ${g.slice(0, 2)}, which is not a valid state code.`;
  if (stateCode && g.slice(0, 2) !== stateCode) return `GSTIN starts with ${g.slice(0, 2)} but the shop's state code is ${stateCode}.`;
  if (checkChar(g.slice(0, 14)) !== g[14]) return "GSTIN check character does not match. Please re-check each character.";
  return "";
}

export const hsnError = (raw: string) =>
  raw === "" || /^(\d{4}|\d{6}|\d{8})$/.test(raw) ? "" : "HSN code must be 4, 6 or 8 digits.";

export const STATE_NAMES: Record<string, string> = { "07": "Delhi" };
