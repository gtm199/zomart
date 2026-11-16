import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, ScrollView, Switch, Text, View } from "react-native";
import { Button, Card, Err, Input, KeyboardAware, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { GST_DISCLAIMER, GstScheme, STATE_NAMES, gstinError, normalizeGstin } from "../../services/gst";
import { refreshAfterGstChange } from "../../services/sync";
import { useSession } from "../../store/session";

type GstSettings = {
  gst_enabled: boolean; gst_enabled_at: string | null; gstin: string; gst_legal_name: string; gst_trade_name: string;
  gst_address: string; gst_scheme: GstScheme; gst_state_code: string; gstin_check_note: string;
  gst_price_mode: PriceMode; products_count: number; products_tax_on_top: number; mrp_note: string;
};
type PriceMode = "inclusive" | "exclusive";

const MODES: { value: PriceMode; title: string; text: string }[] = [
  { value: "inclusive", title: "Prices include GST", text: "MRP style. A ₹100 price means the customer pays ₹100; the GST is inside it. Usual for kirana shops." },
  { value: "exclusive", title: "GST added on top", text: "A ₹100 price at 5% means the customer pays ₹105. Usual for wholesale and business sales." },
];

const SCHEMES: { value: GstScheme; title: string; text: string }[] = [
  { value: "regular", title: "Regular", text: "You charge GST and issue tax invoices (CGST + SGST shown on the bill)." },
  { value: "composition", title: "Composition", text: "You pay tax on turnover and cannot charge GST. You issue a 'Bill of Supply' with no tax on it." },
];

/** Owner only (manage_gst). Everyone else never sees this screen in the menu, and the server refuses changes. */
export default function GstSettingsScreen() {
  const { can } = useSession();
  const [s, setS] = useState<GstSettings | null>(null);
  const [gstin, setGstin] = useState("");
  const [legal, setLegal] = useState("");
  const [trade, setTrade] = useState("");
  const [address, setAddress] = useState("");
  const [scheme, setScheme] = useState<GstScheme>("regular");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);

  const fill = (r: GstSettings) => {
    setS(r); setGstin(r.gstin); setLegal(r.gst_legal_name); setTrade(r.gst_trade_name); setAddress(r.gst_address);
    setScheme(r.gst_scheme || "regular");
  };
  useFocusEffect(useCallback(() => { api<GstSettings>("/shop/gst/").then(fill).catch((e) => setErr(e.message)); }, []));

  if (!can("manage_gst")) return <Screen><Muted>Only the shop owner can change GST billing.</Muted></Screen>;
  if (!s) return <Screen><Err msg={err} /><Muted>Loading...</Muted></Screen>;

  const typedError = gstin.trim() ? gstinError(gstin, s.gst_state_code) : "";

  const send = async (body: Record<string, unknown>, message: string) => {
    setErr(""); setOk(""); setBusy(true);
    try {
      fill(await api<GstSettings>("/shop/gst/", { method: "PATCH", body }));
      setOk(message);
      refreshAfterGstChange(); // the billing screen picks up the change (also used offline)
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const details = () => ({
    gstin: normalizeGstin(gstin), gst_legal_name: legal.trim(), gst_trade_name: trade.trim(), gst_address: address.trim(),
  });

  const switchOn = () => {
    if (!gstin.trim()) { setErr("Enter your GSTIN first."); return; }
    if (typedError) { setErr(typedError); return; }
    const chosen = SCHEMES.find((x) => x.value === scheme)!;
    // Decision: default is Regular, but the owner must confirm the scheme every time GST is switched on.
    Alert.alert(
      "Confirm your GST scheme",
      `You chose: ${chosen.title}.\n${chosen.text}\n\nBills made from now on will be ${scheme === "composition" ? "bills of supply" : "tax invoices"}. Bills made before today stay as they are.\n\nIs this your registered scheme?`,
      [
        { text: "Go back", style: "cancel" },
        { text: `Yes, ${chosen.title}`, onPress: () => send({ ...details(), gst_enabled: true, gst_scheme: scheme }, "GST billing is on.") },
      ]
    );
  };

  const choosePriceMode = (mode: PriceMode) => {
    const label = MODES.find((m) => m.value === mode)!.title;
    const others = mode === "inclusive" ? s.products_tax_on_top : s.products_count - s.products_tax_on_top;
    const ask = (applyAll: boolean) =>
      send({ gst_price_mode: mode, apply_price_mode_to_all: applyAll },
        applyAll ? `Saved. All ${s.products_count} products: ${label.toLowerCase()}.` : `Saved. New products: ${label.toLowerCase()}.`);
    if (mode === s.gst_price_mode && others === 0) return;
    Alert.alert(
      label,
      `${others} product(s) are set the other way now.

Change only the default for new products, or change all ${s.products_count} products too? Bills already made never change.`,
      [
        { text: "Cancel", style: "cancel" },
        ...(mode !== s.gst_price_mode ? [{ text: "Only new products", onPress: () => ask(false) }] : []),
        { text: "All my products", onPress: () => ask(true) },
      ]
    );
  };

  const switchOff = () =>
    Alert.alert(
      "Switch GST billing off?",
      "New bills will be plain bills without GST. Your GSTIN, GST details, past tax invoices and credit notes are all kept.",
      [{ text: "Keep it on", style: "cancel" }, { text: "Switch off", style: "destructive", onPress: () => send({ gst_enabled: false }, "GST billing is off. Past GST bills are kept.") }]
    );

  const saveDetails = () => {
    if (typedError) { setErr(typedError); return; }
    const body: Record<string, unknown> = details();
    if (s.gst_enabled && scheme !== s.gst_scheme) {
      Alert.alert("Change GST scheme?", `New bills will be ${scheme === "composition" ? "bills of supply (no GST)" : "tax invoices (with GST)"}. Old bills do not change.`, [
        { text: "Cancel", style: "cancel" },
        { text: "Change", onPress: () => send({ ...body, gst_scheme: scheme }, "Saved.") },
      ]);
      return;
    }
    send(body, "Saved.");
  };

  return (
    <Screen>
      <KeyboardAware>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: 24 }}>
          <Card>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 17, fontWeight: "700" }}>GST billing</Text>
                <Muted>{s.gst_enabled
                  ? `On since ${s.gst_enabled_at ? new Date(s.gst_enabled_at).toLocaleDateString("en-IN") : "-"} · ${s.gst_scheme === "composition" ? "Composition (bill of supply)" : "Regular (tax invoice)"}`
                  : "Off: plain bills, no GST on bills."}</Muted>
              </View>
              <Switch value={s.gst_enabled} disabled={busy} onValueChange={(v) => (v ? switchOn() : switchOff())} />
            </View>
          </Card>

          <Card>
            <Text style={{ fontWeight: "700" }}>GSTIN</Text>
            <Input placeholder="15-character GSTIN" autoCapitalize="characters" value={gstin} onChangeText={setGstin} maxLength={20} />
            {typedError ? <Err msg={typedError} /> : gstin.trim() ? <Text style={{ color: colors.primary }}>Format looks right.</Text> : null}
            <Muted>{s.gstin_check_note}</Muted>

            <Text style={{ fontWeight: "700", marginTop: 10 }}>Legal name (as on your GST registration)</Text>
            <Input placeholder="Legal name" value={legal} onChangeText={setLegal} />
            <Text style={{ fontWeight: "700" }}>Trade name (optional)</Text>
            <Input placeholder="Trade name" value={trade} onChangeText={setTrade} />
            <Text style={{ fontWeight: "700" }}>Address printed on invoices</Text>
            <Input placeholder="Shop address" value={address} onChangeText={setAddress} multiline />
            <Muted>State: {STATE_NAMES[s.gst_state_code] ?? s.gst_state_code} (code {s.gst_state_code}) - your place of supply.</Muted>

            <Text style={{ fontWeight: "700", marginTop: 10 }}>GST scheme</Text>
            {SCHEMES.map((x) => (
              <View key={x.value} style={{ marginVertical: 2 }}>
                <Button title={x.title} kind={scheme === x.value ? "primary" : "ghost"} onPress={() => setScheme(x.value)} />
                <Muted>{x.text}</Muted>
              </View>
            ))}
            <Err msg={err} />
            {ok ? <Text style={{ color: colors.primary }}>{ok}</Text> : null}
            <Button title={s.gst_enabled ? "Save GST details" : "Save details (GST stays off)"} onPress={saveDetails} disabled={busy} />
            {!s.gst_enabled && <Button title="Switch GST billing on" kind="ghost" onPress={switchOn} disabled={busy} />}
          </Card>

          {s.gst_scheme !== "composition" && (
            <Card>
              <Text style={{ fontWeight: "700" }}>How your selling prices are entered</Text>
              <Muted>
                Shop default: new products follow it. Each product can still be changed in My Stock.
                Now {s.products_tax_on_top} of {s.products_count} products have GST added on top.
              </Muted>
              {MODES.map((m) => (
                <View key={m.value} style={{ marginVertical: 2 }}>
                  <Button title={m.title} kind={s.gst_price_mode === m.value ? "primary" : "ghost"} disabled={busy}
                    onPress={() => choosePriceMode(m.value)} />
                  <Muted>{m.text}</Muted>
                </View>
              ))}
              <Text style={{ color: "#b45309", marginTop: 4 }}>{s.mrp_note}</Text>
            </Card>
          )}

          <Card>
            <Text style={{ fontWeight: "700" }}>Before you start</Text>
            <Muted>1. Set a GST rate on every product (My Stock, "Needs GST rate"). Products without a rate cannot be billed.</Muted>
            <Muted>2. GST on the delivery fee of online orders is not added in this version. Ask your CA how to treat it.</Muted>
            <Muted>3. {GST_DISCLAIMER}</Muted>
          </Card>
        </ScrollView>
      </KeyboardAware>
    </Screen>
  );
}
