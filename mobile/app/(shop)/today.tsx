import { useCallback, useState } from "react";
import { useFocusEffect } from "expo-router";
import { ScrollView, Text } from "react-native";
import { Button, Card, Err, Muted, Screen } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

export default function Today() {
  const { can, signOut, shop } = useSession();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
  useFocusEffect(useCallback(() => {
    if (!can("view_reports")) return;
    api("/shop/reports/daily-summary/").then(setD).catch((e) => setErr(e.message));
  }, []));
  return (
    <Screen>
      <ScrollView>
        <Text style={{ fontSize: 18, fontWeight: "700" }}>{shop?.name}</Text>
        <Muted>Role: {shop?.role}</Muted>
        <Err msg={err} />
        {!can("view_reports") && <Muted>Daily reports are available to owners, managers and accounts staff.</Muted>}
        {d && (
          <Card>
            <Text>Bills: {d.bills}</Text>
            <Text>Sales: ₹{d.sales_total}</Text>
            <Text>Credit given: ₹{d.credit_given}</Text>
            <Text>Customer receipts: ₹{d.customer_receipts}</Text>
            {Object.entries(d.net_collected_by_method).map(([k, v]) => <Text key={k}>{k.toUpperCase()} collected: ₹{String(v)}</Text>)}
            <Text style={{ marginTop: 6 }}>Estimated gross profit: ₹{d.gross_profit_estimate}</Text>
            <Muted>{d.note}</Muted>
          </Card>
        )}
        <Button title="Sign out" kind="danger" onPress={signOut} />
      </ScrollView>
    </Screen>
  );
}
