import * as Location from "expo-location";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Linking, Modal, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import OsmMap, { MapMarker } from "../../components/OsmMap";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { api, keep } from "../../services/api";
import { directionsUrl, searchUrl } from "../../services/navigate";
import { startTracking, stopTracking } from "../../services/tracking";
import type { Order } from "../index";

export default function DeliveryScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [o, setO] = useState<Order | null>(null);
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");
  const [askPin, setAskPin] = useState(false);
  const [pin, setPin] = useState("");
  const [pay, setPay] = useState<"cash" | "upi">("cash");

  const load = useCallback(async () => {
    try {
      const r = await api<Order>(`/delivery/orders/${id}/`);
      setO(r); setErr("");
      // the app was closed and reopened in the middle of a trip: start sharing the location again
      if (r.trip_started && (await keep.get("tripOrder")) !== String(id)) {
        const mode = await startTracking(Number(id));
        if (mode === "foreground") setNotice("Location is shared only while this app is open.");
      }
    } catch (e: any) {
      if (e?.status === 404) router.replace("/"); else setErr(e.message);
    }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const hasPos = !!o && o.has_position && o.delivery_lat != null && o.delivery_lng != null;

  const markers: MapMarker[] = [];
  if (o && o.shop_lat != null && o.shop_lng != null) markers.push({ id: "shop", lat: o.shop_lat, lng: o.shop_lng, emoji: "🏪", label: o.shop_name });
  if (o && hasPos) markers.push({ id: "home", lat: o.delivery_lat!, lng: o.delivery_lng!, emoji: "🏠", label: o.customer_name });

  const begin = () =>
    Alert.alert(
      "Share your location?",
      "While this delivery is in progress, Zomartt Delivery collects your location, even when the app is closed or not in use, so the customer can see where you are. Sharing stops when you finish the delivery.",
      [
        { text: "Not now", style: "cancel" },
        {
          text: "Continue",
          onPress: async () => {
            setErr("");
            try {
              const mode = await startTracking(Number(id));
              if (mode === "denied") { setErr("Allow location for this app in your phone settings to start."); return; }
              await api(`/delivery/orders/${id}/start/`, { body: {} });
              setNotice(mode === "background" ? "" : "Location is shared only while this app is open. Keep it open.");
              load();
            } catch (e: any) { setErr(e.message); }
          },
        },
      ]
    );

  const arrived = async () => {
    try { await api(`/delivery/orders/${id}/arrived/`, { body: {} }); load(); } catch (e: any) { setErr(e.message); }
  };

  // The link is built here, each time, from the saved coordinates. Nothing is stored as a link.
  const openNavigation = async () => {
    if (!o || !hasPos) return;
    try { await Linking.openURL(directionsUrl(o.delivery_lat!, o.delivery_lng!)); }
    catch { Alert.alert("Could not open Google Maps", "Install Google Maps, or open the link in a browser."); }
  };

  const findAddress = async () => {
    if (!o) return;
    try { await Linking.openURL(searchUrl(o.delivery_address)); } catch { Alert.alert("Could not open Google Maps"); }
  };

  // First delivery to an address with no pin: save the spot once, standing at the door.
  const savePlace = () =>
    Alert.alert("Save this place?", "Do this only when you are standing at the customer's door. The spot is saved for their next orders.", [
      { text: "Not yet", style: "cancel" },
      {
        text: "Save here",
        onPress: async () => {
          setErr("");
          try {
            const perm = await Location.requestForegroundPermissionsAsync();
            if (perm.status !== "granted") { setErr("Allow location to save this place."); return; }
            const p = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
            setO(await api<Order>(`/delivery/orders/${id}/save-location/`, { body: { lat: p.coords.latitude, lng: p.coords.longitude } }));
            Alert.alert("Saved", "Next time, the Navigate button will take you straight here.");
          } catch (e: any) { setErr(e.message); }
        },
      },
    ]);

  const deliver = async () => {
    setErr("");
    try {
      await api(`/delivery/orders/${id}/deliver/`, { body: { pin, payment_method: pay } });
      await stopTracking();
      setAskPin(false); setPin("");
      Alert.alert("Delivered", "Well done!");
      router.replace("/");
    } catch (e: any) { setErr(e.message); }
  };

  if (!o) return <Screen><Err msg={err} /><Muted>Loading...</Muted></Screen>;

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <View style={{ height: 240 }}>
        <OsmMap state={{ markers, fitKey: markers.map((m) => `${m.id}${m.lat}${m.lng}`).join("|") }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 24 + insets.bottom }}>
        <Card>
          <Text style={{ fontWeight: "700", fontSize: 16 }}>#{o.number} · {o.customer_name}</Text>
          <Text>{o.delivery_address}</Text>
          {o.note ? <Muted>Note: {o.note}</Muted> : null}
          <Text style={{ fontSize: 20, fontWeight: "700", color: colors.primary, marginTop: 6 }}>
            {o.on_credit ? `Collect the delivery fee ₹${o.collect_amount}` : `Collect ₹${o.collect_amount}`}
          </Text>
          {o.on_credit && <Muted>This order is on credit. The items are not paid at the door.</Muted>}
          {o.items.map((i, k) => <Muted key={k}>{i.product_name} × {Number(i.quantity)}{i.unit ? ` ${i.unit}` : ""}</Muted>)}
        </Card>

        <Err msg={err} />
        {notice ? <Muted>{notice}</Muted> : null}

        {!o.trip_started ? (
          <>
            <Button title="Start delivery (share my location)" onPress={begin} />
            <Button title={`Call ${o.shop_name}`} kind="ghost" onPress={() => Linking.openURL(`tel:${o.shop_phone}`)} />
          </>
        ) : (
          <>
            {hasPos ? (
              <Button title="Navigate in Google Maps" onPress={openNavigation} />
            ) : (
              <>
                <Muted>This address has no map position yet.</Muted>
                <Button title="Find the address in Google Maps" onPress={findAddress} />
                <Button title="Save this place (I am at the customer's door)" kind="ghost" onPress={savePlace} />
              </>
            )}
            <Button title="Call customer" kind="ghost" onPress={() => Linking.openURL(`tel:${o.customer_phone}`)} />
            {!o.arrived && <Button title="I have arrived" kind="ghost" onPress={arrived} />}
            <Button title="Delivered: enter the customer's PIN" onPress={() => { setErr(""); setAskPin(true); }} disabled={o.pin_locked} />
            {o.pin_locked && <Text style={{ color: colors.danger }}>Too many wrong PINs. Ask the shop to complete this order.</Text>}
          </>
        )}
      </ScrollView>

      <Modal visible={askPin} transparent animationType="fade" onRequestClose={() => setAskPin(false)}>
        <View style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: 24 }}>
          <View style={{ backgroundColor: "#fff", borderRadius: 14, padding: 16 }}>
            <Text style={{ fontWeight: "700", fontSize: 16 }}>Ask the customer for their PIN</Text>
            <Muted>They can see it in their app. Don't enter the PIN until you have handed over the order.</Muted>
            <TextInput
              value={pin} onChangeText={setPin} keyboardType="number-pad" maxLength={4} autoFocus
              style={{ borderWidth: 1, borderColor: colors.border, borderRadius: 10, fontSize: 30, letterSpacing: 12, textAlign: "center", padding: 10, marginVertical: 10 }}
            />
            {!o.on_credit && (
              <>
                <Muted>How did the customer pay?</Muted>
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <Button title="Cash" kind={pay === "cash" ? "primary" : "ghost"} onPress={() => setPay("cash")} />
                  <Button title="UPI" kind={pay === "upi" ? "primary" : "ghost"} onPress={() => setPay("upi")} />
                </View>
              </>
            )}
            <Err msg={err} />
            <Button title="Complete delivery" onPress={deliver} disabled={pin.length < 4} />
            <Button title="Cancel" kind="ghost" onPress={() => setAskPin(false)} />
          </View>
        </View>
      </Modal>
    </View>
  );
}