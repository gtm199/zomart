import { useState } from "react";
import { Text } from "react-native";
import { Button, Err, Input, Muted, Screen } from "../../components/ui";
import { useSession } from "../../store/session";

export default function Login() {
  const { signIn } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true); setErr("");
    try { await signIn(username.trim(), password); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Screen>
      <Text style={{ fontSize: 26, fontWeight: "700", marginTop: 70, marginBottom: 6 }}>Zomartt Delivery</Text>
      <Muted>Sign in with the username and password your shop gave you.</Muted>
      <Input placeholder="Username or mobile number" autoCapitalize="none" autoCorrect={false} value={username} onChangeText={setUsername} />
      <Input placeholder="Password" secureTextEntry value={password} onChangeText={setPassword} />
      <Err msg={err} />
      <Button title={busy ? "Please wait..." : "Sign in"} onPress={submit} disabled={busy || !username || !password} />
    </Screen>
  );
}