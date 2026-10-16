import { Link } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";
import { Button, Err, Input, Screen } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";
import { Session } from "../../types";

export default function Login() {
  const { signIn } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setErr("");
    try { await signIn(await api<Session>("/auth/login/", { body: { username, password } })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Screen>
      <Text style={{ fontSize: 26, fontWeight: "700", marginTop: 60, marginBottom: 16 }}>Kirana POS</Text>
      <Input placeholder="Username" autoCapitalize="none" value={username} onChangeText={setUsername} />
      <Input placeholder="Password" secureTextEntry value={password} onChangeText={setPassword} />
      <Err msg={err} />
      <Button title={busy ? "Signing in..." : "Sign in"} onPress={submit} disabled={busy} />
      <Link href="/(auth)/register" style={{ textAlign: "center", marginTop: 16 }}>New shop? Register here</Link>
    </Screen>
  );
}
