import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Linking, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { waLink } from "../../services/receipt";

type Item = { id: number; product_name: string; unit: string; ordered_quantity: string; quantity: string; unit_price: string; line_total: string };
type Order = {
  id: number; number: number; status: string; fulfilment: "delivery" | "pickup"; customer_name: string; customer_phone: string;
  delivery_address: string; note: string; payment_method: string; subtotal: string; delivery_fee: string; total: string;
  reason: string; created_at: string; items: Item[];
};

const LABEL: Record<string, string> = {
  placed: "NEW - waiting for you", accepted: "Accepted", packed: "Packed", out_for_delivery: "Out for delivery",
  ready_for_pickup: "Ready for pickup", completed: "Completed", cancelled: "Cancelled", rejected: "Declined",
};
const MSG: Record<string, string> = {
  accepted: "has been accepted and is being prepared", packed: "is packed", out_for_delivery: "is on its way",
  ready_for_pickup: "is ready. Please collect it from the shop", completed: "is complete. Thank you!",
};

export default function Orders() {
  const router = useRouter();
  const [scope, setScope] = useState<"active" | "past">("active");
  const [rows, setRows] = useState<Order[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [adjust, setAdjust] = useState<Record<number, string>>({});
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api<{ results: Order[] }>(`/shop/orders/?scope=${scope}&page_size=100`);
      setRows(r.results);
      setErr("");
    } catch (e: any) { setErr(e.message); }
  }, [scope]);

  // Refresh when the screen opens and every 20 seconds while it is open, so new orders show up.
  useFocusEffect(
    useCallback(() => {
      load();
      const t = setInterval(load, 20000);
      return () => clearInterval(t);
    }, [load])
  );

  const act = async (o: Order, action: string, body: object = {}) => {
    setErr("");
    try {
      await api(`/shop/orders/${o.id}/${action}/`, { body });
      setReason(""); setAdjust({}); setOpen(null);
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const accept = (o: Order) => {
    const items = o.items
      .filter((i) => adjust[i.id] !== undefined && adjust[i.id] !== "" && Number(adjust[i.id]) !== Number(i.ordered_quantity))
      .map((i) => ({ item: i.id, quantity: adjust[i.id] }));
    act(o, "accept", { items });
  };

  const tell = (o: Order) =>
    Linking.openURL(waLink(o.customer_phone, `Hello ${o.customer_name}, your order #${o.number} ${MSG[o.status] ?? "was updated"}.`));

  return (
    <Screen>
      <Button title="← Back to menu" kind="ghost" onPress={() => router.navigate("/(shop)/menu")} />
      <View style={{ flexDirection: "row", gap: 8 }}>
        <Button title="Active" kind={scope === "active" ? "primary" : "ghost"} onPress={() => setScope("active")} />
        <Button title="Past" kind={scope === "past" ? "primary" : "ghost"} onPress={() => setScope("past")} />
      </View>
      <Err msg={err} />
      <FlatList
        data={rows}
        keyExtractor={(o) => String(o.id)}
        ListEmptyComponent={<Muted>{scope === "active" ? "No active orders." : "No past orders."}</Muted>}
        renderItem={({ item: o }) => (
          <Card>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={{ fontWeight: "700" }}>#{o.number} · {o.customer_name}</Text>
              <Text style={{ fontWeight: "700" }}>₹{o.total}</Text>
            </View>
            <Text style={{ color: o.status === "placed" ? colors.danger : colors.text, fontWeight: "700" }}>{LABEL[o.status]}</Text>
            <Muted>{o.fulfilment === "delivery" ? "Delivery" : "Pickup"} · pays {o.payment_method} · {new Date(o.created_at).toLocaleString("en-IN")}</Muted>
            {o.reason ? <Muted>{o.reason}</Muted> : null}

            {open === o.id ? (
              <>
                {o.fulfilment === "delivery" && <Text>📍 {o.delivery_address}</Text>}
                {o.note ? <Text>Note: {o.note}</Text> : null}
                <Text>📞 {o.customer_phone}</Text>
                {o.items.map((i) => (
                  <View key={i.id} style={{ marginTop: 4 }}>
                    <Text>
                      {i.product_name} × {Number(i.quantity)}{i.unit ? ` ${i.unit}` : ""} = ₹{i.line_total}
                      {Number(i.quantity) !== Number(i.ordered_quantity) ? ` (ordered ${Number(i.ordered_quantity)})` : ""}
                    </Text>
                    {o.status === "placed" && (
                      <Input placeholder={`Can supply (ordered ${Number(i.ordered_quantity)}, 0 = none)`} keyboardType="decimal-pad"
                        value={adjust[i.id] ?? ""} onChangeText={(v) => setAdjust({ ...adjust, [i.id]: v })} />
                    )}
                  </View>
                ))}
                <Text>Items ₹{o.subtotal}{o.fulfilment === "delivery" ? ` + delivery ₹${o.delivery_fee}` : ""} = ₹{o.total}</Text>

                {o.status === "placed" && (
                  <>
                    <Button title="Accept order" onPress={() => accept(o)} />
                    <Input placeholder="Reason, if you decline" value={reason} onChangeText={setReason} />
                    <Button title="Decline" kind="danger" onPress={() => act(o, "reject", { reason })} disabled={!reason.trim()} />
                  </>
                )}
                {o.status === "accepted" && <Button title="Mark as packed" onPress={() => act(o, "pack")} />}
                {o.status === "packed" && (
                  <Button title={o.fulfilment === "delivery" ? "Out for delivery" : "Ready for pickup"} onPress={() => act(o, "ready")} />
                )}
                {(o.status === "out_for_delivery" || o.status === "ready_for_pickup") && (
                  <>
                    <Muted>Handed over and paid? This makes the bill and takes the stock.</Muted>
                    <View style={{ flexDirection: "row", gap: 8 }}>
                      <Button title="Paid in cash" onPress={() => act(o, "complete", { payment_method: "cash" })} />
                      <Button title="Paid by UPI" kind="ghost" onPress={() => act(o, "complete", { payment_method: "upi" })} />
                    </View>
                  </>
                )}
                {["accepted", "packed", "out_for_delivery", "ready_for_pickup"].includes(o.status) && (
                  <>
                    <Input placeholder="Reason, if you must cancel" value={reason} onChangeText={setReason} />
                    <Button title="Cancel order" kind="danger" onPress={() => act(o, "cancel", { reason })} disabled={!reason.trim()} />
                  </>
                )}
                <Button title="Call customer" kind="ghost" onPress={() => Linking.openURL(`tel:${o.customer_phone}`)} />
                {MSG[o.status] && <Button title="Message on WhatsApp" kind="ghost" onPress={() => tell(o)} />}
                <Button title="Close" kind="ghost" onPress={() => { setOpen(null); setAdjust({}); }} />
              </>
            ) : <Button title="Open" kind="ghost" onPress={() => { setOpen(o.id); setReason(""); setAdjust({}); }} />}
          </Card>
        )}
      />
    </Screen>
  );
}