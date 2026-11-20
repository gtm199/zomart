import { useCallback, useEffect, useState } from "react";
import { Alert, Text, View } from "react-native";
import { api } from "../services/api";
import { ShopProduct } from "../types";
import { Button, Err, Input, Muted, colors } from "./ui";
import { DateField } from "./DateField";

/** Expiry batches of one product: each lot with its own expiry date and pieces left.
 *  Selling takes stock without a date first, then the batch that expires first (the server decides). */
type Batch = {
  id: number; expiry_date: string; batch_no: string; quantity_received: string; quantity_left: string;
  days_to_expiry: number; status: "expired" | "expiring_soon" | "ok" | "finished"; source: string;
};
type Resp = { product: ShopProduct; undated_qty: string; alert_days: number; batches: Batch[] };

const WARN = "#b45309";
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const qty = (s: string) => String(Number(s));   // "5.000" -> "5"

function statusLine(b: Batch) {
  if (b.status === "expired") return { text: `EXPIRED ${-b.days_to_expiry} day(s) ago`, color: colors.danger };
  if (b.status === "expiring_soon") return { text: b.days_to_expiry === 0 ? "Expires today" : `Expires in ${b.days_to_expiry} day(s)`, color: WARN };
  return { text: `${b.days_to_expiry} day(s) left`, color: colors.muted };
}

export default function BatchPanel({ sp, canManage, onChanged }: { sp: ShopProduct; canManage: boolean; onChanged: (p: ShopProduct) => void }) {
  const [data, setData] = useState<Resp | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [date, setDate] = useState("");
  const [count, setCount] = useState("");
  const [batchNo, setBatchNo] = useState("");
  const unit = sp.master_product.is_loose ? ` ${sp.master_product.unit}` : " pcs";

  const load = useCallback(async () => {
    try { setData(await api<Resp>(`/shop/products/${sp.id}/batches/`)); setErr(""); } catch (e: any) { setErr(e.message); }
  }, [sp.id]);
  useEffect(() => { load(); }, [load, sp.stock_qty]);

  const run = async (path: string, body: object = {}) => {
    setBusy(true); setErr("");
    try {
      const r = await api<Resp>(`/shop/products/${sp.id}/batches/${path}`, { body });
      setData(r); onChanged(r.product); return true;
    } catch (e: any) { setErr(e.message); return false; }
    finally { setBusy(false); }
  };

  const writeOff = (b: Batch) => Alert.alert(
    "Throw away this batch?",
    `${qty(b.quantity_left)}${unit} expiring ${b.expiry_date} will be removed from stock as ${b.status === "expired" ? "expired" : "damaged"}.`,
    [{ text: "Cancel", style: "cancel" },
     { text: "Throw away", style: "destructive", onPress: () => run(`${b.id}/write-off/`, { movement_type: b.status === "expired" ? "expired" : "damage" }) }]);

  const close = (b: Batch) => Alert.alert(
    "Not on the shelf any more?",
    "Use this when these pieces were already sold or counted wrong. Stock stays the same; only the expiry date of this batch is dropped.",
    [{ text: "Cancel", style: "cancel" }, { text: "Yes, close batch", onPress: () => run(`${b.id}/close/`) }]);

  const addDate = async () => {
    if (!DATE.test(date.trim())) { setErr("Pick the expiry date."); return; }
    if (!(Number(count) > 0)) { setErr("Enter how many pieces have this date."); return; }
    if (await run("add/", { expiry_date: date.trim(), quantity: count.trim(), batch_no: batchNo.trim() })) {
      setAdding(false); setDate(""); setCount(""); setBatchNo("");
    }
  };

  if (!data) return <>{err ? <Err msg={err} /> : <Muted>Loading batches…</Muted>}</>;
  const undated = Number(data.undated_qty);

  return (
    <View style={{ marginVertical: 6, padding: 8, borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 8 }}>
      <Text style={{ fontWeight: "700" }}>Expiry batches</Text>
      {data.batches.length === 0 ? <Muted>No batches with an expiry date.</Muted> : null}
      {data.batches.map((b) => {
        const st = statusLine(b);
        return (
          <View key={b.id} style={{ paddingVertical: 6, borderTopWidth: 1, borderTopColor: "#f1f5f9" }}>
            <Text style={{ fontWeight: "600" }}>
              Exp {b.expiry_date} · {qty(b.quantity_left)}{unit} left{b.batch_no ? ` · Batch ${b.batch_no}` : ""}
            </Text>
            <Text style={{ color: st.color, fontWeight: b.status === "ok" ? "400" : "700" }}>{st.text}</Text>
            {canManage ? (
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                <Button title={b.status === "expired" ? "Write off (expired)" : "Throw away (damaged)"} kind={b.status === "expired" ? "danger" : "ghost"}
                  disabled={busy} onPress={() => writeOff(b)} />
                <Button title="Not on shelf" kind="ghost" disabled={busy} onPress={() => close(b)} />
              </View>
            ) : null}
          </View>
        );
      })}
      {undated > 0 ? <Muted>{qty(data.undated_qty)}{unit} in stock have no expiry date. They are sold first.</Muted> : null}
      {canManage && undated > 0 && !adding ? <Button title="Add expiry date for stock in hand" kind="ghost" onPress={() => { setAdding(true); setCount(qty(data.undated_qty)); }} /> : null}
      {adding ? (
        <>
          <View style={{ flexDirection: "row", marginVertical: 4 }}>
            <DateField label="Expiry date" value={date} onChange={setDate} placeholder="Pick the expiry date" />
          </View>
          <Muted>How many pieces have this date (up to {qty(data.undated_qty)})</Muted>
          <Input keyboardType="decimal-pad" value={count} onChangeText={setCount} />
          <Muted>Batch number (optional, as printed on the pack)</Muted>
          <Input value={batchNo} onChangeText={setBatchNo} autoCapitalize="characters" />
          <Button title="Save batch" disabled={busy} onPress={addDate} />
          <Button title="Cancel" kind="ghost" onPress={() => setAdding(false)} />
        </>
      ) : null}
      <Err msg={err} />
    </View>
  );
}
