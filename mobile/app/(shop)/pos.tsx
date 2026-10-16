import { CameraView, useCameraPermissions } from "expo-camera";
import * as Crypto from "expo-crypto";
import { useRef, useState } from "react";
import { Alert, FlatList, Linking, ScrollView, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { Customer, Master, Page, ShopProduct } from "../../types";

type Line = { sp: ShopProduct; qty: number };

export default function Pos() {
  const [perm, requestPerm] = useCameraPermissions();
  const [scanning, setScanning] = useState(false);
  const [cart, setCart] = useState<Line[]>([]);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<ShopProduct[]>([]);
  const [unlisted, setUnlisted] = useState<Master | null>(null);
  const [newPrice, setNewPrice] = useState("");
  const [newStock, setNewStock] = useState("");
  const [paid, setPaid] = useState("");
  const [method, setMethod] = useState<"cash" | "upi">("cash");
  const [custQuery, setCustQuery] = useState("");
  const [custs, setCusts] = useState<Customer[]>([]);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [err, setErr] = useState("");
  const lastScan = useRef(0);
  const txnId = useRef(Crypto.randomUUID()); // reused on retry => the server never double-bills

  const total = cart.reduce((a, l) => a + Number(l.sp.selling_price) * l.qty, 0);
  const addToCart = (sp: ShopProduct) =>
    setCart((c) => (c.find((l) => l.sp.id === sp.id) ? c.map((l) => (l.sp.id === sp.id ? { ...l, qty: l.qty + 1 } : l)) : [...c, { sp, qty: 1 }]));
  const changeQty = (id: number, d: number) =>
    setCart((c) => c.map((l) => (l.sp.id === id ? { ...l, qty: Math.max(0, l.qty + d) } : l)).filter((l) => l.qty > 0));

  const onScan = async ({ data }: { data: string }) => {
    if (Date.now() - lastScan.current < 1500) return;
    lastScan.current = Date.now();
    setErr("");
    try {
      const r = await api<{ master_product: Master | null; shop_product: ShopProduct | null }>(`/shop/products/by-barcode/${encodeURIComponent(data)}/`);
      if (r.shop_product) addToCart(r.shop_product);
      else if (r.master_product) { setUnlisted(r.master_product); setScanning(false); }
    } catch (e: any) {
      if (e.status === 404) Alert.alert("Unknown barcode", "Not in the catalogue. Search by name, or ask the admin to add it.");
      else setErr(e.message);
    }
  };

  const doSearch = async (t: string) => {
    setSearch(t);
    if (t.length < 2) return setResults([]);
    try { setResults((await api<Page<ShopProduct>>(`/shop/products/?search=${encodeURIComponent(t)}&enabled=true`)).results); } catch {}
  };
  const searchCustomers = async (t: string) => {
    setCustQuery(t);
    if (t.length < 2) return setCusts([]);
    try { setCusts((await api<Page<Customer>>(`/shop/customers/?search=${encodeURIComponent(t)}`)).results); } catch {}
  };

  const addUnlisted = async () => {
    if (!unlisted) return;
    try {
      const sp = await api<ShopProduct>("/shop/products/", { body: { master_product: unlisted.id, selling_price: newPrice, opening_stock: newStock || "0" } });
      addToCart(sp); setUnlisted(null); setNewPrice(""); setNewStock("");
    } catch (e: any) { setErr(e.message); }
  };

  const checkout = async () => {
    setErr("");
    const paidAmount = paid === "" ? total : Number(paid);
    try {
      const sale = await api<any>("/shop/sales/", {
        body: {
          client_txn_id: txnId.current,
          customer: customer?.id ?? null,
          items: cart.map((l) => ({ shop_product: l.sp.id, quantity: String(l.qty) })),
          payments: paidAmount > 0 ? [{ method, amount: paidAmount.toFixed(2) }] : [],
        },
      });
      const rec = await api<{ whatsapp_url: string }>(`/shop/sales/${sale.id}/receipt/`);
      setCart([]); setPaid(""); setCustomer(null); setCustQuery(""); setCusts([]);
      txnId.current = Crypto.randomUUID();
      Alert.alert(`Bill ${sale.invoice_number}`, `Total ₹${sale.total}`, [
        { text: "Done" },
        { text: "Send on WhatsApp", onPress: () => Linking.openURL(rec.whatsapp_url) },
      ]);
    } catch (e: any) { setErr(e.message); }
  };

  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        {scanning ? (
          <View style={{ height: 220, borderRadius: 10, overflow: "hidden" }}>
            <CameraView style={{ flex: 1 }} onBarcodeScanned={onScan}
              barcodeScannerSettings={{ barcodeTypes: ["ean13", "ean8", "upc_a", "upc_e", "code128"] }} />
          </View>
        ) : null}
        <Button title={scanning ? "Stop scanner" : "Scan barcode"} kind="ghost"
          onPress={async () => { if (!perm?.granted) await requestPerm(); setScanning((s) => !s); }} />
        <Input placeholder="Or search product by name" value={search} onChangeText={doSearch} />
        {results.map((sp) => (
          <Card key={sp.id}>
            <Text style={{ fontWeight: "600" }}>{sp.master_product.display_name}</Text>
            <Muted>₹{sp.selling_price} · stock {sp.stock_qty}</Muted>
            <Button title="Add to bill" onPress={() => { addToCart(sp); setSearch(""); setResults([]); }} />
          </Card>
        ))}

        {unlisted && (
          <Card>
            <Text style={{ fontWeight: "700" }}>{unlisted.display_name}</Text>
            <Muted>Not in your shop yet. MRP: {unlisted.mrp ?? "n/a"}</Muted>
            <Input placeholder="Your selling price" keyboardType="decimal-pad" value={newPrice} onChangeText={setNewPrice} />
            <Input placeholder="Stock in hand" keyboardType="decimal-pad" value={newStock} onChangeText={setNewStock} />
            <Button title="Add to my shop & bill" onPress={addUnlisted} disabled={!newPrice} />
            <Button title="Cancel" kind="ghost" onPress={() => setUnlisted(null)} />
          </Card>
        )}

        <Text style={{ fontWeight: "700", marginTop: 10 }}>Bill</Text>
        {cart.length === 0 && <Muted>Scan or search to add items.</Muted>}
        {cart.map((l) => (
          <Card key={l.sp.id}>
            <Text>{l.sp.master_product.display_name}</Text>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <Muted>₹{l.sp.selling_price} × {l.qty}</Muted>
              <View style={{ flexDirection: "row", gap: 8 }}>
                <Button title="−" kind="ghost" onPress={() => changeQty(l.sp.id, -1)} />
                <Button title="+" kind="ghost" onPress={() => changeQty(l.sp.id, 1)} />
              </View>
            </View>
          </Card>
        ))}

        {cart.length > 0 && (
          <Card>
            <Text style={{ fontSize: 20, fontWeight: "700" }}>Total ₹{total.toFixed(2)}</Text>
            <Input placeholder={`Amount received (blank = ₹${total.toFixed(2)})`} keyboardType="decimal-pad" value={paid} onChangeText={setPaid} />
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Button title="Cash" kind={method === "cash" ? "primary" : "ghost"} onPress={() => setMethod("cash")} />
              <Button title="UPI" kind={method === "upi" ? "primary" : "ghost"} onPress={() => setMethod("upi")} />
            </View>
            <Input placeholder="Customer name/phone (needed for credit)" value={custQuery} onChangeText={searchCustomers} />
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
