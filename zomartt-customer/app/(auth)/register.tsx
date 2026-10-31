import { Link } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";
import { Button, Err, Input, Muted, Screen } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

export default function Register() {
  const { signIn } = useSession();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true); setErr("");
    try { await signIn(await api("/store/auth/register/", { body: { name, phone, password } })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Screen>
      <Text style={{ fontSize: 22, fontWeight: "700", marginTop: 50, marginBottom: 12 }}>Create your account</Text>
      <Input placeholder="Your name" value={name} onChangeText={setName} />
      <Input placeholder="Mobile number (10 digits)" keyboardType="phone-pad" value={phone} onChangeText={setPhone} />
      <Input placeholder="Password (at least 6 characters)" secureTextEntry value={password} onChangeText={setPassword} />
      <Muted>The shop sees your name and number only when you place an order with it.</Muted>
      <Err msg={err} />
      <Button title={busy ? "Please wait..." : "Create account"} onPress={submit} disabled={busy || !name || !phone || password.length < 6} />
      <Link href="/(auth)/login" style={{ textAlign: "center", marginTop: 16 }}>I already have an account</Link>
    </Screen>
  );
}