import { useState } from "react";
import { Text } from "react-native";
import { ResetPasswordForm } from "../components/ResetPasswordForm";
import { Button, Err, Muted, Screen } from "../components/ui";
import { api } from "../services/api";
import { useSession } from "../store/session";

export default function ResetPasswordScreen() {
  const { shopper, signOut } = useSession();
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const email = shopper?.email ?? "";

  const send = async () => {
    setBusy(true); setErr("");
    try {
      await api("/store/auth/forgot-password/", { body: { email } });
      setSent(true);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  if (!email) {
    return (
      <Screen>
        <Text style={{ fontSize: 20, fontWeight: "700", marginTop: 20 }}>Add an email first</Text>
        <Muted>Go back to Account and add your email. The reset code is sent there.</Muted>
      </Screen>
    );
  }

  if (sent) {
    // after the reset every phone is signed out, so "Go to sign in" just clears the session
    return <Screen><ResetPasswordForm email={email} lockEmail onResend={send} onDone={signOut} /></Screen>;
  }

  return (
    <Screen>
      <Text style={{ fontSize: 20, fontWeight: "700", marginTop: 20, marginBottom: 8 }}>Reset password</Text>
      <Muted>We will email a 6-digit code to {email}.</Muted>
      <Err msg={err} />
      <Button title={busy ? "Sending..." : "Send me a code"} onPress={send} disabled={busy} />
    </Screen>
  );
}
