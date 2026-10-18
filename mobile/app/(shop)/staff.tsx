import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

type Member = { id: number; username: string; full_name: string; phone: string; role: string; is_active: boolean };
const ROLES = [["cashier", "Cashier"], ["manager", "Manager"], ["inventory", "Stock keeper"], ["accounts", "Accounts"]] as const;

export default function Staff() {
  const { can } = useSession();
  const [items, setItems] = useState<Member[]>([]);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<string>("cashier");
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [newPass, setNewPass] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");

  const load = useCallback(async () => {
    try { setItems((await api<{ results: Member[] }>("/shop/members/")).results); } catch (e: any) { setErr(e.message); }
  }, []);
  useFocusEffect(useCallback(() => { if (can("manage_members")) load(); }, [load]));

  if (!can("manage_members")) return <Screen><Muted>Only the shop owner can manage staff.</Muted></Screen>;

  const add = async () => {
    setErr(""); setOk("");
    const digits = phone.replace(/\D/g, "");
    try {
      await api("/shop/members/", { body: { username: digits, password, full_name: name, phone: digits, role } });
      setOk(`${name} can now sign in with the mobile number ${digits} and the password you set.`);
      setName(""); setPhone(""); setPassword("");
      load();
    } catch (e: any) { setErr(e.message); }
  };
  const toggle = async (m: Member) => {
    setErr("");
    try { await api(`/shop/members/${m.id}/`, { method: "PATCH", body: { is_active: !m.is_active } }); load(); } catch (e: any) { setErr(e.message); }
  };
  const reset = async (m: Member) => {
    setErr(""); setOk("");
    try {
      await api(`/shop/members/${m.id}/set-password/`, { body: { password: newPass } });
      setResetFor(null); setNewPass(""); setOk(`New password set for ${m.full_name || m.username}. They were signed out.`);
    } catch (e: any) { setErr(e.message); }
  };

  return (
    <Screen>
      <FlatList
        data={items.filter((m) => m.role !== "owner")}
        keyExtractor={(m) => String(m.id)}
        ListHeaderComponent={
          <Card>
            <Text style={{ fontWeight: "700" }}>Add a staff member</Text>
            <Input placeholder="Name" value={name} onChangeText={setName} />
            <Input placeholder="Mobile number (used to sign in)" keyboardType="phone-pad" value={phone} onChangeText={setPhone} />
            <Input placeholder="Password (at least 8 characters)" secureTextEntry value={password} onChangeText={setPassword} />
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {ROLES.map(([k, label]) => <Button key={k} title={label} kind={role === k ? "primary" : "ghost"} onPress={() => setRole(k)} />)}
            </View>
            <Muted>Cashiers can bill and see customers, but not costs, profit or reports.</Muted>
            <Err msg={err} />
            {ok ? <Text style={{ color: colors.primary }}>{ok}</Text> : null}
            <Button title="Add staff" onPress={add} disabled={!name || phone.replace(/\D/g, "").length < 10 || password.length < 8} />
          </Card>
        }
        ListEmptyComponent={<Muted>No staff added yet.</Muted>}
        renderItem={({ item: m }) => (
          <Card>
            <Text style={{ fontWeight: "600" }}>{m.full_name || m.username}</Text>
            <Muted>{m.role} · {m.phone || m.username}</Muted>
            <Text style={{ color: m.is_active ? colors.primary : colors.danger, fontWeight: "700" }}>{m.is_active ? "Active" : "Switched off"}</Text>
            <Button title={m.is_active ? "Switch off (they leave)" : "Switch on"} kind={m.is_active ? "danger" : "primary"} onPress={() => toggle(m)} />
            {resetFor === m.id ? (
              <>
                <Input placeholder="New password" secureTextEntry value={newPass} onChangeText={setNewPass} />
                <Button title="Set new password" onPress={() => reset(m)} disabled={newPass.length < 8} />
                <Button title="Cancel" kind="ghost" onPress={() => setResetFor(null)} />
              </>
            ) : <Button title="Reset password" kind="ghost" onPress={() => setResetFor(m.id)} />}
          </Card>
        )}
      />
    </Screen>
  );
}