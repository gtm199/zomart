import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, ScrollView, Text, View } from "react-native";
import { Button, Card, Chip, Err, Muted, Screen, colors } from "../components/ui";
import { api } from "../services/api";
import { useSession } from "../store/session";

export type Order = {
  id: number; number: number; status: string; customer_name: string; customer_phone: string; delivery_address: string;
  delivery_lat: number | null; delivery_lng: number | null; has_position: boolean; note: string; payment_method: string; on_credit: boolean;
  collect_amount: string; total: string; items: { product_name: string; unit: string; quantity: string }[];
  shop_name: string; shop_phone: string; shop_lat: number | null; shop_lng: number | null;
  trip_started: boolean; arrived: boolean; pin_locked: boolean;
};

export default function Home() {
  const router = useRouter();
  const { name, shop, shops, chooseShop, signOut } = useSession();
  const [tab, setTab] = useState<"active" | "today">("active");
  const [rows, setRows] = useState<Order[]>([]);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api<{ results: Order[] }>(`/delivery/orders/?scope=${tab}&page_size=100`);
      setRows(r.results); setErr("");
    } catch (e: any) { setErr(e.message); }
  }, [tab, shop?.id]);

  // Refresh when the screen opens and every 15 seconds, so new deliveries from the shop appear.
  useFocusEffect(useCallback(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]));

  const collected = rows.reduce((a, o) => a + Number(o.collect_amount), 0);

  return (
    <Screen safeBottom>
      <Card>
        <Text style={{ fontWeight: "700", fontSize: 16 }}>Hello {name}</Text>
        <Muted>{shop?.name}</Muted>
        {shops.length > 1 && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 6 }}>
            {shops.map((s) => <Chip key={s.id} label={s.name} active={s.id === shop?.id} onPress={() => chooseShop(s.id)} />)}
          </ScrollView>
        )}
      </Card>
      <View style={{ flexDirection: "row", gap: 8 }}>
        <Button title="To deliver" kind={tab === "active" ? "primary" : "ghost"} onPress={() => setTab("active")} />
        <Button title="Done today" kind={tab === "today" ? "primary" : "ghost"} onPress={() => setTab("today")} />
      </View>
      {tab === "today" && rows.length > 0 && <Muted>{rows.length} delivered · ₹{collected.toFixed(2)} collected at the door</Muted>}
      <Err msg={err} />
      <FlatList
        style={{ flex: 1 }}
        data={rows}
        keyExtractor={(o) => String(o.id)}
        ListEmptyComponent={<Muted>{tab === "active" ? "No deliveries for you right now. The shop will send one." : "Nothing delivered yet today."}</Muted>}
        renderItem={({ item: o }) => (
          <Card>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={{ fontWeight: "700" }}>#{o.number} · {o.customer_name}</Text>
              <Text style={{ fontWeight: "700", color: colors.primary }}>{o.on_credit ? "Fee" : "Collect"} ₹{o.collect_amount}</Text>
            </View>
            <Muted>{o.delivery_address}</Muted>
            <Muted>{o.on_credit ? "On credit: collect only the delivery fee" : `Pays ${o.payment_method}`}{o.trip_started ? " · trip started" : ""}</Muted>
            {tab === "active" && <Button title="Open" onPress={() => router.push({ pathname: "/delivery/[id]", params: { id: String(o.id) } })} />}
          </Card>
        )}
      />
      <Button title="Sign out" kind="ghost" onPress={signOut} />
    </Screen>
  );
}