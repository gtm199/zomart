import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
type Range = "today" | "week" | "month";

function rangeDates(r: Range) {
  const now = new Date();
  if (r === "today") return [iso(now), iso(now)];
  if (r === "week") return [iso(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6)), iso(now)];
  return [iso(new Date(now.getFullYear(), now.getMonth(), 1)), iso(now)];
}

const Row = ({ label, value, bold }: { label: string; value: string; bold?: boolean }) => (
  <View style={{ flexDirection: "row", justifyContent: "space-between", marginVertical: 2 }}>
    <Text style={{ fontWeight: bold ? "700" : "400" }}>{label}</Text>
    <Text style={{ fontWeight: bold ? "700" : "400" }}>{value}</Text>
  </View>
);

export default function Reports() {
  const [range, setRange] = useState<Range>("month");
  const [pl, setPl] = useState<any>(null);
  const [sa, setSa] = useState<any>(null);
  const [ag, setAg] = useState<any>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    const [from, to] = rangeDates(range);
    try {
      const [a, b, c] = await Promise.all([
        api(`/shop/reports/profit-loss/?from=${from}&to=${to}`),
        api(`/shop/reports/sales-analysis/?from=${from}&to=${to}`),
        api(`/shop/reports/ageing/`),
      ]);
      setPl(a); setSa(b); setAg(c);
    } catch (e: any) { setErr(e.message); }
  }, [range]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <Screen>
      <ScrollView>
        <View style={{ flexDirection: "row", gap: 6 }}>
          <Button title="Today" kind={range === "today" ? "primary" : "ghost"} onPress={() => setRange("today")} />
          <Button title="7 days" kind={range === "week" ? "primary" : "ghost"} onPress={() => setRange("week")} />
          <Button title="This month" kind={range === "month" ? "primary" : "ghost"} onPress={() => setRange("month")} />
        </View>
        <Err msg={err} />

        {pl && (
          <Card>
            <Text style={{ fontWeight: "700", marginBottom: 4 }}>Profit &amp; loss</Text>
            <Row label="Sales (after returns)" value={`₹${pl.net_sales}`} />
            <Row label="Cost of goods sold" value={`₹${pl.cost_of_goods_sold}`} />
            <Row label="Gross profit" value={`₹${pl.gross_profit}`} bold />
            <Row label="Expenses" value={`₹${pl.expenses_total}`} />
            {pl.expenses_by_category.map((e: any) => <Muted key={e.category}>   {e.category}: ₹{e.amount}</Muted>)}
            <Row label="Net profit" value={`₹${pl.net_profit}`} bold />
            <Muted>Collected: {Object.entries(pl.money_collected_by_method).map(([k, v]) => `${k.toUpperCase()} ₹${v}`).join("  ") || "nothing yet"}</Muted>
          </Card>
        )}

        {sa && (
          <>
            <Card>
              <Text style={{ fontWeight: "700", marginBottom: 4 }}>Top sellers</Text>
              {sa.top_sellers.length === 0 && <Muted>No sales in this period.</Muted>}
              {sa.top_sellers.map((p: any) => <Row key={p.product} label={`${p.product} × ${p.quantity}`} value={`₹${p.sales}`} />)}
            </Card>
            <Card>
              <Text style={{ fontWeight: "700", marginBottom: 4 }}>Not selling (in stock, no sales)</Text>
              {sa.slow_movers.length === 0 && <Muted>None.</Muted>}
              {sa.slow_movers.slice(0, 10).map((p: any) => <Row key={p.product} label={`${p.product} (${p.stock})`} value={`₹${p.stock_value_at_cost}`} />)}
            </Card>
          </>
        )}

        {ag && (
          <>
            <Card>
              <Text style={{ fontWeight: "700", marginBottom: 4 }}>Customers owe you: ₹{ag.receivables.total}</Text>
              {Object.entries(ag.receivables.buckets).map(([k, v]) => <Row key={k} label={k} value={`₹${v}`} />)}
              {ag.receivables.rows.slice(0, 8).map((r: any) => <Muted key={r.name + r.phone}>{r.name}: ₹{r.balance}</Muted>)}
            </Card>
            <Card>
              <Text style={{ fontWeight: "700", marginBottom: 4 }}>You owe suppliers: ₹{ag.payables.total}</Text>
              {Object.entries(ag.payables.buckets).map(([k, v]) => <Row key={k} label={k} value={`₹${v}`} />)}
              {ag.payables.rows.slice(0, 8).map((r: any) => <Muted key={r.name + r.phone}>{r.name}: ₹{r.balance}</Muted>)}
            </Card>
          </>
        )}
      </ScrollView>
    </Screen>
  );
}