import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Linking, Text } from "react-native";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { PendingSale, discardSale, kvGet, listAll, retrySale } from "../../services/localdb";
import { waLink } from "../../services/receipt";
import { notifySync, runSync } from "../../services/sync";
import { getShopInfo, receiptHtml, shareReceiptPdf, toCents } from "../../services/receipt";

type Flagged = { id: number; invoice_number: string; total: string; review_note: string; created_at: string };

export default function SyncScreen() {
  const router = useRouter();
  const [rows, setRows] = useState<PendingSale[]>([]);
  const [flagged, setFlagged] = useState<Flagged[]>([]);
  const [lastSync, setLastSync] = useState<string | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setRows(await listAll());
    setLastSync(await kvGet("last_sync"));
    try {
      const r = await api<{ results: Flagged[] }>("/shop/sales/?needs_review=true");
      setFlagged(r.results);
      setErr("");
    } catch (e: any) {
      if (e.status !== 0) setErr(e.message);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const syncNow = async () => { setOnline(await runSync()); await load(); };
  const retry = async (id: string) => { await retrySale(id); notifySync(); await syncNow(); };
  const discard = (id: string) => discardSale(id).then(() => { notifySync(); load(); });

  const label = (r: PendingSale) =>
    r.status === "sent" ? `Uploaded as ${r.invoice}` : r.status === "failed" ? "Needs attention" : r.attempts > 0 ? `Waiting (tried ${r.attempts}x)` : "Waiting to upload";

  return (
    <Screen>
      <Button title="← Back to menu" kind="ghost" onPress={() => router.navigate("/(shop)/menu")} />
      <Muted>Last downloaded from server: {lastSync ? new Date(lastSync).toLocaleString("en-IN") : "never"}</Muted>
      {online === false && <Err msg="No internet. Bills stay safe on this phone and upload later." />}
      <Err msg={err} />
      <Button title="Sync now" onPress={syncNow} />

      <FlatList
        data={rows}
        keyExtractor={(r) => r.txn_id}
        ListHeaderComponent={<Text style={{ fontWeight: "700", marginTop: 8 }}>Bills made on this phone</Text>}
        ListEmptyComponent={<Muted>Nothing waiting.</Muted>}
        ListFooterComponent={
          flagged.length > 0 ? (
            <>
              <Text style={{ fontWeight: "700", marginTop: 16 }}>Uploaded bills to review</Text>
              {flagged.map((f) => (
                <Card key={f.id}>
                  <Text style={{ fontWeight: "600" }}>{f.invoice_number} · ₹{f.total}</Text>
                  <Text style={{ color: "#b45309" }}>{f.review_note}</Text>
                </Card>
              ))}
            </>
          ) : null
        }
        renderItem={({ item: r }) => {
          const s = JSON.parse(r.summary);
          return (
            <Card>
              <Text style={{ fontWeight: "700" }}>{s.ref} · ₹{s.total}{s.customer ? ` · ${s.customer}` : ""}</Text>
              <Muted>{new Date(r.created_at).toLocaleString("en-IN")}</Muted>
              {s.lines.map((l: any, i: number) => <Text key={i}>{l.name} × {l.qty}</Text>)}
              <Text style={{ fontWeight: "700", color: r.status === "failed" ? colors.danger : r.status === "sent" ? colors.primary : "#b45309" }}>
                {label(r)}
              </Text>
              {r.last_error ? <Text style={{ color: colors.danger }}>{r.last_error}</Text> : null}
              <Button title="Send bill on WhatsApp" kind="ghost" onPress={() => Linking.openURL(waLink(s.phone, s.receipt))} />
              <Button title="Share PDF" kind="ghost" onPress={async () => {
                const info = await getShopInfo("");
                shareReceiptPdf(receiptHtml(info, { ref: s.ref, whenISO: r.created_at, customer: s.customer, lines: s.lines, totalC: toCents(s.total), paidC: toCents(s.paid) }));
              }} />
              {r.status === "failed" && (
                <>
                  <Button title="Try again" onPress={() => retry(r.txn_id)} />
                  <Button title="Discard this bill" kind="danger" onPress={() => discard(r.txn_id)} />
                </>
              )}
            </Card>
          );
        }}
      />
    </Screen>
  );
}