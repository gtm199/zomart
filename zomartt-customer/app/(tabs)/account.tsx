import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ScrollView, Text } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { Shopper, useSession } from "../../store/session";

type CreditRow = { shop: number; shop_name: string; status: string; limit: string; owed: string; available: string };
const STATUS: Record<string, string> = { requested: "Waiting for the shop", approved: "Credit available", declined: "Not given", suspended: "Stopped by the shop" };

export default function Account() {
  const router = useRouter();
  const { shopper, signOut, update } = useSession();
  const [rows, setRows] = useState<CreditRow[]>([]);
  const [err, setErr] = useState("");

  const [email, setEmail] = useState(shopper?.email ?? "");
  const [pw, setPw] = useState("");
  const [emailErr, setEmailErr] = useState("");
  const [emailMsg, setEmailMsg] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => { setEmail(shopper?.email ?? ""); }, [shopper?.email]);
  const emailChanged = email.trim().toLowerCase() !== (shopper?.email ?? "").toLowerCase();

  // username: another way to sign in (besides the mobile number and email)
  const [username, setUsername] = useState(shopper?.username ?? "");
  const [userErr, setUserErr] = useState("");
  const [userMsg, setUserMsg] = useState("");
  useEffect(() => { setUsername(shopper?.username ?? ""); }, [shopper?.username]);
  const usernameChanged = username.trim() !== (shopper?.username ?? "");
  const saveUsername = async () => {
    setSaving(true); setUserErr(""); setUserMsg("");
    try {
      const s = await api<Shopper>("/store/auth/profile/", { method: "PATCH", body: { username: username.trim() } });
      await update(s);
      setUserMsg(s.username ? `Saved. You can now sign in with "${s.username}".` : "Username removed. Sign in with your mobile number or email.");
    } catch (e: any) { setUserErr(e.message); } finally { setSaving(false); }
  };

  useFocusEffect(useCallback(() => {
    api<CreditRow[]>("/store/credit/").then((r) => { setRows(r); setErr(""); }).catch((e) => setErr(e.message));
  }, []));

  const saveEmail = async () => {
    setSaving(true); setEmailErr(""); setEmailMsg("");
    try {
      const s = await api<Shopper>("/store/auth/profile/", { method: "PATCH", body: { email: email.trim(), current_password: pw } });
      await update(s);
      setPw("");
      setEmailMsg("Email saved.");
    } catch (e: any) { setEmailErr(e.message); } finally { setSaving(false); }
  };

  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        <Card>
          <Text style={{ fontWeight: "700", fontSize: 16 }}>{shopper?.name}</Text>
          <Muted>{shopper?.phone}</Muted>
        </Card>

        <Card>
          <Text style={{ fontWeight: "700", marginBottom: 4 }}>Username</Text>
          <Muted>Sign in with your mobile number, username or email. 3-30 letters, numbers, dot or underscore, starting with a letter.</Muted>
          <Input placeholder="e.g. anita_22" autoCapitalize="none" autoCorrect={false} value={username} maxLength={30}
            onChangeText={(v) => { setUsername(v); setUserMsg(""); setUserErr(""); }} />
          {usernameChanged && (
            <Button title={saving ? "Saving..." : username.trim() ? "Save username" : "Remove username"} onPress={saveUsername} disabled={saving} />
          )}
          <Err msg={userErr} />
          {!!userMsg && <Text style={{ color: colors.primary }}>{userMsg}</Text>}
        </Card>

        <Card>
          <Text style={{ fontWeight: "700", marginBottom: 4 }}>Email & password</Text>
          {!shopper?.email && <Text style={{ color: "#b45309" }}>Add an email so you can reset a forgotten password.</Text>}
          <Input placeholder="Email" autoCapitalize="none" keyboardType="email-address" value={email}
            onChangeText={(v) => { setEmail(v); setEmailMsg(""); }} />
          {emailChanged && (
            <>
              <Muted>To change your email, type your current password.</Muted>
              <Input placeholder="Current password" secureTextEntry value={pw} onChangeText={setPw} />
              <Button title={saving ? "Saving..." : "Save email"} onPress={saveEmail} disabled={saving || !pw} />
            </>
          )}
          <Err msg={emailErr} />
          {!!emailMsg && <Text style={{ color: colors.primary }}>{emailMsg}</Text>}
          <Button title="Reset password" kind="ghost" onPress={() => router.push("/reset-password")} disabled={!shopper?.email} />
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
