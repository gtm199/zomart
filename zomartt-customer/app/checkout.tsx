import * as Crypto from "expo-crypto";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen } from "../components/ui";
import { api, keep } from "../services/api";
import { useCart } from "../store/cart";
import type { Shop } from "./(tabs)/index";

export default function Checkout() {
  const router = useRouter();
  const cart = useCart();
  const [shop, setShop] = useState<Shop | null>(null);
  const [fulfilment, setFulfilment] = useState<"delivery" | "pickup">("delivery");
  const [address, setAddress] = useState("");
  const [note, setNote] = useState("");
  const [payment, setPayment] = useState<"cash" | "upi">("cash");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const txn = useRef(Crypto.randomUUID()); // a double tap can never place two orders

  useFocusEffect(useCallback(() => {
    if (cart.shop) api<Shop>(`/store/shops/${cart.shop.id}/`).then((s) => {
      setShop(s);
      if (!s.accepts_delivery) setFulfilment("pickup");
    }).catch((e) => setErr(e.message));
    keep.get("address").then((a) => { if (a) setAddress(a); });
  }, [cart.shop?.id]));

  if (!cart.shop || cart.lines.length === 0) return <Screen><Muted>Your basket is empty.</Muted></Screen>;

  const subtotal = cart.total;
  const free = shop?.free_delivery_above ? subtotal >= Number(shop.free_delivery_above) : false;
  const fee = fulfilment === "delivery" && shop && !free ? Number(shop.delivery_fee) : 0;
  const below = shop ? subtotal < Number(shop.min_order) : false;

  const place = async () => {
    if (!cart.shop) return;
    setBusy(true); setErr("");
    try {
      const order = await api<{ id: number }>("/store/orders/", {
        body: {
          shop: cart.shop.id, client_txn_id: txn.current, fulfilment, address, note, payment_method: payment,
          items: cart.lines.map((l) => ({ shop_product: l.id, quantity: String(l.qty) })),
        },
      });
      if (address) await keep.set("address", address);
      cart.clear();
      router.replace({ pathname: "/order/[id]", params: { id: String(order.id) } });
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <Screen safeBottom>
      <ScrollView keyboardShouldPersistTaps="handled">
        <Card>
          <Text style={{ fontWeight: "700" }}>{cart.shop.name}</Text>
          {cart.lines.map((l) => <Muted key={l.id}>{l.name} × {l.qty}{l.loose ? ` ${l.unit}` : ""}</Muted>)}
        </Card>
        <Card>
          <Text style={{ fontWeight: "700" }}>How do you want it?</Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            {shop?.accepts_delivery && <Button title="Home delivery" kind={fulfilment === "delivery" ? "primary" : "ghost"} onPress={() => setFulfilment("delivery")} />}
            {shop?.accepts_pickup && <Button title="I will pick up" kind={fulfilment === "pickup" ? "primary" : "ghost"} onPress={() => setFulfilment("pickup")} />}
          </View>
          {fulfilment === "delivery" && (
            <Input placeholder="Full delivery address (house, street, landmark)" multiline value={address} onChangeText={setAddress} />
          )}
          <Input placeholder="Note for the shop (optional)" value={note} onChangeText={setNote} />
        </Card>
        <Card>
          <Text style={{ fontWeight: "700" }}>Payment</Text>
          <Muted>You pay the shop when you {fulfilment === "delivery" ? "receive" : "collect"} the order.</Muted>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Button title="Cash" kind={payment === "cash" ? "primary" : "ghost"} onPress={() => setPayment("cash")} />
            <Button title="UPI" kind={payment === "upi" ? "primary" : "ghost"} onPress={() => setPayment("upi")} />
          </View>
        </Card>
        <Card>
          <Text>Items ₹{subtotal.toFixed(2)}</Text>
          {fulfilment === "delivery" && <Text>Delivery ₹{fee.toFixed(2)}{free ? " (free)" : ""}</Text>}
          <Text style={{ fontSize: 20, fontWeight: "700" }}>Total ₹{(subtotal + fee).toFixed(2)}</Text>
          {below && <Text style={{ color: "#b91c1c" }}>The minimum order for this shop is ₹{Number(shop!.min_order)}.</Text>}
          <Muted>The shop may change quantities if something is short. You will see the final total.</Muted>
        </Card>
        <Err msg={err} />
        <Button title={busy ? "Placing order..." : "Place order"} onPress={place}
          disabled={busy || below || (fulfilment === "delivery" && address.trim().length < 8)} />
      </ScrollView>
    </Screen>
  );
}