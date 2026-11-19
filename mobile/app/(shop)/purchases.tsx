import * as Crypto from "expo-crypto";
import { useCallback, useEffect, useRef, useState } from "react";
import { ScrollView, Text } from "react-native";
import { Button, Card, Err, Input, Muted, Screen } from "../../components/ui";
import { api } from "../../services/api";
import { gstinError, normalizeGstin } from "../../services/gst";
import { Page, ShopProduct } from "../../types";

type Supplier = { id: number; name: string; phone: string; balance: string; gstin?: string };
type Line = { sp: ShopProduct; qty: string; cost: string; expiry: string; batchNo: string; gstRate: string; gstAmount: string };

export default function Purchases() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [newName, setNewName] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [payFor, setPayFor] = useState<number | null>(null);
  const [payAmount, setPayAmount] = useState("");
  const [buyFrom, setBuyFrom] = useState<Supplier | null>(null);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<ShopProduct[]>([]);
  const [lines, setLines] = useState<Line[]>([]);
  const [invoice, setInvoice] = useState("");
  const [paid, setPaid] = useState("");
  const [method, setMethod] = useState<"cash" | "upi">("cash");
  const [msg, setMsg] = useState("");
  const txnId = useRef(Crypto.randomUUID()); // same id on retry => server never records the purchase twice
  const [gstOn, setGstOn] = useState(false);       // GST shops only: supplier GSTIN and GST per line
  const [supGstin, setSupGstin] = useState("");

  const load = useCallback(async () => {
    try { setSuppliers((await api<Page<Supplier>>("/shop/suppliers/?page_size=200")).results); } catch (e: any) { setMsg(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api<{ gst_enabled: boolean }>("/shop/gst/").then((g) => setGstOn(g.gst_enabled)).catch(() => {}); }, []);

  const addSupplier = async () => {
    setMsg("");
    try { await api("/shop/suppliers/", { body: { name: newName, phone: newPhone } }); setNewName(""); setNewPhone(""); load(); }
    catch (e: any) { setMsg(e.message); }
  };
  const paySupplier = async (s: Supplier, m: "cash" | "upi") => {
    setMsg("");
    try { await api(`/shop/suppliers/${s.id}/pay/`, { body: { amount: payAmount, method: m } }); setPayFor(null); setPayAmount(""); load(); }
    catch (e: any) { setMsg(e.message); }
  };
  const doSearch = async (t: string) => {
    setSearch(t);
    if (t.length < 2) return setResults([]);
    try { setResults((await api<Page<ShopProduct>>(`/shop/products/?search=${encodeURIComponent(t)}`)).results); } catch {}
  };
  const addLine = (sp: ShopProduct) => {
    if (!lines.find((l) => l.sp.id === sp.id)) setLines([...lines, { sp, qty: "1", cost: sp.purchase_cost ?? "", expiry: "", batchNo: "", gstRate: "", gstAmount: "" }]);
    setSearch(""); setResults([]);
  };
  const setLine = (id: number, k: "qty" | "cost" | "expiry" | "batchNo" | "gstRate" | "gstAmount", v: string) =>
    setLines(lines.map((l) => (l.sp.id === id ? { ...l, [k]: v } : l)));
  const gstTotal = lines.reduce((a, l) => a + (Number(l.gstAmount) || 0), 0);

  const total = lines.reduce((a, l) => a + (Number(l.qty) || 0) * (Number(l.cost) || 0), 0);

  const save = async () => {
    if (!buyFrom) return;
    setMsg("");
    const paidAmount = paid === "" ? 0 : Number(paid);
    if (gstOn && supGstin.trim()) {
      const bad = gstinError(supGstin);
      if (bad) { setMsg(`Supplier GSTIN: ${bad}`); return; }
    }
    try {
      await api("/shop/purchases/", {
        body: {
          client_txn_id: txnId.current,
          supplier: buyFrom.id,
          invoice_number: invoice,
          items: lines.map((l) => ({
            shop_product: l.sp.id, quantity: l.qty, unit_cost: l.cost, expiry_date: l.expiry || null, batch_no: l.expiry ? (l.batchNo ?? "").trim() : "",
            ...(gstOn && l.gstAmount !== "" ? { gst_amount: l.gstAmount } : {}),
            ...(gstOn && l.gstRate !== "" ? { gst_rate: l.gstRate } : {}),
          })),
          ...(gstOn && supGstin.trim() ? { supplier_gstin: normalizeGstin(supGstin) } : {}),
          payments: paidAmount > 0 ? [{ method, amount: paidAmount.toFixed(2) }] : [],
        },
      });
      txnId.current = Crypto.randomUUID();
      setLines([]); setInvoice(""); setPaid(""); setBuyFrom(null); setSupGstin(""); load();
      setMsg("Stock received and saved.");
    } catch (e: any) { setMsg(e.message); }
  };

  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        {msg ? <Err msg={msg} /> : null}

        {buyFrom ? (
          <Card>
            <Text style={{ fontWeight: "700" }}>Receive stock from {buyFrom.name}</Text>
            <Input placeholder="Supplier's bill number (optional)" value={invoice} onChangeText={setInvoice} />
            {gstOn && (
              <>
                <Input placeholder={buyFrom.gstin ? `Supplier GSTIN (blank = saved ${buyFrom.gstin})` : "Supplier GSTIN (optional)"}
                  autoCapitalize="characters" value={supGstin} onChangeText={setSupGstin} />
                <Muted>For your input-tax totals. Enter the GST shown on the supplier's bill for each line. The app does no input-tax-credit filing.</Muted>
              </>
            )}
            <Input placeholder="Search my product to add" value={search} onChangeText={doSearch} />
            {results.map((sp) => <Button key={sp.id} kind="ghost" title={sp.master_product.display_name} onPress={() => addLine(sp)} />)}
            {lines.map((l) => (
              <Card key={l.sp.id}>
                <Text>{l.sp.master_product.display_name}</Text>
                <Muted>Quantity received</Muted>
                <Input keyboardType="decimal-pad" value={l.qty} onChangeText={(v) => setLine(l.sp.id, "qty", v)} />
                <Muted>Cost per unit (₹)</Muted>
                <Input keyboardType="decimal-pad" value={l.cost} onChangeText={(v) => setLine(l.sp.id, "cost", v)} />
                <Muted>Expiry date (YYYY-MM-DD, optional)</Muted>
                <Input placeholder="2027-03-31" value={l.expiry} onChangeText={(v) => setLine(l.sp.id, "expiry", v)} />
                {l.expiry ? (<><Muted>Batch number (optional, as printed on the pack)</Muted><Input value={l.batchNo} autoCapitalize="characters" onChangeText={(v) => setLine(l.sp.id, "batchNo", v)} /></>) : null}
                {gstOn && (
                  <>
                    <Muted>GST on the supplier's bill for this line: rate % and amount ₹ (optional)</Muted>
                    <Input placeholder="Rate %, e.g. 5" keyboardType="decimal-pad" value={l.gstRate} onChangeText={(v) => setLine(l.sp.id, "gstRate", v)} />
                    <Input placeholder="GST amount ₹ (part of the line total)" keyboardType="decimal-pad" value={l.gstAmount} onChangeText={(v) => setLine(l.sp.id, "gstAmount", v)} />
                  </>
                )}
              </Card>
            ))}
            <Text style={{ fontSize: 18, fontWeight: "700" }}>Total ₹{total.toFixed(2)}</Text>
            {gstOn && gstTotal > 0 && <Muted>of which GST (as on the supplier's bill) ₹{gstTotal.toFixed(2)}</Muted>}
            <Input placeholder="Amount paid now (blank = pay later)" keyboardType="decimal-pad" value={paid} onChangeText={setPaid} />
            <Button title="Paid in Cash" kind={method === "cash" ? "primary" : "ghost"} onPress={() => setMethod("cash")} />
            <Button title="Paid by UPI" kind={method === "upi" ? "primary" : "ghost"} onPress={() => setMethod("upi")} />
            <Button title="Save purchase" onPress={save} disabled={lines.length === 0 || lines.some((l) => !l.qty || l.cost === "")} />
            <Button title="Cancel" kind="ghost" onPress={() => { setBuyFrom(null); setLines([]); }} />
          </Card>
        ) : (
          <>
            <Card>
              <Text style={{ fontWeight: "700" }}>New supplier</Text>
              <Input placeholder="Supplier name" value={newName} onChangeText={setNewName} />
              <Input placeholder="Mobile (optional)" keyboardType="phone-pad" value={newPhone} onChangeText={setNewPhone} />
              <Button title="Add supplier" onPress={addSupplier} disabled={!newName} />
            </Card>
            {suppliers.map((s) => (
              <Card key={s.id}>
                <Text style={{ fontWeight: "600" }}>{s.name}</Text>
                <Muted>{s.phone || "no phone"} · You owe ₹{s.balance}</Muted>
                <Button title="Receive stock" onPress={() => setBuyFrom(s)} />
                {Number(s.balance) > 0 && (payFor === s.id ? (
                  <>
                    <Input placeholder="Amount paid" keyboardType="decimal-pad" value={payAmount} onChangeText={setPayAmount} />
                    <Button title="Paid in cash" onPress={() => paySupplier(s, "cash")} disabled={!payAmount} />
                    <Button title="Paid by UPI" kind="ghost" onPress={() => paySupplier(s, "upi")} disabled={!payAmount} />
                  </>
                ) : <Button title="Pay supplier" kind="ghost" onPress={() => setPayFor(s.id)} />)}
              </Card>
            ))}
          </>
        )}
      </ScrollView>
    </Screen>
  );
}