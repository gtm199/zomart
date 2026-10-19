export const round3 = (n: number) => Math.round(n * 1000) / 1000;

const FACTOR: Record<string, number> = { kg: 1000, g: 1, l: 1000, ml: 1 };
const FAMILY: Record<string, string> = { kg: "weight", g: "weight", l: "volume", ml: "volume" };

/** Units the cashier may type for a product priced per `productUnit`. */
export function inputUnits(productUnit: string): string[] {
  if (productUnit === "kg") return ["kg", "g"];
  if (productUnit === "g") return ["g", "kg"];
  if (productUnit === "l") return ["l", "ml"];
  if (productUnit === "ml") return ["ml", "l"];
  return [productUnit];
}

/** 250 g -> 0.25 kg. Returns NaN for units that cannot be converted. */
export function toProductUnit(value: number, from: string, productUnit: string) {
  if (from === productUnit) return round3(value);
  if (!FACTOR[from] || FAMILY[from] !== FAMILY[productUnit]) return NaN;
  return round3((value * FACTOR[from]) / FACTOR[productUnit]);
}

/** 0.25 kg -> "250 g", 2 kg -> "2 kg", pieces -> "3". */
export function fmtQty(qty: number, unit = "") {
  const q = round3(qty);
  if (unit === "kg" && q < 1) return `${round3(q * 1000)} g`;
  if (unit === "l" && q < 1) return `${round3(q * 1000)} ml`;
  return unit && unit !== "pc" ? `${q} ${unit}` : `${q}`;
}

/** Quick buttons on the weight form: [label, value, unit]. */
export function quickWeights(productUnit: string): [string, number, string][] {
  if (productUnit === "kg" || productUnit === "g") return [["100 g", 100, "g"], ["250 g", 250, "g"], ["500 g", 500, "g"], ["1 kg", 1, "kg"]];
  if (productUnit === "l" || productUnit === "ml") return [["100 ml", 100, "ml"], ["250 ml", 250, "ml"], ["500 ml", 500, "ml"], ["1 l", 1, "l"]];
  return [];
}