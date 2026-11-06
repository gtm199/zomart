import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, Text } from "react-native";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

type CreditRow = { shop: number; shop_name: string; status: string; limit: string; owed: string; available: string };
const STATUS: Record<string, string> = { requested: "Waiting for the shop", approved: "Credit available", declined: "Not given", suspended: "Stopped by the shop" };

export default function Account() {
  const router = useRouter();
  const { shopper, signOut } = useSession();
  const [rows, setRows] = useState<CreditRow[]>([]);
  const [err, setErr] = useState("");

  useFocusEffect(useCallback(() => {
    api<CreditRow[]>("/store/credit/").then((r) => { setRows(r); setErr(""); }).catch((e) => setErr(e.message));
  }, []));

  return (
    <Screen>
      <ScrollView>
        <Card>
          <Text style={{ fontWeight: "700", fontSize: 16 }}>{shopper?.name}</Text>
          <Muted>{shopper?.phone}</Muted>
        </Card>
        <Text style={{ fontWeight: "700", marginTop: 8 }}>My credit (khata)</Text>
        <Err msg={err} />
        {rows.length === 0 && <Muted>No credit yet. At checkout you can ask a shop to let you pay later.</Muted>}
        {rows.map((r) => (
          <Card key={r.shop}>
            <Text style={{ fontWeight: "700" }}>{r.shop_name}</Text>
            <Text style={{ color: r.status === "approved" ? colors.primary : colors.muted, fontWeight: "600" }}>{STATUS[r.status]}</Text>
            {Number(r.owed) > 0 && <Text style={{ color: colors.danger, fontWeight: "700" }}>You owe ₹{r.owed}</Text>}
            {r.status === "approved" && <Muted>Left to use: ₹{r.available} of ₹{r.limit}</Muted>}
            <Button title="See my account" kind="ghost" onPress={() => router.push({ pathname: "/credit/[shop]", params: { shop: String(r.shop) } })} />
          </Card>
        ))}
        <Muted>Shops only see your name and number on the orders you send them.</Muted>
        <Button title="Sign out" kind="danger" onPress={signOut} />
      </ScrollView>
    </Screen>
  );
}