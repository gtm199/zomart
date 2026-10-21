import { Link } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";
import { Button, Err, Input, Muted, Screen } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";
import { Session } from "../../types";

export default function Register() {
  const { signIn } = useSession();
  const [f, setF] = useState({ shop_name: "", full_name: "", phone: "", email: "", username: "", password: "" });
  const [err, setErr] = useState("");
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  const submit = async () => {
    setErr("");
    try { await signIn(await api<Session>("/auth/register-vendor/", { body: { ...f, city: "Etawah" } })); }
    catch (e: any) { setErr(e.message); }
  };
  return (
    <Screen>
      <Text style={{ fontSize: 22, fontWeight: "700", marginTop: 40, marginBottom: 12 }}>Register your shop</Text>
      <Input placeholder="Shop name" value={f.shop_name} onChangeText={set("shop_name")} />
      <Input placeholder="Your name" value={f.full_name} onChangeText={set("full_name")} />
      <Input placeholder="Mobile number" keyboardType="phone-pad" value={f.phone} onChangeText={set("phone")} />
      <Input placeholder="Email (to reset your password)" autoCapitalize="none" keyboardType="email-address" value={f.email} onChangeText={set("email")} />
      <Muted>Add your email now. Without it, only we can reset a forgotten password.</Muted>
      <Input placeholder="Username" autoCapitalize="none" value={f.username} onChangeText={set("username")} />
      <Input placeholder="Password (min 8 characters)" secureTextEntry value={f.password} onChangeText={set("password")} />
      <Err msg={err} />
      <Button title="Create account" onPress={submit} />
      <Link href="/(auth)/login" style={{ textAlign: "center", marginTop: 16 }}>Back to sign in</Link>
    </Screen>
  );
}