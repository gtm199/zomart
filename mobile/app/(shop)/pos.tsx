import { CameraView, useCameraPermissions } from "expo-camera";
import * as Crypto from "expo-crypto";
import { useRef, useState } from "react";
import { Alert, Linking, ScrollView, Text, View } from "react-native";
import SyncBanner from "../../components/SyncBanner";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { LocalCustomer, LocalProduct, findByBarcode, getProduct, queueSale, searchCustomers, searchProducts } from "../../services/localdb";
import { receiptText, rs, toCents, waLink } from "../../services/receipt";
import { notifySync, runSync } from "../../services/sync";
import { useSession } from "../../store/session";
import { Master } from "../../types";

type Line = { p: LocalProduct; qty: number };

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
  const lastScan = useRef(0);
  const txnId = useRef(Crypto.randomUUID()); // saved with the bill: the server never bills the same one twice

  const totalC = cart.reduce((a, l) => a + toCents(l.p.selling_price) * l.qty, 0);
  const available = (p: LocalProduct) => Number(p.stock_qty) - p.pending_qty;

  const addToCart = (p: LocalProduct) => {
    if (!p.is_enabled) { Alert.alert("Not available", `${p.name} is switched off.`); return; }
    setCart((c) => (c.find((l) => l.p.id === p.id) ? c.map((l) => (l.p.id === p.id ? { ...l, qty: l.qty + 1 } : l)) : [...c, { p, qty: 1 }]));
  };
  const changeQty = (id: number, d: number) =>
    setCart((c) => c.map((l) => (l.p.id === id ? { ...l, qty: Math.max(0, l.qty + d) } : l)).filter((l) => l.qty > 0));

  const onScan = async ({ data }: { data: string }) => {
    if (Date.now() - lastScan.current < 1500) return;
    lastScan.current = Date.now();
    setErr("");
    const local = await findByBarcode(data);
    if (local) { addToCart(local); return; }
    try {
      const r = await api<{ master_product: Master | null; shop_product: { id: number } | null }>(`/shop/products/by-barcode/${encodeURIComponent(data)}/`);
      if (r.shop_product) {
        await runSync(); // a product added on another phone: download it
        const again = await getProduct(r.shop_product.id);
        if (again) addToCart(again);
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
      if (lp) addToCart(lp);
      setUnlisted(null); setNewPrice(""); setNewStock("");
    } catch (e: any) { setErr(e.status === 0 ? "Adding a new product needs internet." : e.message); }
  };

  const checkout = async () => {
    setErr("");
    const paidC = paid === "" ? totalC : Math.round(Number(paid) * 100);
    if (!(paidC >= 0)) { setErr("Enter a valid amount received."); return; }
    if (paidC > totalC) { setErr("Amount received cannot be more than the bill total."); return; }
    if (paidC < totalC && !customer) { setErr("Select a customer to sell on credit."); return; }

    const txn = txnId.current;
    const ref = "OFF-" + txn.slice(0, 6).toUpperCase(); // temporary number; the real one comes after upload
    const lines = cart.map((l) => ({ name: l.p.name, qty: l.qty, price: l.p.selling_price }));
    const text = receiptText(shop?.name ?? "Shop", ref, lines, totalC, paidC);
    const phone = waPhone || customer?.whatsapp_number || customer?.phone || "";

    await queueSale(
      txn,
      {
        client_txn_id: txn,
        offline: true,
        client_created_at: new Date().toISOString(),
        customer: customer?.id ?? null,
        items: cart.map((l) => ({ shop_product: l.p.id, quantity: String(l.qty), unit_price: l.p.selling_price })),
        payments: paidC > 0 ? [{ method, amount: rs(paidC) }] : [],
      },
      JSON.stringify({ ref, lines, total: rs(totalC), paid: rs(paidC), customer: customer?.name ?? "", receipt: text, phone })
    );

    txnId.current = Crypto.randomUUID();
    setCart([]); setPaid(""); setCustomer(null); setCustQuery(""); setCusts([]); setWaPhone("");
    notifySync();
    runSync(); // upload right away if there is internet

    Alert.alert(`Bill saved (${ref})`, `Total ₹${rs(totalC)}. It uploads automatically; the final bill number appears after that.`, [
      { text: "Done" },
      { text: "Send on WhatsApp", onPress: () => Linking.openURL(waLink(phone, text)) },
    ]);
  };

  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        <SyncBanner />
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
            <Text style={{ fontWeight: "600" }}>{p.name}</Text>
            <Muted>₹{p.selling_price} · stock about {available(p)}</Muted>
            <Button title="Add to bill" onPress={() => { addToCart(p); setSearch(""); setResults([]); }} />
          </Card>
        ))}

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
              <Muted>₹{l.p.selling_price} × {l.qty}{available(l.p) < l.qty ? "  (stock low)" : ""}</Muted>
              <View style={{ flexDirection: "row", gap: 8 }}>
                <Button title="−" kind="ghost" onPress={() => changeQty(l.p.id, -1)} />
                <Button title="+" kind="ghost" onPress={() => changeQty(l.p.id, 1)} />
              </View>
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
            {customer && <Text style={{ color: colors.primary }}>Selected: {customer.name}</Text>}
            {custs.map((c) => <Button key={c.id} kind="ghost" title={`${c.name} ${c.phone}`} onPress={() => { setCustomer(c); setCusts([]); }} />)}
            <Err msg={err} />
            <Button title="Complete sale" onPress={checkout} />
          </Card>
        )}
        {cart.length === 0 && <Err msg={err} />}
      </ScrollView>
    </Screen>
  );
}
