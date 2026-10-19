import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Linking, Switch, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { kvGet, kvSet } from "../../services/localdb";
import { reminderText, toCents, waLink } from "../../services/receipt";
import { useSession } from "../../store/session";
import { Customer, Page } from "../../types";

const daysAgo = (iso: string) => Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);

export default function Customers() {
  const router = useRouter();
  const { shop } = useSession();
  const trusted = shop?.role === "owner" || shop?.role === "manager";
  const [q, setQ] = useState("");
  const [owingOnly, setOwingOnly] = useState(false);
  const [items, setItems] = useState<Customer[]>([]);
  const [reminded, setReminded] = useState<Record<number, string>>({});
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [limit, setLimit] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [amount, setAmount] = useState("");
  const [limitFor, setLimitFor] = useState<number | null>(null);
  const [limitValue, setLimitValue] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const path = `/shop/customers/?search=${encodeURIComponent(q)}${owingOnly ? "&owing=true" : ""}`;
      const list = (await api<Page<Customer>>(path)).results;
      setItems(owingOnly ? [...list].sort((a, b) => Number(b.balance) - Number(a.balance)) : list);
      const map: Record<number, string> = {};
      for (const c of list) {
        const when = await kvGet(`reminded_${c.id}`);
        if (when) map[c.id] = when;
      }
      setReminded(map);
      setErr("");
    } catch (e: any) { setErr(e.message); }
  }, [q, owingOnly]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const totalOwed = items.reduce((a, c) => a + Number(c.balance), 0);

  const add = async () => {
    setErr("");
    try {
      const body: Record<string, string> = { name, phone };
      if (trusted && limit.trim() !== "") body.credit_limit = limit.trim();
      await api("/shop/customers/", { body });
      setName(""); setPhone(""); setLimit("");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const receive = async (c: Customer, method: "cash" | "upi") => {
    setErr("");
    try {
      await api(`/shop/customers/${c.id}/receive-payment/`, { body: { amount, method } });
      setOpen(null); setAmount("");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const saveLimit = async (c: Customer) => {
    setErr("");
    try {
      await api(`/shop/customers/${c.id}/`, { method: "PATCH", body: { credit_limit: limitValue.trim() === "" ? null : limitValue.trim() } });
      setLimitFor(null); setLimitValue("");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  /** Opens WhatsApp with the message written. You read it and tap send yourself. */
  const remind = async (c: Customer) => {
    const text = reminderText(shop?.name ?? "our shop", c.name, toCents(c.balance));
    await Linking.openURL(waLink(c.whatsapp_number || c.phone, text));
    const now = new Date().toISOString();
    await kvSet(`reminded_${c.id}`, now);
    setReminded((r) => ({ ...r, [c.id]: now }));
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
        {trusted && <Input placeholder="Credit limit ₹ (optional)" keyboardType="decimal-pad" value={limit} onChangeText={setLimit} />}
        <Button title="Add customer" onPress={add} disabled={!name} />
      </Card>
      <Err msg={err} />

      <FlatList
        data={items}
        keyExtractor={(c) => String(c.id)}
        renderItem={({ item: c }) => {
          const owes = Number(c.balance) > 0;
          const over = owes && c.credit_limit !== null && Number(c.balance) > Number(c.credit_limit);
          return (
            <Card>
              <Text style={{ fontWeight: "600" }}>{c.name}</Text>
              <Muted>{c.phone || "no phone"}</Muted>
              <Text style={{ color: owes ? colors.danger : colors.muted, fontWeight: owes ? "700" : "400" }}>
                {owes ? `Owes ₹${c.balance}` : "Nothing owed"}
              </Text>
              <Muted>
                {c.credit_limit !== null ? `Credit limit ₹${c.credit_limit}` : "No credit limit"}
                {over ? "  ·  OVER LIMIT" : ""}
              </Muted>
              <Button title="View bills" kind="ghost"
                onPress={() => router.push({ pathname: "/(shop)/customerbills", params: { id: String(c.id), name: c.name } })} />

              {owes && (
                <>
                  <Button title="Remind on WhatsApp" kind="ghost" onPress={() => remind(c)} />
                  {reminded[c.id] && <Muted>Last reminded {daysAgo(reminded[c.id]) === 0 ? "today" : `${daysAgo(reminded[c.id])} day(s) ago`}</Muted>}
                  {open === c.id ? (
                    <>
                      <Input placeholder="Amount received" keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
                      <Button title="Received in cash" onPress={() => receive(c, "cash")} disabled={!amount} />
                      <Button title="Received by UPI" kind="ghost" onPress={() => receive(c, "upi")} disabled={!amount} />
                      <Button title="Cancel" kind="ghost" onPress={() => setOpen(null)} />
                    </>
                  ) : <Button title="Receive payment" kind="ghost" onPress={() => setOpen(c.id)} />}
                </>
              )}

              {trusted && (limitFor === c.id ? (
                <>
                  <Input placeholder="New limit ₹ (blank = no limit)" keyboardType="decimal-pad" value={limitValue} onChangeText={setLimitValue} />
                  <Button title="Save limit" onPress={() => saveLimit(c)} />
                  <Button title="Cancel" kind="ghost" onPress={() => setLimitFor(null)} />
                </>
              ) : <Button title="Set credit limit" kind="ghost" onPress={() => { setLimitFor(c.id); setLimitValue(c.credit_limit ?? ""); }} />)}
            </Card>
          );
        }}
      />
    </Screen>
  );
}