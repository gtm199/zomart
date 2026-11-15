import { useState } from "react";
import { Text } from "react-native";
import { api } from "../services/api";
import { Button, Err, Input, Muted, colors } from "./ui";

type Props = { email: string; lockEmail?: boolean; onResend: () => void; onDone: () => void };

export function ResetPasswordForm({ email: initial, lockEmail, onResend, onDone }: Props) {
  const [email, setEmail] = useState(initial);
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [again, setAgain] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async () => {
    setErr("");
    if (pw !== again) { setErr("The two passwords are not the same."); return; }
    setBusy(true);
    try {
      await api("/store/auth/reset-password/", { body: { email: email.trim(), code: code.trim(), new_password: pw } });
      setDone(true);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  if (done) {
    return (
      <>
        <Text style={{ fontSize: 22, fontWeight: "700", marginTop: 40, color: colors.primary }}>Password changed</Text>
        <Muted>Sign in with your new password. You were signed out on all phones.</Muted>
        <Button title="Go to sign in" onPress={onDone} />
      </>
    );
  }

  return (
    <>
      <Text style={{ fontSize: 22, fontWeight: "700", marginTop: 40, marginBottom: 8 }}>Enter the code</Text>
      <Muted>{lockEmail ? `We sent a 6-digit code to ${email}.` : "If the email is on an account, a 6-digit code was sent."} It works for 15 minutes.</Muted>
      {!lockEmail && (
        <Input placeholder="Email" autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
      )}
      <Input placeholder="6-digit code" keyboardType="number-pad" maxLength={6} value={code} onChangeText={setCode} />
      <Input placeholder="New password (at least 6 characters)" secureTextEntry value={pw} onChangeText={setPw} />
      <Input placeholder="New password again" secureTextEntry value={again} onChangeText={setAgain} />
      <Err msg={err} />
      <Button title={busy ? "Please wait..." : "Change password"} onPress={submit}
        disabled={busy || code.length < 6 || pw.length < 6 || !email} />
      <Text onPress={onResend} style={{ textAlign: "center", marginTop: 16, color: colors.primary }}>Send a new code</Text>
    </>
  );
}
