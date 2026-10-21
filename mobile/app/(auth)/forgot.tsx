import { Link, useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";
import { Button, Err, Input, Muted, Screen } from "../../components/ui";
import { api } from "../../services/api";

export default function Forgot() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      await api("/auth/forgot-password/", { body: { email: email.trim() } });
      router.push({ pathname: "/(auth)/reset", params: { email: email.trim() } });
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <Screen>
      <Text style={{ fontSize: 22, fontWeight: "700", marginTop: 40, marginBottom: 8 }}>Forgot password</Text>
      <Muted>Type the email on your account. We will send you a 6-digit code.</Muted>
      <Input placeholder="Email" autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
      <Err msg={err} />
      <Button title={busy ? "Sending..." : "Send me a code"} onPress={submit} disabled={busy || !email.includes("@")} />
      <Muted>No email on your account? Staff members should ask the shop owner to reset the password. Owners can contact us.</Muted>
      <Link href="/(auth)/login" style={{ textAlign: "center", marginTop: 16 }}>Back to sign in</Link>
    </Screen>
  );
}