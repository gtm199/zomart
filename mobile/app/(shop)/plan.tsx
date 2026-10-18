import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Image, Linking, ScrollView, Text, View } from "react-native";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";

type Option = { months: number; amount: string };
type Plan = { id: number; name: string; price_monthly: string; max_products: number | null; max_employees: number | null; options: Option[] };
type Sub = {
  active: boolean; plan: string | null; status: string | null; expires_on: string | null; days_left: number | null;
  write_allowed: boolean; in_grace_period: boolean; grace_days: number;
  payment: { shop_code: string; upi_id: string; payee_name: string; qr_url: string; instructions: string };
  plans: Plan[];
};

export default function PlanScreen() {
  const [sub, setSub] = useState<Sub | null>(null);
  const [pick, setPick] = useState<{ plan: Plan; option: Option } | null>(null);
  const [err, setErr] = useState("");

  useFocusEffect(
    useCallback(() => {
      api<Sub>("/shop/subscription/").then((r) => { setSub(r); setErr(""); }).catch((e) => setErr(e.message));
    }, [])
  );

  const payWithApp = async () => {
    if (!sub || !pick) return;
    const p = sub.payment;
    const url = `upi://pay?pa=${encodeURIComponent(p.upi_id)}&pn=${encodeURIComponent(p.payee_name)}&am=${pick.option.amount}&cu=INR&tn=${encodeURIComponent(p.shop_code)}`;
    try { await Linking.openURL(url); }
    catch { Alert.alert("No UPI app found", "Scan the QR code from another phone, or pay to the UPI id shown."); }
  };

  if (!sub) return <Screen><Err msg={err} /><Muted>Loading...</Muted></Screen>;

  const danger = !sub.write_allowed || (sub.days_left !== null && sub.days_left <= 7);
  return (
    <Screen>
      <ScrollView>
        <Card>
          <Text style={{ fontSize: 18, fontWeight: "700" }}>{sub.plan ?? "No plan"}</Text>
          {sub.expires_on && (
            <Text style={{ color: danger ? colors.danger : colors.text, fontWeight: "700" }}>
              {sub.days_left !== null && sub.days_left >= 0
                ? `Valid until ${sub.expires_on} (${sub.days_left} day(s) left)`
                : `Expired on ${sub.expires_on}`}
            </Text>
          )}
          {!sub.write_allowed && <Text style={{ color: colors.danger }}>Saving changes is switched off until you renew. Your data is safe.</Text>}
          {sub.write_allowed && sub.in_grace_period && <Text style={{ color: colors.danger }}>Grace period: please renew now.</Text>}
        </Card>

        <Text style={{ fontWeight: "700", marginTop: 8 }}>Choose a plan and period</Text>
        {sub.plans.map((p) => (
          <Card key={p.id}>
            <Text style={{ fontWeight: "700" }}>{p.name} · ₹{Number(p.price_monthly)}/month</Text>
            <Muted>
              {p.max_products ? `Up to ${p.max_products} products` : "Unlimited products"} ·{" "}
              {p.max_employees === null ? "unlimited staff" : `${p.max_employees} staff`}
            </Muted>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {p.options.map((o) => (
                <Button key={o.months} kind={pick?.plan.id === p.id && pick.option.months === o.months ? "primary" : "ghost"}
                  title={`${o.months} month${o.months > 1 ? "s" : ""}`} onPress={() => setPick({ plan: p, option: o })} />
              ))}
            </View>
          </Card>
        ))}

        {pick && (
          <Card>
            <Text style={{ fontSize: 13, color: colors.muted }}>{pick.plan.name}, {pick.option.months} month(s). Pay exactly</Text>
            <Text style={{ fontSize: 28, fontWeight: "700" }}>₹{pick.option.amount}</Text>
            <Text style={{ fontWeight: "700", marginTop: 6 }}>Write this in the UPI note: {sub.payment.shop_code}</Text>
            <Muted>The exact amount (with the extra paise) and the code help us find your payment.</Muted>
            {sub.payment.qr_url ? (
              <Image source={{ uri: sub.payment.qr_url }} style={{ width: 220, height: 220, alignSelf: "center", marginVertical: 8 }} resizeMode="contain" />
            ) : null}
            {sub.payment.upi_id ? <Text>UPI id: {sub.payment.upi_id}{sub.payment.payee_name ? ` (${sub.payment.payee_name})` : ""}</Text> : null}
            <Button title="Pay with a UPI app on this phone" onPress={payWithApp} disabled={!sub.payment.upi_id} />
            {sub.payment.instructions ? <Muted>{sub.payment.instructions}</Muted> : null}
            <Muted>After you pay, your plan is switched on once we see the payment in our bank account, usually within one working day.</Muted>
          </Card>
        )}
        <Err msg={err} />
      </ScrollView>
    </Screen>
  );
}