import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, FlatList, Linking, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { ReceiptData, getShopInfo, printReceipt, receiptHtml, shareReceiptPdf, toCents } from "../../services/receipt";
import { fmtQty } from "../../services/units";
import { useSession } from "../../store/session";

type Item = { id: number; product_name: string; quantity: string; unit: string; unit_price: string; line_total: string };
type Sale = {
  id: number; invoice_number: string; created_at: string; total: string; amount_paid: string; amount_due: string;
  status: string; customer_name: string; items: Item[];
};

export default function Bills() {
  const { shop } = useSession();
  const [q, setQ] = useState("");
  const [sales, setSales] = useState<Sale[]>([]);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [phone, setPhone] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async (p: number, term: string) => {
    try {
      const r = await api<{ results: Sale[]; next: string | null }>(`/shop/sales/?search=${encodeURIComponent(term)}&page=${p}`);
      setSales((prev) => (p === 1 ? r.results : [...prev, ...r.results]));
      setMore(!!r.next);
      setPage(p);
      setErr("");
    } catch (e: any) { setErr(e.status === 0 ? "No internet. Past bills are read from the server." : e.message); }
  }, []);
  useFocusEffect(useCallback(() => { load(1, q); }, [load]));

  const dataFor = (s: Sale): ReceiptData => ({
    ref: s.invoice_number, whenISO: s.created_at, customer: s.customer_name || undefined,
    lines: s.items.map((i) => ({ name: i.product_name, qty: Number(i.quantity), unit: i.unit, price: i.unit_price, totalC: toCents(i.line_total) })),
    totalC: toCents(s.total), paidC: toCents(s.amount_paid),
  });
  const htmlFor = async (s: Sale) => receiptHtml(await getShopInfo(shop?.name ?? "Shop"), dataFor(s));
  const fail = (e: any) => Alert.alert("Could not do that", String(e?.message ?? e));

  const sendWhatsApp = async (s: Sale) => {
    try {
      const r = await api<{ whatsapp_url: string }>(`/shop/sales/${s.id}/receipt/?phone=${encodeURIComponent(phone)}`);
      Linking.openURL(r.whatsapp_url);
    } catch (e) { fail(e); }
  };

  return (
    <Screen>
      <Input placeholder="Search by bill number or customer" value={q} onChangeText={setQ} />
      <Button title="Search" onPress={() => load(1, q)} />
      <Err msg={err} />
      <FlatList
        data={sales}
        keyExtractor={(s) => String(s.id)}
        ListEmptyComponent={<Muted>No bills found.</Muted>}
        ListFooterComponent={more ? <Button title="Load more" kind="ghost" onPress={() => load(page + 1, q)} /> : null}
        renderItem={({ item: s }) => (
          <Card>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={{ fontWeight: "700" }}>{s.invoice_number}</Text>
              <Text style={{ fontWeight: "700" }}>₹{s.total}</Text>
            </View>
            <Muted>
              {new Date(s.created_at).toLocaleString("en-IN")}{s.customer_name ? ` · ${s.customer_name}` : ""}
              {s.status !== "completed" ? ` · ${s.status.replace("_", " ")}` : ""}
            </Muted>
            {Number(s.amount_due) > 0 && <Text style={{ color: colors.danger }}>Credit given ₹{s.amount_due}</Text>}
            {open === s.id ? (
              <>
                {s.items.map((i) => (
                  <Text key={i.id}>{i.product_name} × {fmtQty(Number(i.quantity), i.unit)} = ₹{i.line_total}</Text>
                ))}
                <Button title="Share PDF" onPress={async () => shareReceiptPdf(await htmlFor(s)).catch(fail)} />
                <Button title="Print" kind="ghost" onPress={async () => printReceipt(await htmlFor(s)).catch(fail)} />
                <Input placeholder="WhatsApp number (blank = customer's number)" keyboardType="phone-pad" value={phone} onChangeText={setPhone} />
                <Button title="Send on WhatsApp" kind="ghost" onPress={() => sendWhatsApp(s)} />
                <Button title="Close" kind="ghost" onPress={() => setOpen(null)} />
              </>
            ) : <Button title="Open / reprint" kind="ghost" onPress={() => { setOpen(s.id); setPhone(""); }} />}
          </Card>
        )}
      />
    </Screen>
  );
}