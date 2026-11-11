import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { Linking, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import OsmMap, { MapMarker, MapState } from "../../components/OsmMap";
import { Button, Muted, colors } from "../../components/ui";
import { useTrackSocket } from "../../lib/useTrackSocket";
import { api } from "../../services/api";

type Track = {
  status: string; fulfilment: string; pin: string | null;
  shop: { name: string; phone: string; lat: number | null; lng: number | null };
  destination: { lat: number; lng: number; address: string } | null;
  rider: { name: string; phone: string; lat: number | null; lng: number | null; heading: number | null; updated_at: string | null; arrived: boolean } | null;
  distance_km: number | null; eta_minutes: number | null;
};

const STEPS: [string, string][] = [
  ["placed", "Order placed"], ["accepted", "Accepted"], ["packed", "Packed"], ["out_for_delivery", "On the way"], ["completed", "Delivered"],
];

function headline(t: Track) {
  switch (t.status) {
    case "completed": return "Delivered. Enjoy!";
    case "cancelled": case "rejected": return "This order was not delivered";
    case "placed": return "Waiting for the shop to accept";
    case "accepted": return "The shop is preparing your order";
    case "packed": return "Your order is packed and will leave soon";
    case "out_for_delivery":
      if (t.rider?.arrived) return "Your delivery partner has arrived";
      if (t.rider?.lat != null) return "On the way to you";
      return "Your delivery partner is picking up the order";
    default: return t.status;
  }
}

export default function TrackScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const [t, setT] = useState<Track | null>(null);
  const [err, setErr] = useState("");
  const [socketUp, setSocketUp] = useState(false);
  const tRef = useRef<Track | null>(null);
  tRef.current = t;

  const load = useCallback(async () => {
    try { setT(await api<Track>(`/store/orders/${id}/track/`)); setErr(""); } catch (e: any) { setErr(e.message); }
  }, [id]);

  // The server pushes every move over the live connection. This slow check only covers a lost connection.
  useFocusEffect(useCallback(() => {
    load();
    const timer = setInterval(load, socketUp ? 60000 : 8000);
    return () => clearInterval(timer);
  }, [load, socketUp]));

  useTrackSocket(String(id), (m) => {
    if (m.type === "refresh") { load(); return; }
    if (m.type !== "position") return;
    const prev = tRef.current;
    if (!prev || !prev.rider) { load(); return; }
    setT({
      ...prev,
      eta_minutes: m.eta_minutes ?? prev.eta_minutes,
      distance_km: m.distance_km ?? prev.distance_km,
      rider: { ...prev.rider, lat: m.lat, lng: m.lng, heading: m.heading, updated_at: m.updated_at, arrived: m.arrived },
    });
  }, setSocketUp);

  const markers: MapMarker[] = [];
  if (t && t.shop.lat != null && t.shop.lng != null) markers.push({ id: "shop", lat: t.shop.lat, lng: t.shop.lng, emoji: "🏪", label: t.shop.name });
  if (t?.destination) markers.push({ id: "home", lat: t.destination.lat, lng: t.destination.lng, emoji: "🏠", label: "You" });
  if (t?.rider && t.rider.lat != null && t.rider.lng != null) markers.push({ id: "rider", lat: t.rider.lat, lng: t.rider.lng, emoji: "🛵", smooth: true });
  const rider = markers.find((m) => m.id === "rider");
  const home = markers.find((m) => m.id === "home");
  const state: MapState = {
    markers,
    line: rider && home ? { from: [rider.lat, rider.lng], to: [home.lat, home.lng] } : null,
    fitKey: markers.filter((m) => m.id !== "rider").map((m) => `${m.id}${m.lat}${m.lng}`).join("|") + (rider ? "r" : ""),
    padBottom: 300,
  };

  const stale = t?.rider?.updated_at ? Date.now() - new Date(t.rider.updated_at).getTime() > 60000 : false;
  const stepIndex = t ? STEPS.findIndex(([s]) => s === t.status) : -1;

  return (
    <View style={{ flex: 1 }}>
      <OsmMap state={state} />
      <View style={{ position: "absolute", left: 0, right: 0, bottom: 0, backgroundColor: "#fff", borderTopLeftRadius: 18, borderTopRightRadius: 18,
        padding: 16, paddingBottom: 16 + insets.bottom, elevation: 12 }}>
        {!t ? <Muted>{err || "Loading..."}</Muted> : (
          <>
            <Text style={{ fontSize: 18, fontWeight: "700" }}>{headline(t)}</Text>
            {t.status === "out_for_delivery" && t.eta_minutes != null && (
              <Text style={{ fontSize: 15, color: colors.primary, fontWeight: "700" }}>
                About {t.eta_minutes} min · roughly {t.distance_km} km away
              </Text>
            )}
            {stale && <Muted>Updating the rider's location...</Muted>}
            {socketUp && t.status === "out_for_delivery" && <Muted>● Live</Muted>}
            {t.rider && (
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 6 }}>
                <Text style={{ fontWeight: "600" }}>🛵 {t.rider.name}</Text>
                {t.rider.phone ? <Button title="Call" kind="ghost" onPress={() => Linking.openURL(`tel:${t.rider!.phone}`)} /> : null}
              </View>
            )}
            {t.pin && (
              <View style={{ backgroundColor: "#ecfdf5", borderRadius: 10, padding: 10, marginTop: 6 }}>
                <Text style={{ fontWeight: "700" }}>Delivery PIN: <Text style={{ fontSize: 22, letterSpacing: 6, color: colors.primary }}>{t.pin}</Text></Text>
                <Muted>Tell it to the delivery person only when you receive the order.</Muted>
              </View>
            )}
            <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 10 }}>
              {STEPS.map(([key, label], i) => (
                <View key={key} style={{ alignItems: "center", flex: 1 }}>
                  <View style={{ width: 14, height: 14, borderRadius: 7, backgroundColor: i <= stepIndex ? colors.primary : "#d1d5db" }} />
                  <Text style={{ fontSize: 10, textAlign: "center", marginTop: 3, color: i <= stepIndex ? colors.text : colors.muted }}>{label}</Text>
                </View>
              ))}
            </View>
            {t.shop.phone ? <Button title={`Call ${t.shop.name}`} kind="ghost" onPress={() => Linking.openURL(`tel:${t.shop.phone}`)} /> : null}
          </>
        )}
      </View>
    </View>
  );
}