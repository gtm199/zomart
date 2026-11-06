import * as Crypto from "expo-crypto";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen } from "../components/ui";
import { api, keep } from "../services/api";
import { useCart } from "../store/cart";
import type { Shop } from "./(tabs)/index";

type CreditRow = { shop: number; status: string; limit: string; owed: string; available: string };

export default function Checkout() {
  const router = useRouter();
  const cart = useCart();
  const [shop, setShop] = useState<Shop | null>(null);
  const [credit, setCredit] = useState<CreditRow | null>(null);
  const [fulfilment, setFulfilment] = useState<"delivery" | "pickup">("delivery");
  const [address, setAddress] = useState("");
  const [note, setNote] = useState("");
  const [payment, setPayment] = useState<"cash" | "upi" | "credit">("cash");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const txn = useRef(Crypto.randomUUID()); // a double tap can never place two orders

  const loadCredit = useCallback(async (shopId: number) => {
    try { const rows = await api<CreditRow[]>("/store/credit/"); setCredit(rows.find((r) => r.shop === shopId) ?? null); } catch {}
  }, []);

  useFocusEffect(useCallback(() => {
    if (cart.shop) {
      api<Shop>(`/store/shops/${cart.shop.id}/`).then((s) => { setShop(s); if (!s.accepts_delivery) setFulfilment("pickup"); }).catch((e) => setErr(e.message));
      loadCredit(cart.shop.id);
    }
    keep.get("address").then((a) => { if (a) setAddress(a); });
  }, [cart.shop?.id, loadCredit]));

  if (!cart.shop || cart.lines.length === 0) return <Screen><Muted>Your basket is empty.</Muted></Screen>;

  const subtotal = cart.total;
  const free = shop?.free_delivery_above ? subtotal >= Number(shop.free_delivery_above) : false;
  const fee = fulfilment === "delivery" && shop && !free ? Number(shop.delivery_fee) : 0;
  const below = shop ? subtotal < Number(shop.min_order) : false;

  const creditApproved = credit?.status === "approved";
  const available = creditApproved ? Number(credit!.available) : 0;
  const creditTooSmall = payment === "credit" && subtotal > available;

  const askCredit = async () => {
    setErr("");
    try { await api("/store/credit/request/", { body: { shop: cart.shop!.id } }); await loadCredit(cart.shop!.id); }
    catch (e: any) { setErr(e.message); }
  };

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
    <Screen>
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
            <Muted>Cash or UPI: you pay the shop when you {fulfilment === "delivery" ? "receive" : "collect"} the order.</Muted>
            <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
              <Button title="Cash" kind={payment === "cash" ? "primary" : "ghost"} onPress={() => setPayment("cash")} />
              <Button title="UPI" kind={payment === "upi" ? "primary" : "ghost"} onPress={() => setPayment("upi")} />
              {creditApproved && <Button title="Pay later (credit)" kind={payment === "credit" ? "primary" : "ghost"} onPress={() => setPayment("credit")} />}
            </View>
            {creditApproved ? (
              <Muted>Credit with this shop: ₹{available.toFixed(2)} available.</Muted>
            ) : credit?.status === "requested" ? (
              <Muted>You asked this shop for credit. Waiting for the shop to answer.</Muted>
            ) : credit?.status === "suspended" ? (
              <Muted>This shop has stopped new credit for now.</Muted>
            ) : (
              <>
                <Muted>{credit?.status === "declined" ? "The shop did not give you credit before. You can ask again." : "Want to pay later? Ask this shop for credit."}</Muted>
                <Button title="Ask this shop for credit" kind="ghost" onPress={askCredit} />
              </>
            )}
            {payment === "credit" && (
              <Muted>
                ₹{subtotal.toFixed(2)} for the items goes on your account at this shop.
                {fulfilment === "delivery" && fee > 0 ? ` Pay the delivery fee ₹${fee.toFixed(2)} in cash at the door.` : ""}
              </Muted>
            )}
          </Card>
          <Card>
            <Text>Items ₹{subtotal.toFixed(2)}</Text>
            {fulfilment === "delivery" && <Text>Delivery ₹{fee.toFixed(2)}{free ? " (free)" : ""}</Text>}
            <Text style={{ fontSize: 20, fontWeight: "700" }}>Total ₹{(subtotal + fee).toFixed(2)}</Text>
            {below && <Text style={{ color: "#b91c1c" }}>The minimum order for this shop is ₹{Number(shop!.min_order)}.</Text>}
            {creditTooSmall && <Text style={{ color: "#b91c1c" }}>Your credit left (₹{available.toFixed(2)}) is less than the items. Choose cash or UPI, or remove something.</Text>}
            <Muted>The shop may change quantities if something is short. You will see the final total.</Muted>
          </Card>
          <Err msg={err} />
          <Button title={busy ? "Placing order..." : "Place order"} onPress={place}
            disabled={busy || below || creditTooSmall || (fulfilment === "delivery" && address.trim().length < 8)} />
        </ScrollView>
    </Screen>
  );
}