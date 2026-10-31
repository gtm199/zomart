import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, Share, Switch, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";

type Settings = {
  store_enabled: boolean; accepts_delivery: boolean; accepts_pickup: boolean; delivery_fee: string;
  free_delivery_above: string | null; min_order: string; store_note: string; store_code: string; share_text: string;
};

export default function StoreSettings() {
  const router = useRouter();
  const [s, setS] = useState<Settings | null>(null);
  const [fee, setFee] = useState("");
  const [free, setFree] = useState("");
  const [min, setMin] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");

  const fill = (r: Settings) => { setS(r); setFee(r.delivery_fee); setFree(r.free_delivery_above ?? ""); setMin(r.min_order); setNote(r.store_note); };
  useFocusEffect(useCallback(() => { api<Settings>("/shop/store-settings/").then(fill).catch((e) => setErr(e.message)); }, []));

  const save = async (patch: Partial<Settings> = {}) => {
    setErr(""); setOk("");
    try {
      fill(await api<Settings>("/shop/store-settings/", {
        method: "PATCH",
        body: { delivery_fee: fee || "0", free_delivery_above: free === "" ? null : free, min_order: min || "0", store_note: note, ...patch },
      }));
      setOk("Saved.");
    } catch (e: any) { setErr(e.message); }
  };

  if (!s) return <Screen><Err msg={err} /><Muted>Loading...</Muted></Screen>;
  const row = (label: string, value: boolean, key: keyof Settings) => (
    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginVertical: 4 }}>
      <Text>{label}</Text>
      <Switch value={value} onValueChange={(v) => save({ [key]: v } as any)} />
    </View>
  );

  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        <Button title="← Back to menu" kind="ghost" onPress={() => router.navigate("/(shop)/menu")} />
        <Card>
          {row("Accept online orders", s.store_enabled, "store_enabled")}
          {s.store_code ? (
            <>
              <Text style={{ fontSize: 26, fontWeight: "700", color: colors.primary }}>Shop code: {s.store_code}</Text>
              <Muted>Customers type this code in the ordering app. Put it on a sticker at your counter.</Muted>
              <Button title="Share the code (WhatsApp...)" onPress={() => Share.share({ message: s.share_text })} />
            </>
          ) : <Muted>Turn this on to get your shop code.</Muted>}
        </Card>
        <Card>
          {row("Home delivery", s.accepts_delivery, "accepts_delivery")}
          {row("Pickup from the shop", s.accepts_pickup, "accepts_pickup")}
          <Muted>Delivery fee (₹)</Muted>
          <Input keyboardType="decimal-pad" value={fee} onChangeText={setFee} />
          <Muted>Free delivery when the order is at least (₹, blank = never free)</Muted>
          <Input keyboardType="decimal-pad" value={free} onChangeText={setFree} />
          <Muted>Smallest order you accept (₹)</Muted>
          <Input keyboardType="decimal-pad" value={min} onChangeText={setMin} />
          <Muted>Note for customers (opening hours, delivery area)</Muted>
          <Input value={note} onChangeText={setNote} maxLength={255} />
          <Err msg={err} />
          {ok ? <Text style={{ color: colors.primary }}>{ok}</Text> : null}
          <Button title="Save" onPress={() => save()} />
        </Card>
        <Muted>Customers see only products that are in stock, switched on, and shown online. Hide a product from the customer app in My Stock, using Edit.</Muted>
      </ScrollView>
    </Screen>
  );
}