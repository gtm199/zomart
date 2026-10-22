import { CameraView, useCameraPermissions } from "expo-camera";
import * as Crypto from "expo-crypto";
import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { Alert, Linking, ScrollView, Text, View } from "react-native";
import SyncBanner from "../../components/SyncBanner";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import {
  HeldCart, LocalCustomer, LocalProduct, deleteHeld, findByBarcode, getCustomer, getProduct, holdCart, listHeld,
  queueSale, searchCustomers, searchProducts,
} from "../../services/localdb";
import { getShopInfo, lineCents, receiptHtml, receiptText, rs, shareReceiptPdf, toCents, waLink } from "../../services/receipt";
import { notifySync, runSync } from "../../services/sync";
import { fmtQty, inputUnits, quickWeights, round3, toProductUnit } from "../../services/units";
import { useSession } from "../../store/session";
import { Master } from "../../types";

type Line = { p: LocalProduct; qty: number };

const isLoose = (p: LocalProduct) => p.loose === 1;
const unitOf = (p: LocalProduct) => (isLoose(p) ? p.unit : "");

const askOverLimit = (message: string, canOverride: boolean) =>
  new Promise<boolean>((resolve) => {
    Alert.alert(
      "Over credit limit",
      message + (canOverride ? "" : "\n\nAsk the owner or a manager to allow this."),
      canOverride
        ? [{ text: "Cancel", style: "cancel", onPress: () => resolve(false) }, { text: "Allow this time", onPress: () => resolve(true) }]
        : [{ text: "OK", onPress: () => resolve(false) }],
      { cancelable: false }
    );
  });

export default function Pos() {
  const { shop } = useSession();
  const [perm, requestPerm] = useCameraPermissions();
  const [scanning, setScanning] = useState(false);
  const [cart, setCart] = useState<Line[]>([]);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<LocalProduct[]>([]);
  const [unlisted, setUnlisted] = useState<Master | null>(null);
  const [newPrice, setNewPrice] = useState("");
  const [newStock, setNewStock] = useState("");
  const [paid, setPaid] = useState("");
  const [method, setMethod] = useState<"cash" | "upi">("cash");
  const [custQuery, setCustQuery] = useState("");
  const [custs, setCusts] = useState<LocalCustomer[]>([]);
  const [customer, setCustomer] = useState<LocalCustomer | null>(null);
  const [waPhone, setWaPhone] = useState("");
  const [err, setErr] = useState("");
  const [held, setHeld] = useState<HeldCart[]>([]);
  // weight entry for loose items
  const [weighing, setWeighing] = useState<{ p: LocalProduct; editing: boolean } | null>(null);
  const [wMode, setWMode] = useState<"weight" | "amount">("weight");
  const [wUnit, setWUnit] = useState("kg");
  const [wValue, setWValue] = useState("");
  const lastScan = useRef(0);
  const txnId = useRef(Crypto.randomUUID()); // saved with the bill: the server never bills the same one twice

  const trusted = shop?.role === "owner" || shop?.role === "manager";
  const totalC = cart.reduce((a, l) => a + lineCents(l.p.selling_price, l.qty), 0);
  const available = (p: LocalProduct) => Number(p.stock_qty) - p.pending_qty;

  useFocusEffect(useCallback(() => { listHeld().then(setHeld); }, []));

  // ---------- adding things to the bill ----------
  const pick = (p: LocalProduct) => {
    if (!p.is_enabled) { Alert.alert("Not available", `${p.name} is switched off.`); return; }
    if (isLoose(p)) {
      setWeighing({ p, editing: false }); setWMode("weight"); setWUnit(p.unit); setWValue(""); setErr("");
      return;
    }
    setCart((c) => (c.find((l) => l.p.id === p.id) ? c.map((l) => (l.p.id === p.id ? { ...l, qty: l.qty + 1 } : l)) : [...c, { p, qty: 1 }]));
  };
  const changeQty = (id: number, d: number) =>
    setCart((c) => c.map((l) => (l.p.id === id ? { ...l, qty: Math.max(0, l.qty + d) } : l)).filter((l) => l.qty > 0));
  const editWeight = (l: Line) => {
    setWeighing({ p: l.p, editing: true }); setWMode("weight"); setWUnit(l.p.unit); setWValue(String(l.qty));
  };

  const weighQty = () => {
    if (!weighing) return 0;
    const v = Number(wValue.replace(",", "."));
    if (!(v > 0)) return 0;
    if (wMode === "amount") {
      const price = Number(weighing.p.selling_price);
      return price > 0 ? round3(v / price) : 0;
    }
    const q = toProductUnit(v, wUnit, weighing.p.unit);
    return Number.isFinite(q) ? q : 0;
  };
  const confirmWeight = () => {
    const q = weighQty();
    if (!weighing || !(q > 0)) { setErr("Enter a weight or an amount."); return; }
    const p = weighing.p;
    setCart((c) => {
      const exists = c.find((l) => l.p.id === p.id);
      if (exists) return c.map((l) => (l.p.id === p.id ? { ...l, qty: weighing.editing ? q : round3(l.qty + q) } : l));
      return [...c, { p, qty: q }];
    });
    setWeighing(null); setErr("");
  };

  const onScan = async ({ data }: { data: string }) => {
    if (Date.now() - lastScan.current < 1500) return;
    lastScan.current = Date.now();
    setErr("");
    const local = await findByBarcode(data);
    if (local) { pick(local); return; }
    try {
      const r = await api<{ master_product: Master | null; shop_product: { id: number } | null }>(`/shop/products/by-barcode/${encodeURIComponent(data)}/`);
      if (r.shop_product) {
        await runSync(); // a product added on another phone: download it
        const again = await getProduct(r.shop_product.id);
        if (again) pick(again);
      } else if (r.master_product) { setUnlisted(r.master_product); setScanning(false); }
    } catch (e: any) {
      if (e.status === 0) Alert.alert("Not in your offline list", "This product is not saved on the phone. Connect to the internet once to download your products.");
      else if (e.status === 404) Alert.alert("Unknown barcode", "Not in the catalogue. Search by name, or ask the admin to add it.");
      else setErr(e.message);
    }
  };

  const doSearch = async (t: string) => {
    setSearch(t);
    if (t.length < 2) return setResults([]);
    setResults(await searchProducts(t));
  };
  const doSearchCustomers = async (t: string) => {
    setCustQuery(t);
    if (t.length < 2) return setCusts([]);
    setCusts(await searchCustomers(t));
  };

  // Adding a catalogue product to the shop needs internet.
  const addUnlisted = async () => {
    if (!unlisted) return;
    try {
      const sp = await api<{ id: number }>("/shop/products/", { body: { master_product: unlisted.id, selling_price: newPrice, opening_stock: newStock || "0" } });
      await runSync();
      const lp = await getProduct(sp.id);
      if (lp) pick(lp);
      setUnlisted(null); setNewPrice(""); setNewStock("");
    } catch (e: any) { setErr(e.status === 0 ? "Adding a new product needs internet." : e.message); }
  };

  // ---------- hold and resume ----------
  const clearBill = () => { setCart([]); setPaid(""); setCustomer(null); setCustQuery(""); setCusts([]); setWaPhone(""); setErr(""); };
  const holdCurrent = async () => {
    if (cart.length === 0) return;
    const time = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
    const label = customer ? `${customer.name} (${time})` : `Held ${time}`;
    await holdCart(label, { lines: cart.map((l) => ({ id: l.p.id, qty: l.qty })), customerId: customer?.id ?? null, waPhone });
    clearBill();
    setHeld(await listHeld());
  };
  const resume = async (h: HeldCart) => {
    if (cart.length > 0) await holdCurrent(); // park whatever is on the counter first
    const data = JSON.parse(h.payload);
    const lines: Line[] = [];
    for (const l of data.lines) {
      const p = await getProduct(l.id); // today's price and stock
      if (p) lines.push({ p, qty: l.qty });
    }
    setCart(lines);
    setCustomer(data.customerId ? await getCustomer(data.customerId) : null);
    setWaPhone(data.waPhone ?? "");
    await deleteHeld(h.id);
    setHeld(await listHeld());
  };
  const dropHeld = (h: HeldCart) =>
    Alert.alert("Delete held bill?", h.name, [
      { text: "No", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => { await deleteHeld(h.id); setHeld(await listHeld()); } },
    ]);

  // ---------- checkout ----------
  const checkout = async () => {
    setErr("");
    const paidC = paid === "" ? totalC : Math.round(Number(paid) * 100);
    if (!(paidC >= 0)) { setErr("Enter a valid amount received."); return; }
    if (paidC > totalC) { setErr("Amount received cannot be more than the bill total."); return; }
    const dueC = totalC - paidC;
    if (dueC > 0 && !customer) { setErr("Select a customer to sell on credit."); return; }

    if (dueC > 0 && customer && customer.credit_limit) {
      const limitC = toCents(customer.credit_limit);
      const owedC = toCents(customer.balance);
      if (owedC + dueC > limitC) {
        const ok = await askOverLimit(
          `${customer.name}\nLimit ₹${rs(limitC)}, owes ₹${rs(owedC)}, this bill adds ₹${rs(dueC)} (new total ₹${rs(owedC + dueC)}).`,
          trusted
        );
        if (!ok) return;
      }
    }

    const txn = txnId.current;
    const ref = "OFF-" + txn.slice(0, 6).toUpperCase(); // temporary number; the real one comes after upload
    const lines = cart.map((l) => ({ name: l.p.name, qty: l.qty, unit: unitOf(l.p), price: l.p.selling_price }));
    const text = receiptText(shop?.name ?? "Shop", ref, lines, totalC, paidC);
    const phone = waPhone || customer?.whatsapp_number || customer?.phone || "";
    const pdfData = { ref, whenISO: new Date().toISOString(), customer: customer?.name, lines, totalC, paidC };

    await queueSale(
      txn,
      {
        client_txn_id: txn,
        offline: true,
        client_created_at: new Date().toISOString(),
        customer: customer?.id ?? null,
        items: cart.map((l) => ({ shop_product: l.p.id, quantity: String(round3(l.qty)), unit_price: l.p.selling_price })),
        payments: paidC > 0 ? [{ method, amount: rs(paidC) }] : [],
      },
      JSON.stringify({ ref, lines, total: rs(totalC), paid: rs(paidC), customer: customer?.name ?? "", receipt: text, phone })
    );

    txnId.current = Crypto.randomUUID();
    clearBill();
    notifySync();
    runSync(); // upload right away if there is internet

    Alert.alert(`Bill saved (${ref})`, `Total ₹${rs(totalC)}. It uploads automatically; the final bill number appears after that.`, [
      { text: "Done" },
      { text: "WhatsApp", onPress: () => Linking.openURL(waLink(phone, text)) },
      {
        text: "PDF",
        onPress: async () => {
          const info = await getShopInfo(shop?.name ?? "Shop");
          shareReceiptPdf(receiptHtml(info, pdfData), ref).catch((e) => Alert.alert("Could not make the PDF", String(e?.message ?? e)));
        },
      },
    ]);
  };

  const wq = weighQty();

  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        <SyncBanner />

        {held.length > 0 && (
          <Card>
            <Text style={{ fontWeight: "700" }}>On hold ({held.length})</Text>
            {held.map((h) => (
              <View key={h.id} style={{ marginTop: 6 }}>
                <Text>{h.name} · {JSON.parse(h.payload).lines.length} item(s)</Text>
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <Button title="Resume" onPress={() => resume(h)} />
                  <Button title="Delete" kind="ghost" onPress={() => dropHeld(h)} />
                </View>
              </View>
            ))}
          </Card>
        )}

        {scanning ? (
          <View style={{ height: 220, borderRadius: 10, overflow: "hidden" }}>
            <CameraView style={{ flex: 1 }} onBarcodeScanned={onScan}
              barcodeScannerSettings={{ barcodeTypes: ["ean13", "ean8", "upc_a", "upc_e", "code128"] }} />
          </View>
        ) : null}
        <Button title={scanning ? "Stop scanner" : "Scan barcode"} kind="ghost"
          onPress={async () => { if (!perm?.granted) await requestPerm(); setScanning((s) => !s); }} />
        <Input placeholder="Or search product by name" value={search} onChangeText={doSearch} />
        {results.map((p) => (
          <Card key={p.id}>
            <Text style={{ fontWeight: "600" }}>{p.name}{isLoose(p) ? "  (loose)" : ""}</Text>
            <Muted>₹{p.selling_price}{isLoose(p) ? ` per ${p.unit}` : ""} · stock about {fmtQty(available(p), unitOf(p))}</Muted>
            <Button title={isLoose(p) ? "Weigh / add" : "Add to bill"} onPress={() => { pick(p); setSearch(""); setResults([]); }} />
          </Card>
        ))}

        {weighing && (
          <Card>
            <Text style={{ fontWeight: "700" }}>{weighing.p.name}</Text>
            <Muted>₹{weighing.p.selling_price} per {weighing.p.unit}</Muted>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Button title="By weight" kind={wMode === "weight" ? "primary" : "ghost"} onPress={() => setWMode("weight")} />
              <Button title="By amount ₹" kind={wMode === "amount" ? "primary" : "ghost"} onPress={() => setWMode("amount")} />
            </View>
            {wMode === "weight" && (
              <>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                  {inputUnits(weighing.p.unit).map((u) => <Button key={u} title={u} kind={wUnit === u ? "primary" : "ghost"} onPress={() => setWUnit(u)} />)}
                </View>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                  {quickWeights(weighing.p.unit).map(([label, v, u]) => (
                    <Button key={label} title={label} kind="ghost" onPress={() => { setWUnit(u); setWValue(String(v)); }} />
                  ))}
                </View>
              </>
            )}
            <Input placeholder={wMode === "weight" ? `Weight in ${wUnit}` : "Amount in ₹"} keyboardType="decimal-pad" value={wValue} onChangeText={setWValue} />
            {wq > 0 && <Text style={{ fontWeight: "700" }}>{fmtQty(wq, weighing.p.unit)} = ₹{rs(lineCents(weighing.p.selling_price, wq))}</Text>}
            <Err msg={err} />
            <Button title={weighing.editing ? "Update" : "Add to bill"} onPress={confirmWeight} disabled={!(wq > 0)} />
            <Button title="Cancel" kind="ghost" onPress={() => { setWeighing(null); setErr(""); }} />
          </Card>
        )}

        {unlisted && (
          <Card>
            <Text style={{ fontWeight: "700" }}>{unlisted.display_name}</Text>
            <Muted>Not in your shop yet (needs internet). MRP: {unlisted.mrp ?? "n/a"}</Muted>
            <Input placeholder="Your selling price" keyboardType="decimal-pad" value={newPrice} onChangeText={setNewPrice} />
            <Input placeholder="Stock in hand" keyboardType="decimal-pad" value={newStock} onChangeText={setNewStock} />
            <Button title="Add to my shop & bill" onPress={addUnlisted} disabled={!newPrice} />
            <Button title="Cancel" kind="ghost" onPress={() => setUnlisted(null)} />
          </Card>
        )}

        <Text style={{ fontWeight: "700", marginTop: 10 }}>Bill</Text>
        {cart.length === 0 && <Muted>Scan or search to add items.</Muted>}
        {cart.map((l) => (
          <Card key={l.p.id}>
            <Text>{l.p.name}</Text>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <Muted>
                {isLoose(l.p) ? `₹${l.p.selling_price}/${l.p.unit} × ${fmtQty(l.qty, l.p.unit)}` : `₹${l.p.selling_price} × ${l.qty}`}
                {" = ₹"}{rs(lineCents(l.p.selling_price, l.qty))}
                {available(l.p) < l.qty ? "  (stock low)" : ""}
              </Muted>
              {isLoose(l.p) ? (
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <Button title="Edit" kind="ghost" onPress={() => editWeight(l)} />
                  <Button title="✕" kind="ghost" onPress={() => changeQty(l.p.id, -999999)} />
                </View>
              ) : (
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <Button title="−" kind="ghost" onPress={() => changeQty(l.p.id, -1)} />
                  <Button title="+" kind="ghost" onPress={() => changeQty(l.p.id, 1)} />
                </View>
              )}
            </View>
          </Card>
        ))}

        {cart.length > 0 && (
          <Card>
            <Text style={{ fontSize: 20, fontWeight: "700" }}>Total ₹{rs(totalC)}</Text>
            <Input placeholder={`Amount received (blank = ₹${rs(totalC)})`} keyboardType="decimal-pad" value={paid} onChangeText={setPaid} />
            <Muted>
              {paid !== "" && Math.round(Number(paid) * 100) < totalC
                ? `₹${rs(totalC - Math.round(Number(paid) * 100))} will be added to the customer's dues. Select a customer below.`
                : "Paid in full."}
            </Muted>
            <Button title="Sell fully on credit" kind="ghost" onPress={() => setPaid("0")} />
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Button title="Cash" kind={method === "cash" ? "primary" : "ghost"} onPress={() => setMethod("cash")} />
              <Button title="UPI" kind={method === "upi" ? "primary" : "ghost"} onPress={() => setMethod("upi")} />
            </View>
            <Input placeholder="Customer name/phone (needed for credit)" value={custQuery} onChangeText={doSearchCustomers} />
            <Input placeholder="Customer's WhatsApp number (optional, to send the bill)" keyboardType="phone-pad" value={waPhone} onChangeText={setWaPhone} />
            {customer && (
              <Text style={{ color: colors.primary }}>
                Selected: {customer.name} · owes ₹{customer.balance}
                {customer.credit_limit ? ` · limit ₹${customer.credit_limit}` : ""}
              </Text>
            )}
            {custs.map((c) => (
              <Button key={c.id} kind="ghost" title={`${c.name} ${c.phone}${Number(c.balance) > 0 ? `  (owes ₹${c.balance})` : ""}`}
                onPress={() => { setCustomer(c); setCusts([]); }} />
            ))}
            <Err msg={err} />
            <Button title="Complete sale" onPress={checkout} />
            <Button title="Put bill on hold" kind="ghost" onPress={holdCurrent} />
            <Button title="Clear bill" kind="ghost" onPress={clearBill} />
          </Card>
        )}
        {cart.length === 0 && !weighing && <Err msg={err} />}
      </ScrollView>
    </Screen>
  );
}