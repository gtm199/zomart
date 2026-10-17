import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Switch, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { Customer, Page } from "../../types";

export default function Customers() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [owingOnly, setOwingOnly] = useState(false);
  const [items, setItems] = useState<Customer[]>([]);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [amount, setAmount] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const path = `/shop/customers/?search=${encodeURIComponent(q)}${owingOnly ? "&owing=true" : ""}`;
      setItems((await api<Page<Customer>>(path)).results);
    } catch (e: any) {
      setErr(e.message);
    }
  }, [q, owingOnly]);

  // Reload every time this screen comes into view (e.g. after a credit bill)
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const totalOwed = items.reduce((a, c) => a + Number(c.balance), 0);

  const add = async () => {
    setErr("");
    try {
      await api("/shop/customers/", { body: { name, phone } });
      setName("");
      setPhone("");
      load();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const receive = async (c: Customer, method: "cash" | "upi") => {
    setErr("");
    try {
      await api(`/shop/customers/${c.id}/receive-payment/`, { body: { amount, method } });
      setOpen(null);
      setAmount("");
      load();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  return (
    <Screen>
      <Input placeholder="Search customers" value={q} onChangeText={setQ} />
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          <Switch value={owingOnly} onValueChange={setOwingOnly} />
          <Text> Owing only</Text>
        </View>
        <Text style={{ fontWeight: "700", color: totalOwed > 0 ? colors.danger : colors.text }}>
          Total to collect ₹{totalOwed.toFixed(2)}
        </Text>
      </View>

      <Card>
        <Input placeholder="New customer name" value={name} onChangeText={setName} />
        <Input placeholder="Mobile (10 digits)" keyboardType="phone-pad" value={phone} onChangeText={setPhone} />
        <Button title="Add customer" onPress={add} disabled={!name} />
      </Card>
      <Err msg={err} />

      <FlatList
        data={items}
        keyExtractor={(c) => String(c.id)}
        renderItem={({ item: c }) => {
          const owes = Number(c.balance) > 0;
          return (
            <Card>
              <Text style={{ fontWeight: "600" }}>{c.name}</Text>
              <Muted>{c.phone || "no phone"}</Muted>
              <Text style={{ color: owes ? colors.danger : colors.muted, fontWeight: owes ? "700" : "400" }}>
                {owes ? `Owes ₹${c.balance}` : "Nothing owed"}
              </Text>
              <Button
                title="View bills"
                kind="ghost"
                onPress={() => router.push({ pathname: "/(shop)/customerbills", params: { id: String(c.id), name: c.name } })}
              />
              {owes &&
                (open === c.id ? (
                  <>
                    <Input placeholder="Amount received" keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
                    <Button title="Received in cash" onPress={() => receive(c, "cash")} disabled={!amount} />
                    <Button title="Received by UPI" kind="ghost" onPress={() => receive(c, "upi")} disabled={!amount} />
                    <Button title="Cancel" kind="ghost" onPress={() => setOpen(null)} />
                  </>
                ) : (
                  <Button title="Receive payment" kind="ghost" onPress={() => setOpen(c.id)} />
                ))}
            </Card>
          );
        }}
      />
    </Screen>
  );
}