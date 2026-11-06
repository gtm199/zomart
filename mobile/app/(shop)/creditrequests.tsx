import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

type Credit = {
  id: number; status: string; requested_at: string; shopper_name: string; shopper_phone: string;
  customer: { id: number; name: string; owed: string; limit: string | null } | null;
  same_phone_customer: { id: number; name: string; owed: string } | null;
};
const LABEL: Record<string, string> = { requested: "Waiting for you", approved: "Has credit", declined: "Declined", suspended: "Credit stopped" };

export default function CreditRequests() {
  const router = useRouter();
  const { shop } = useSession();
  const trusted = shop?.role === "owner" || shop?.role === "manager";
  const [tab, setTab] = useState<"requested" | "approved" | "other">("requested");
  const [rows, setRows] = useState<Credit[]>([]);
  const [limits, setLimits] = useState<Record<number, string>>({});
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try { setRows((await api<{ results: Credit[] }>("/shop/credit-requests/?page_size=200")).results); setErr(""); }
    catch (e: any) { setErr(e.message); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const call = async (c: Credit, action: string, body: object = {}) => {
    setErr("");
    try { await api(`/shop/credit-requests/${c.id}/${action}/`, { body }); load(); }
    catch (e: any) { setErr(e.message); }
  };
  const approve = (c: Credit, customerId: number | null = null) => call(c, "approve", { limit: limits[c.id], customer: customerId });

  const shown = rows.filter((c) => (tab === "other" ? c.status === "declined" || c.status === "suspended" : c.status === tab));
  const waiting = rows.filter((c) => c.status === "requested").length;

  return (
    <Screen>
      <Button title="← Back to menu" kind="ghost" onPress={() => router.navigate("/(shop)/menu")} />
      <View style={{ flexDirection: "row", gap: 8 }}>
        <Button title={`Waiting (${waiting})`} kind={tab === "requested" ? "primary" : "ghost"} onPress={() => setTab("requested")} />
        <Button title="Have credit" kind={tab === "approved" ? "primary" : "ghost"} onPress={() => setTab("approved")} />
        <Button title="Other" kind={tab === "other" ? "primary" : "ghost"} onPress={() => setTab("other")} />
      </View>
      {!trusted && <Muted>Only the owner or a manager can give or change credit. You can see the list.</Muted>}
      <Err msg={err} />
      <FlatList
        data={shown}
        keyExtractor={(c) => String(c.id)}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={<Muted>Nothing here.</Muted>}
        renderItem={({ item: c }) => (
          <Card>
            <Text style={{ fontWeight: "700" }}>{c.shopper_name} · {c.shopper_phone}</Text>
            <Text style={{ color: c.status === "requested" ? colors.danger : colors.text, fontWeight: "600" }}>{LABEL[c.status]}</Text>
            {c.customer && <Muted>Owes ₹{c.customer.owed} · limit {c.customer.limit ? `₹${c.customer.limit}` : "none"}</Muted>}

            {trusted && c.status !== "approved" && (
              <>
                {c.same_phone_customer && (
                  <Text style={{ color: "#b45309" }}>
                    You already have a customer with this number: {c.same_phone_customer.name} (owes ₹{c.same_phone_customer.owed}).
                    Link them only if you have called this number and it is the same person.
                  </Text>
                )}
                <Input placeholder="Credit limit (₹)" keyboardType="decimal-pad" value={limits[c.id] ?? ""} onChangeText={(v) => setLimits({ ...limits, [c.id]: v })} />
                {c.same_phone_customer ? (
                  <>
                    <Button title={`Link to ${c.same_phone_customer.name} and approve`} onPress={() => approve(c, c.same_phone_customer!.id)} disabled={!limits[c.id]} />
                    <Muted>Or approve as a new customer: not possible while that number is in your customer list.</Muted>
                  </>
                ) : <Button title="Approve with this limit" onPress={() => approve(c)} disabled={!limits[c.id]} />}
                {c.status === "requested" && <Button title="Decline" kind="danger" onPress={() => call(c, "decline")} />}
              </>
            )}

            {trusted && c.status === "approved" && (
              <>
                <Input placeholder="New limit (₹)" keyboardType="decimal-pad" value={limits[c.id] ?? ""} onChangeText={(v) => setLimits({ ...limits, [c.id]: v })} />
                <Button title="Change the limit" kind="ghost" onPress={() => approve(c)} disabled={!limits[c.id]} />
                <Button title="Stop new credit" kind="danger" onPress={() => call(c, "suspend")} />
              </>
            )}
          </Card>
        )}
      />
    </Screen>
  );
}