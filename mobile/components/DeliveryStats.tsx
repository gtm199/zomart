import { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { api } from "../services/api";
import { Button, Card, Err, Muted, colors } from "./ui";

/** Online Orders > Deliveries: how many deliveries were made and the delivery charges.
 *  Kept separate from bills and reports (delivery charges are never part of a bill). */
type Row = { deliveries: number; charges: string };
type Stats = {
  from: string; to: string; deliveries: number; charges: string; paid_deliveries: number; free_deliveries: number;
  average_charge: string; not_delivered: number; in_progress_now: number; out_for_delivery_now: number;
  by_day: ({ date: string } & Row)[]; by_rider: ({ rider: string } & Row)[]; by_payment: ({ method: string } & Row)[];
  note: string;
};

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const pretty = (s: string) => new Date(`${s}T00:00:00`).toLocaleDateString(undefined, { day: "2-digit", month: "short" });

function periods() {
  const t = new Date();
  const y = new Date(t); y.setDate(t.getDate() - 1);
  const w = new Date(t); w.setDate(t.getDate() - ((t.getDay() + 6) % 7));   // Monday
  const m = new Date(t.getFullYear(), t.getMonth(), 1);
  const lmFrom = new Date(t.getFullYear(), t.getMonth() - 1, 1);
  const lmTo = new Date(t.getFullYear(), t.getMonth(), 0);
  return [
    { key: "today", title: "Today", from: iso(t), to: iso(t) },
    { key: "yesterday", title: "Yesterday", from: iso(y), to: iso(y) },
    { key: "week", title: "This week", from: iso(w), to: iso(t) },
    { key: "month", title: "This month", from: iso(m), to: iso(t) },
    { key: "last", title: "Last month", from: iso(lmFrom), to: iso(lmTo) },
  ];
}
const METHOD: Record<string, string> = { cash: "Cash", upi: "UPI", credit: "Pay later (credit)" };

const Line = ({ label, value, strong }: { label: string; value: string; strong?: boolean }) => (
  <View style={{ flexDirection: "row", justifyContent: "space-between", marginVertical: 2 }}>
    <Text style={{ color: colors.text, fontWeight: strong ? "700" : "400", flex: 1 }}>{label}</Text>
    <Text style={{ color: colors.text, fontWeight: strong ? "700" : "400" }}>{value}</Text>
  </View>
);

export default function DeliveryStats() {
  const [period, setPeriod] = useState("today");
  const [s, setS] = useState<Stats | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    const p = periods().find((x) => x.key === period)!;
    setLoading(true);
    try { setS(await api<Stats>(`/shop/orders/delivery-stats/?from=${p.from}&to=${p.to}`)); setErr(""); }
    catch (e: any) { setErr(e.message); }
    finally { setLoading(false); }
  }, [period]);
  useEffect(() => { load(); }, [load]);

  return (
    <ScrollView>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0 }}>
        <View style={{ flexDirection: "row", gap: 6 }}>
          {periods().map((p) => <Button key={p.key} title={p.title} kind={period === p.key ? "primary" : "ghost"} onPress={() => setPeriod(p.key)} />)}
        </View>
      </ScrollView>
      <Err msg={err} />
      {!s ? <Muted>{loading ? "Loading..." : ""}</Muted> : (
        <>
          <Card>
            <Muted>{s.from === s.to ? pretty(s.from) : `${pretty(s.from)} - ${pretty(s.to)}`} · delivered orders</Muted>
            <View style={{ flexDirection: "row", gap: 10, marginVertical: 6 }}>
              <View style={{ flex: 1, padding: 10, borderRadius: 8, backgroundColor: "#ecfdf5" }}>
                <Text style={{ fontSize: 26, fontWeight: "800", color: colors.primary }}>{s.deliveries}</Text>
                <Muted>Deliveries</Muted>
              </View>
              <View style={{ flex: 1, padding: 10, borderRadius: 8, backgroundColor: "#eff6ff" }}>
                <Text style={{ fontSize: 26, fontWeight: "800", color: "#1d4ed8" }}>₹{s.charges}</Text>
                <Muted>Delivery charges</Muted>
              </View>
            </View>
            <Line label="Paid deliveries" value={String(s.paid_deliveries)} />
            <Line label="Free deliveries" value={String(s.free_deliveries)} />
            <Line label="Average charge" value={`₹${s.average_charge}`} />
            <Line label="Ordered but not delivered (declined / cancelled)" value={String(s.not_delivered)} />
            <Line label="Deliveries still in progress now" value={`${s.in_progress_now}${s.out_for_delivery_now ? ` (${s.out_for_delivery_now} on the way)` : ""}`} />
          </Card>
          {s.by_rider.length > 0 && (
            <Card>
              <Text style={{ fontWeight: "700" }}>By delivery person</Text>
              {s.by_rider.map((r) => <Line key={r.rider} label={`${r.rider} · ${r.deliveries}`} value={`₹${r.charges}`} />)}
            </Card>
          )}
          {s.by_payment.length > 0 && (
            <Card>
              <Text style={{ fontWeight: "700" }}>By how the order was paid</Text>
              {s.by_payment.map((r) => <Line key={r.method} label={`${METHOD[r.method] ?? r.method} · ${r.deliveries}`} value={`₹${r.charges}`} />)}
              <Muted>For pay-later orders the delivery charge is paid in cash at the door.</Muted>
            </Card>
          )}
          {s.by_day.length > 1 && (
            <Card>
              <Text style={{ fontWeight: "700" }}>Day by day</Text>
              {s.by_day.map((d) => <Line key={d.date} label={`${pretty(d.date)} · ${d.deliveries}`} value={`₹${d.charges}`} />)}
            </Card>
          )}
          <Muted>{s.note}</Muted>
          <Button title="Refresh" kind="ghost" onPress={load} />
        </>
      )}
    </ScrollView>
  );
}
