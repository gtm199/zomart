export const toCents = (s: string) => Math.round(Number(s) * 100);
export const rs = (cents: number) => (cents / 100).toFixed(2);

export function receiptText(shop: string, ref: string, lines: { name: string; qty: number; price: string }[], totalC: number, paidC: number) {
  const out = [`*${shop}*`, `Bill: ${ref}`, new Date().toLocaleString("en-IN"), "------------------------"];
  for (const l of lines) out.push(`${l.name}\n  ${l.qty} x ${l.price} = ${rs(toCents(l.price) * l.qty)}`);
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