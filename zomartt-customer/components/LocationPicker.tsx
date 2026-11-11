import * as Location from "expo-location";
import { useState } from "react";
import { Modal, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import OsmMap from "./OsmMap";
import { Button, Err, Muted } from "./ui";

export type Point = { lat: number; lng: number };
const DEFAULT: Point = { lat: 26.7855, lng: 79.0215 }; // Etawah

/** A button that opens a full-screen map. The customer taps or drags the pin to the door, or uses their current location. */
export default function LocationPicker({ value, onChange }: { value: Point | null; onChange: (p: Point) => void | Promise<void> }) {
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Point>(value ?? DEFAULT);
  const [recenter, setRecenter] = useState("");
  const [err, setErr] = useState("");

  const goToMe = async () => {
    setErr("");
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (perm.status !== "granted") { setErr("Allow location to find where you are, or move the pin yourself."); return; }
      const p = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      setDraft({ lat: p.coords.latitude, lng: p.coords.longitude });
      setRecenter(String(Date.now()));
    } catch { setErr("Could not get your location. Move the pin to your door."); }
  };

  const show = () => { setDraft(value ?? DEFAULT); setErr(""); setOpen(true); if (!value) setTimeout(goToMe, 700); };

  return (
    <View>
      <Button title={value ? "Change delivery location on the map" : "Set delivery location on the map"} kind={value ? "ghost" : "primary"} onPress={show} />
      <Muted>{value ? `📍 Location saved (${value.lat.toFixed(5)}, ${value.lng.toFixed(5)}). The rider will come here.` : "Needed so the rider can find you and you can track the order."}</Muted>
      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <View style={{ flex: 1 }}>
          <OsmMap state={{ pin: draft, pinMode: true, recenterKey: recenter }} onPin={setDraft} />
          <View style={{ padding: 14, paddingBottom: 14 + insets.bottom, backgroundColor: "#fff" }}>
            <Text style={{ fontWeight: "700" }}>Tap the map or drag the pin to your door</Text>
            <Err msg={err} />
            <Button title="Use my current location" kind="ghost" onPress={goToMe} />
            <Button title="Confirm this location" onPress={async () => { await onChange(draft); setOpen(false); }} />
            <Button title="Cancel" kind="ghost" onPress={() => setOpen(false)} />
          </View>
        </View>
      </Modal>
    </View>
  );
}