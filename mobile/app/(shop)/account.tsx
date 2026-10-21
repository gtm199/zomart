import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, Text } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

type Profile = { username: string; full_name: string; phone: string; email: string };

export default function Account() {
  const { refresh } = useSession();
  const [p, setP] = useState<Profile | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");

  useFocusEffect(
    useCallback(() => {
      api<Profile>("/auth/profile/").then((r) => { setP(r); setName(r.full_name); setPhone(r.phone); setEmail(r.email); }).catch((e) => setErr(e.message));
    }, [])
  );

  const save = async () => {
    setErr(""); setOk("");
    try {
      const body: Record<string, string> = { full_name: name, phone };
      if (p && email.trim().toLowerCase() !== p.email.toLowerCase()) { body.email = email.trim(); body.current_password = pw; }
      const r = await api<Profile>("/auth/profile/", { method: "PATCH", body });
      setP(r); setPw("");
      setOk("Saved.");
      await refresh().catch(() => {});
    } catch (e: any) { setErr(e.message); }
  };

  if (!p) return <Screen><Err msg={err} /><Muted>Loading...</Muted></Screen>;
  const emailChanged = email.trim().toLowerCase() !== p.email.toLowerCase();
  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        <Card>
          <Text style={{ fontWeight: "700" }}>Sign-in name: {p.username}</Text>
          <Muted>You can sign in with this name or with your email.</Muted>
          <Input placeholder="Your name" value={name} onChangeText={setName} />
          <Input placeholder="Mobile number" keyboardType="phone-pad" value={phone} onChangeText={setPhone} />
          <Input placeholder="Email" autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
          {!p.email && <Text style={{ color: "#b45309" }}>Add an email so you can reset a forgotten password.</Text>}
          {emailChanged && (
            <>
              <Muted>To change your email, type your current password.</Muted>
              <Input placeholder="Current password" secureTextEntry value={pw} onChangeText={setPw} />
            </>
          )}
          <Err msg={err} />
          {ok ? <Text style={{ color: colors.primary }}>{ok}</Text> : null}
          <Button title="Save" onPress={save} disabled={emailChanged && !pw} />
        </Card>
      </ScrollView>
    </Screen>
  );
}