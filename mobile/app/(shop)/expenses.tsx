import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { Page } from "../../types";

type Expense = { id: number; category: string; amount: string; method: string; expense_date: string; note: string; is_voided: boolean };

const QUICK = ["Rent", "Salary", "Electricity", "Transport", "Tea/Snacks", "Other"];
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export default function Expenses() {
  const [items, setItems] = useState<Expense[]>([]);
  const [category, setCategory] = useState("");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<"cash" | "upi">("cash");
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    const now = new Date();
    const from = iso(new Date(now.getFullYear(), now.getMonth(), 1));
    try { setItems((await api<Page<Expense>>(`/shop/expenses/?from=${from}&to=${iso(now)}`)).results); }
    catch (e: any) { setErr(e.message); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const monthTotal = items.filter((e) => !e.is_voided).reduce((a, e) => a + Number(e.amount), 0);

  const add = async () => {
    setErr("");
    try {
      await api("/shop/expenses/", { body: { category, amount, method, note } });
      setCategory(""); setAmount(""); setNote("");
      load();
    } catch (e: any) { setErr(e.message); }
  };
  const voidIt = async (id: number) => {
    try { await api(`/shop/expenses/${id}/void/`, { method: "POST", body: {} }); load(); } catch (e: any) { setErr(e.message); }
  };

  return (
    <Screen>
      <FlatList
        data={items}
        keyExtractor={(e) => String(e.id)}
        ListHeaderComponent={
          <>
            <Card>
              <Text style={{ fontWeight: "700" }}>Add expense</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                {QUICK.map((q) => <Button key={q} title={q} kind={category === q ? "primary" : "ghost"} onPress={() => setCategory(q)} />)}
              </View>
              <Input placeholder="Category (e.g. Rent, Salary)" value={category} onChangeText={setCategory} />
              <Input placeholder="Amount (₹)" keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
              <Input placeholder="Note (optional)" value={note} onChangeText={setNote} />
              <View style={{ flexDirection: "row", gap: 8 }}>
                <Button title="Paid in cash" kind={method === "cash" ? "primary" : "ghost"} onPress={() => setMethod("cash")} />
                <Button title="Paid by UPI" kind={method === "upi" ? "primary" : "ghost"} onPress={() => setMethod("upi")} />
              </View>
              <Err msg={err} />
              <Button title="Save expense" onPress={add} disabled={!category || !amount} />
            </Card>
            <Text style={{ fontWeight: "700", marginTop: 8 }}>This month: ₹{monthTotal.toFixed(2)}</Text>
          </>
        }
        renderItem={({ item: e }) => (
          <Card>
            <Text style={{ fontWeight: "600", textDecorationLine: e.is_voided ? "line-through" : "none" }}>
              {e.category} · ₹{e.amount} ({e.method})
            </Text>
            <Muted>{e.expense_date}{e.note ? ` · ${e.note}` : ""}</Muted>
            {!e.is_voided && <Button title="Void (entered by mistake)" kind="ghost" onPress={() => voidIt(e.id)} />}
          </Card>
        )}
      />
    </Screen>
  );
}