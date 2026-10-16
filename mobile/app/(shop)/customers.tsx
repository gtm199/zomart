import { useCallback, useEffect, useState } from "react";
import { FlatList, Text } from "react-native";
import { Button, Card, Err, Input, Muted, Screen } from "../../components/ui";
import { api } from "../../services/api";
import { Customer, Page } from "../../types";

export default function Customers() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Customer[]>([]);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [amount, setAmount] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try { setItems((await api<Page<Customer>>(`/shop/customers/?search=${encodeURIComponent(q)}`)).results); } catch (e: any) { setErr(e.message); }
  }, [q]);
  useEffect(() => { load(); }, [load]);

  const add = async () => {
    setErr("");
    try { await api("/shop/customers/", { body: { name, phone } }); setName(""); setPhone(""); load(); } catch (e: any) { setErr(e.message); }
  };
  const receive = async (c: Customer, method: "cash" | "upi") => {
    setErr("");
    try { await api(`/shop/customers/${c.id}/receive-payment/`, { body: { amount, method } }); setOpen(null); setAmount(""); load(); }
    catch (e: any) { setErr(e.message); }
  };

  return (
    <Screen>
      <Input placeholder="Search customers" value={q} onChangeText={setQ} />
      <Card>
        <Input placeholder="New customer name" value={name} onChangeText={setName} />
        <Input placeholder="Mobile (10 digits)" keyboardType="phone-pad" value={phone} onChangeText={setPhone} />
        <Button title="Add customer" onPress={add} disabled={!name} />
      </Card>
      <Err msg={err} />
      <FlatList data={items} keyExtractor={(c) => String(c.id)} renderItem={({ item: c }) => (
        <Card>
          <Text style={{ fontWeight: "600" }}>{c.name}</Text>
          <Muted>{c.phone || "no phone"} · Owes ₹{c.balance}</Muted>
          {Number(c.balance) > 0 && (open === c.id ? (
            <>
              <Input placeholder="Amount received" keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
              <Button title="Received in cash" onPress={() => receive(c, "cash")} disabled={!amount} />
              <Button title="Received by UPI" kind="ghost" onPress={() => receive(c, "upi")} disabled={!amount} />
            </>
          ) : <Button title="Receive payment" kind="ghost" onPress={() => setOpen(c.id)} />)}
        </Card>
      )} />
    </Screen>
  );
}
