import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Text, View } from "react-native";
import { Card, Err, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";

export const STATUS: Record<string, string> = {
  placed: "Waiting for the shop to accept", accepted: "Accepted, being prepared", packed: "Packed",
  out_for_delivery: "On the way to you", ready_for_pickup: "Ready, please collect it from the shop",
  completed: "Done", cancelled: "Cancelled", rejected: "Declined by the shop",
};

type Row = { id: number; number: number; shop_name: string; status: string; fulfilment: string; total: string; created_at: string };

export default function Orders() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>([]);
  const [err, setErr] = useState("");

  useFocusEffect(useCallback(() => {
    const load = () => api<{ results: Row[] }>("/store/orders/").then((r) => { setRows(r.results); setErr(""); }).catch((e) => setErr(e.message));
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []));

  return (
    <Screen>
      <Err msg={err} />
      <FlatList
        data={rows}
        keyExtractor={(o) => String(o.id)}
        ListEmptyComponent={<Muted>No orders yet.</Muted>}
        renderItem={({ item: o }) => (
          <Card>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={{ fontWeight: "700" }}>{o.shop_name} · #{o.number}</Text>
              <Text style={{ fontWeight: "700" }}>₹{o.total}</Text>
            </View>
            <Text style={{ color: ["cancelled", "rejected"].includes(o.status) ? colors.danger : colors.primary, fontWeight: "600" }}>{STATUS[o.status]}</Text>
            <Muted>{o.fulfilment === "delivery" ? "Delivery" : "Pickup"} · {new Date(o.created_at).toLocaleString("en-IN")}</Muted>
            <Text style={{ color: colors.primary, marginTop: 6 }} onPress={() => router.push({ pathname: "/order/[id]", params: { id: String(o.id) } })}>See details ›</Text>
          </Card>
        )}
      />
    </Screen>
  );
}