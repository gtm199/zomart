import { Link, useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";
import { Button, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";

export default function Reset() {
  const router = useRouter();
  const params = useLocalSearchParams<{ email?: string }>();
  const [email, setEmail] = useState(params.email ?? "");
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [again, setAgain] = useState("");
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);

  const submit = async () => {
    setErr("");
    if (pw !== again) { setErr("The two passwords are not the same."); return; }
    try {
      await api("/auth/reset-password/", { body: { email: email.trim(), code: code.trim(), new_password: pw } });
      setDone(true);
    } catch (e: any) { setErr(e.message); }
  };

  if (done) {
    return (
      <Screen>
        <Text style={{ fontSize: 22, fontWeight: "700", marginTop: 40, color: colors.primary }}>Password changed</Text>
        <Muted>Sign in with your new password. You were signed out on all other phones.</Muted>
        <Button title="Go to sign in" onPress={() => router.replace("/(auth)/login")} />
      </Screen>
    );
  }

  return (
    <Screen>
      <Text style={{ fontSize: 22, fontWeight: "700", marginTop: 40, marginBottom: 8 }}>Enter the code</Text>
      <Muted>If the email is on an account, a 6-digit code was sent. It works for 15 minutes.</Muted>
      <Input placeholder="Email" autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
      <Input placeholder="6-digit code" keyboardType="number-pad" maxLength={6} value={code} onChangeText={setCode} />
      <Input placeholder="New password (at least 8 characters)" secureTextEntry value={pw} onChangeText={setPw} />
      <Input placeholder="New password again" secureTextEntry value={again} onChangeText={setAgain} />
      <Err msg={err} />
      <Button title="Change password" onPress={submit} disabled={code.length < 6 || pw.length < 8 || !email} />
      <Link href="/(auth)/forgot" style={{ textAlign: "center", marginTop: 16 }}>Send a new code</Link>
    </Screen>
  );
}