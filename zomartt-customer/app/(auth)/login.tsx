import { Link } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";
import { Button, Err, Input, Screen } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

export default function Login() {
  const { signIn } = useSession();
  const [login, setLogin] = useState("");   // mobile number, username or email
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true); setErr("");
    try { await signIn(await api("/store/auth/login/", { body: { login: login.trim(), password } })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Screen>
      <Text style={{ fontSize: 26, fontWeight: "700", marginTop: 70, marginBottom: 16 }}>Kirana Orders</Text>
      <Input placeholder="Mobile number, username or email" autoCapitalize="none" autoCorrect={false}
        value={login} onChangeText={setLogin} />
      <Input placeholder="Password" secureTextEntry value={password} onChangeText={setPassword} />
      <Err msg={err} />
      <Button title={busy ? "Please wait..." : "Sign in"} onPress={submit} disabled={busy || !login.trim() || !password} />
      <Link href="/(auth)/forgot" style={{ textAlign: "center", marginTop: 16 }}>Forgot password?</Link>
      <Link href="/(auth)/register"style={{ textAlign: "center", marginTop: 16 }}>New here? Create an account</Link>
    </Screen>
  );
}