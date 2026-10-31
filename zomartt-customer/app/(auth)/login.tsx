import { Link } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";
import { Button, Err, Input, Screen } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

export default function Login() {
  const { signIn } = useSession();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true); setErr("");
    try { await signIn(await api("/store/auth/login/", { body: { phone, password } })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Screen>
      <Text style={{ fontSize: 26, fontWeight: "700", marginTop: 70, marginBottom: 16 }}>Kirana Orders</Text>
      <Input placeholder="Mobile number" keyboardType="phone-pad" value={phone} onChangeText={setPhone} />
      <Input placeholder="Password" secureTextEntry value={password} onChangeText={setPassword} />
      <Err msg={err} />
      <Button title={busy ? "Please wait..." : "Sign in"} onPress={submit} disabled={busy || !phone || !password} />
      <Link href="/(auth)/register" style={{ textAlign: "center", marginTop: 16 }}>New here? Create an account</Link>
    </Screen>
  );
}