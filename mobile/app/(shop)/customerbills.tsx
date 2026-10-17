import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Linking, Text, View } from "react-native";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";

type SaleItem = { id: number; product_name: string; quantity: string; line_total: string };
type Sale = {
  id: number; invoice_number: string; created_at: string; total: string; amount_paid: string;
  amount_due: string; status: string; items: SaleItem[];
};
type LedgerRow = { id: number; entry_type: string; amount: string; balance_after: string; note: string; created_at: string };

const WHEN = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const LABEL: Record<string, string> = {
  credit_sale: "Bill on credit", payment: "Payment received", refund: "Return adjusted", adjustment: "Adjustment",
};

export default function CustomerBills() {
  const router = useRouter();
  const { id, name } = useLocalSearchParams<{ id: string; name: string }>();
  const [tab, setTab] = useState<"bills" | "statement">("bills");
  const [owes, setOwes] = useState("0");
  const [sales, setSales] = useState<Sale[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [ledger, setLedger] = useState<LedgerRow[]>([]);
  const [err, setErr] = useState("");

  const loadPage = useCallback(async (p: number) => {
    try {
      const r = await api<{ results: Sale[]; next: string | null }>(`/shop/sales/?customer=${id}&page=${p}`);
      setSales((prev) => (p === 1 ? r.results : [...prev, ...r.results]));
      setHasMore(!!r.next);
      setPage(p);
    } catch (e: any) {
      setErr(e.message);
    }
  }, [id]);

  const loadAll = useCallback(async () => {
    setErr("");
    try {
      const c = await api<{ balance: string }>(`/shop/customers/${id}/`);
      setOwes(c.balance);
      setLedger(await api<LedgerRow[]>(`/shop/customers/${id}/ledger/`));
    } catch (e: any) {
      setErr(e.message);
    }
    loadPage(1);
  }, [id, loadPage]);

  useFocusEffect(useCallback(() => { loadAll(); }, [loadAll]));

  const sendBill = async (saleId: number) => {
    setErr("");
    try {
      const rec = await api<{ whatsapp_url: string }>(`/shop/sales/${saleId}/receipt/`);
      Linking.openURL(rec.whatsapp_url);
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const billedTotal = sales.reduce((a, s) => a + Number(s.total), 0);

  return (
    <Screen>
      <Button title="← Back to customers" kind="ghost" onPress={() => router.navigate("/(shop)/customers")} />
      <Text style={{ fontSize: 18, fontWeight: "700" }}>{name}</Text>
      <Text style={{ color: Number(owes) > 0 ? colors.danger : colors.muted, fontWeight: "700" }}>
        {Number(owes) > 0 ? `Owes ₹${owes}` : "Nothing owed"}
      </Text>
      <Muted>{sales.length} bill(s) loaded · ₹{billedTotal.toFixed(2)} billed</Muted>
      <View style={{ flexDirection: "row", gap: 8 }}>
        <Button title="Bills" kind={tab === "bills" ? "primary" : "ghost"} onPress={() => setTab("bills")} />
        <Button title="Account statement" kind={tab === "statement" ? "primary" : "ghost"} onPress={() => setTab("statement")} />
      </View>
      <Err msg={err} />

      {tab === "bills" ? (
        <FlatList
          data={sales}
          keyExtractor={(s) => String(s.id)}
          ListEmptyComponent={<Muted>No bills yet for this customer. Select the customer while billing to see bills here.</Muted>}
          ListFooterComponent={hasMore ? <Button title="Load more" kind="ghost" onPress={() => loadPage(page + 1)} /> : null}
          renderItem={({ item: s }) => (
            <Card>
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={{ fontWeight: "700" }}>{s.invoice_number}</Text>
                <Text style={{ fontWeight: "700" }}>₹{s.total}</Text>
              </View>
              <Muted>{WHEN(s.created_at)}{s.status !== "completed" ? ` · ${s.status.replace("_", " ")}` : ""}</Muted>
              {s.items.map((i) => (
                <Text key={i.id}>{i.product_name} × {Number(i.quantity)} = ₹{i.line_total}</Text>
              ))}
              <Text>Paid ₹{s.amount_paid}</Text>
              {Number(s.amount_due) > 0 && <Text style={{ color: colors.danger, fontWeight: "700" }}>Credit given ₹{s.amount_due}</Text>}
              <Button title="Send bill on WhatsApp" kind="ghost" onPress={() => sendBill(s.id)} />
            </Card>
          )}
        />
      ) : (
        <FlatList
          data={ledger}
          keyExtractor={(r) => String(r.id)}
          ListEmptyComponent={<Muted>No credit or payment entries yet.</Muted>}
          renderItem={({ item: r }) => {
            const up = Number(r.amount) > 0;
            return (
              <Card>
                <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                  <Text style={{ fontWeight: "600" }}>{LABEL[r.entry_type] ?? r.entry_type}</Text>
                  <Text style={{ color: up ? colors.danger : colors.primary, fontWeight: "700" }}>
                    {up ? "+" : "−"}₹{Math.abs(Number(r.amount)).toFixed(2)}
                  </Text>
                </View>
                <Muted>{WHEN(r.created_at)}{r.note ? ` · ${r.note}` : ""}</Muted>
                <Muted>Balance after: ₹{r.balance_after}</Muted>
              </Card>
            );
          }}
        />
      )}
    </Screen>
  );
}