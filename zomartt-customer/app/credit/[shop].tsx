import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Linking, ScrollView, Text, View } from "react-native";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";

type CreditRow = {
  shop: number; shop_name: string; shop_phone: string; upi_id: string; status: string;
  limit: string; owed: string; reserved: string; available: string;
};
type Entry = { entry_type: string; amount: string; balance_after: string; note: string; created_at: string };
const KIND: Record<string, string> = { credit_sale: "Bought on credit", payment: "Payment received", return: "Goods returned", refund: "Refund" };

export default function CreditDetail() {
  const { shop } = useLocalSearchParams<{ shop: string }>();
  const [row, setRow] = useState<CreditRow | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const rows = await api<CreditRow[]>("/store/credit/");
      setRow(rows.find((r) => String(r.shop) === shop) ?? null);
      setEntries(await api<Entry[]>(`/store/credit/${shop}/ledger/`));
      setErr("");
    } catch (e: any) { setErr(e.message); }
  }, [shop]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const askAgain = async () => {
    try { await api("/store/credit/request/", { body: { shop: Number(shop) } }); load(); } catch (e: any) { setErr(e.message); }
  };

  const payByUpi = async () => {
    if (!row) return;
    const url = `upi://pay?pa=${encodeURIComponent(row.upi_id)}&pn=${encodeURIComponent(row.shop_name)}&am=${Number(row.owed).toFixed(2)}&cu=INR&tn=${encodeURIComponent("Dues")}`;
    try { await Linking.openURL(url); }
    catch { Alert.alert("No UPI app found", `Pay ₹${row.owed} to ${row.upi_id} from your UPI app, or pay at the shop.`); }
  };

  if (!row) return <Screen><Err msg={err} /><Muted>Loading...</Muted></Screen>;
  const owed = Number(row.owed);
  return (
    <Screen safeBottom>
      <ScrollView>
        <Card>
          <Text style={{ fontWeight: "700", fontSize: 16 }}>{row.shop_name}</Text>
          {row.status === "requested" && <Text>You asked for credit. Waiting for the shop to answer.</Text>}
          {row.status === "declined" && <><Text>The shop did not give you credit.</Text><Button title="Ask again" kind="ghost" onPress={askAgain} /></>}
          {row.status === "suspended" && <Text>The shop has stopped new credit. Please pay what you owe.</Text>}
          {(row.status === "approved" || row.status === "suspended") && (
            <>
              <Text style={{ fontSize: 22, fontWeight: "700", color: owed > 0 ? colors.danger : colors.primary }}>You owe ₹{row.owed}</Text>
              {row.status === "approved" && <Muted>Your limit ₹{row.limit} · left to use ₹{row.available}</Muted>}
              {Number(row.reserved) > 0 && <Muted>₹{row.reserved} more is in orders that are not delivered yet.</Muted>}
            </>
          )}
          {owed > 0 && (
            <>
              {row.upi_id ? <Button title={`Pay ₹${row.owed} by UPI`} onPress={payByUpi} /> : null}
              <Muted>After you pay, the shop updates your account. It can take a little while. You can also pay in cash at the shop{row.shop_phone ? ` (${row.shop_phone})` : ""}.</Muted>
              {row.shop_phone ? <Button title="Call the shop" kind="ghost" onPress={() => Linking.openURL(`tel:${row.shop_phone}`)} /> : null}
            </>
          )}
        </Card>
        <Err msg={err} />
        <Text style={{ fontWeight: "700", marginTop: 8 }}>Account history</Text>
        {entries.length === 0 && <Muted>Nothing yet.</Muted>}
        {entries.map((e, i) => (
          <Card key={i}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={{ fontWeight: "600" }}>{KIND[e.entry_type] ?? e.entry_type.replace("_", " ")}</Text>
              <Text style={{ fontWeight: "700" }}>₹{Math.abs(Number(e.amount)).toFixed(2)}</Text>
            </View>
            <Muted>{new Date(e.created_at).toLocaleString("en-IN")}{e.note ? ` · ${e.note}` : ""}</Muted>
            <Muted>Balance after: ₹{e.balance_after}</Muted>
          </Card>
        ))}
      </ScrollView>
    </Screen>
  );
}