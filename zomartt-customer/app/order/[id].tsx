import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Linking, ScrollView, Text } from "react-native";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { STATUS } from "../(tabs)/orders";

type Item = { id: number; product_name: string; unit: string; ordered_quantity: string; quantity: string; unit_price: string; line_total: string };
type Order = {
  id: number; number: number; shop_name: string; shop_phone: string; status: string; fulfilment: string; delivery_address: string;
  note: string; payment_method: string; subtotal: string; delivery_fee: string; total: string; reason: string; items: Item[];
  events: { status: string; note: string; created_at: string }[];
};

export default function OrderDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [o, setO] = useState<Order | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(() => api<Order>(`/store/orders/${id}/`).then((r) => { setO(r); setErr(""); }).catch((e) => setErr(e.message)), [id]);
  useFocusEffect(useCallback(() => {
    load();
    const t = setInterval(load, 15000); // follow the order while this screen is open
    return () => clearInterval(t);
  }, [load]));

  const cancel = () =>
    Alert.alert("Cancel this order?", "You can only cancel before the shop accepts it.", [
      { text: "No", style: "cancel" },
      { text: "Yes, cancel", style: "destructive", onPress: async () => { try { await api(`/store/orders/${id}/cancel/`, { body: {} }); load(); } catch (e: any) { setErr(e.message); } } },
    ]);

  if (!o) return <Screen><Err msg={err} /><Muted>Loading...</Muted></Screen>;
  const payNow = ["accepted", "packed", "out_for_delivery", "ready_for_pickup"].includes(o.status);
  return (
    <Screen safeBottom>
      <ScrollView>
        <Card>
          <Text style={{ fontWeight: "700", fontSize: 16 }}>{o.shop_name} · order #{o.number}</Text>
          <Text style={{ fontWeight: "700", color: ["cancelled", "rejected"].includes(o.status) ? colors.danger : colors.primary }}>{STATUS[o.status]}</Text>
          {o.reason ? <Text>Reason: {o.reason}</Text> : null}
          {payNow && <Muted>Pay ₹{o.total} in {o.payment_method === "cash" ? "cash" : "UPI"} to the shop when you {o.fulfilment === "delivery" ? "receive" : "collect"} the order.</Muted>}
        </Card>
        <Card>
          {o.items.map((i) => (
            <Text key={i.id}>
              {i.product_name} × {Number(i.quantity)}{i.unit ? ` ${i.unit}` : ""} = ₹{i.line_total}
              {Number(i.quantity) !== Number(i.ordered_quantity) ? `  (you ordered ${Number(i.ordered_quantity)})` : ""}
            </Text>
          ))}
          <Text>Items ₹{o.subtotal}</Text>
          {o.fulfilment === "delivery" && <Text>Delivery ₹{o.delivery_fee}</Text>}
          <Text style={{ fontWeight: "700", fontSize: 18 }}>Total ₹{o.total}</Text>
          {o.fulfilment === "delivery" ? <Muted>Deliver to: {o.delivery_address}</Muted> : <Muted>You will collect it from the shop.</Muted>}
          {o.note ? <Muted>Your note: {o.note}</Muted> : null}
        </Card>
        <Card>
          <Text style={{ fontWeight: "700" }}>Progress</Text>
          {o.events.map((e, i) => (
            <Text key={i}>{new Date(e.created_at).toLocaleString("en-IN")}  ·  {STATUS[e.status]}{e.note ? ` (${e.note})` : ""}</Text>
          ))}
        </Card>
        <Err msg={err} />
        {o.shop_phone ? <Button title="Call the shop" kind="ghost" onPress={() => Linking.openURL(`tel:${o.shop_phone}`)} /> : null}
        {o.status === "placed" && <Button title="Cancel order" kind="danger" onPress={cancel} />}
      </ScrollView>
    </Screen>
  );
}