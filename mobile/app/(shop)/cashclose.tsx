import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";

export default function CashClose() {
  const [data, setData] = useState<any>(null);
  const [counted, setCounted] = useState("");
  const [opening, setOpening] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try { setData(await api("/shop/cash-close/")); } catch (e: any) { setErr(e.message); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const close = async () => {
    setErr("");
    try {
      const body: any = { counted_cash: counted, note };
      if (opening !== "") body.opening_cash = opening;
      await api("/shop/cash-close/", { body });
      setCounted(""); setOpening(""); setNote("");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const p = data?.position;
  const closed = data?.closed;
  const Row = ({ a, b }: { a: string; b: string }) => (
    <View style={{ flexDirection: "row", justifyContent: "space-between", marginVertical: 2 }}><Text>{a}</Text><Text>{b}</Text></View>
  );

  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        <Err msg={err} />
        {p && (
          <Card>
            <Text style={{ fontWeight: "700", marginBottom: 4 }}>Cash today ({p.date})</Text>
            <Row a="Opening cash (yesterday's count)" b={`₹${p.opening_cash}`} />
            <Row a="+ Cash received (bills, dues, minus refunds)" b={`₹${p.cash_received_net}`} />
            <Row a="− Cash expenses" b={`₹${p.cash_expenses}`} />
            <Row a="− Cash paid to suppliers" b={`₹${p.cash_paid_to_suppliers_net}`} />
            <Text style={{ fontWeight: "700", fontSize: 18, marginTop: 6 }}>Should be in drawer: ₹{p.expected_cash}</Text>
          </Card>
        )}
        {closed ? (
          <Card>
            <Text style={{ fontWeight: "700" }}>Day closed</Text>
            <Text>Counted ₹{closed.counted_cash}</Text>
            <Text style={{ color: Number(closed.difference) === 0 ? colors.primary : colors.danger, fontWeight: "700" }}>
              {Number(closed.difference) === 0 ? "Cash matches." : Number(closed.difference) < 0 ? `Short by ₹${Math.abs(Number(closed.difference)).toFixed(2)}` : `Extra ₹${closed.difference}`}
            </Text>
          </Card>
        ) : (
          <Card>
            <Text style={{ fontWeight: "700" }}>Close the day</Text>
            <Muted>Count the cash in your drawer and enter it.</Muted>
            <Input placeholder="Cash counted (₹)" keyboardType="decimal-pad" value={counted} onChangeText={setCounted} />
            <Input placeholder="Opening cash (only if different)" keyboardType="decimal-pad" value={opening} onChangeText={setOpening} />
            <Input placeholder="Note (optional)" value={note} onChangeText={setNote} />
            <Button title="Close day" onPress={close} disabled={!counted} />
          </Card>
        )}
      </ScrollView>
    </Screen>
  );
}