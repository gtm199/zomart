import { useEffect, useState } from "react";
import { ScrollView, View } from "react-native";
import { api } from "../services/api";
import type { Point } from "./LocationPicker";
import { Button, Chip, Err, Input, Muted } from "./ui";

type Saved = { id: number; label: string; address: string; lat: number | null; lng: number | null };

/** Saved addresses carry their map position. Moving the pin on one changes it for every delivery that uses it. */
export default function SavedAddresses({ address, point, onPick, onMatch }: {
  address: string;
  point: Point | null;
  onPick: (address: string, point: Point | null) => void;
  onMatch: (id: number | null) => void;
}) {
  const [list, setList] = useState<Saved[]>([]);
  const [label, setLabel] = useState("Home");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = () => api<{ results: Saved[] }>("/store/addresses/").then((r) => setList(r.results)).catch(() => {});
  useEffect(() => { load(); }, []);

  const typed = address.trim();
  const sameText = list.find((a) => a.address === typed);
  const samePlace = (a: Saved) => a.address === typed && point != null && a.lat != null && a.lng != null
    && Math.abs(a.lat - point.lat) < 1e-6 && Math.abs(a.lng - point.lng) < 1e-6;
  const exact = list.find(samePlace);
  useEffect(() => { onMatch(exact ? exact.id : null); }, [exact?.id]);

  const save = async () => {
    if (!point) return;
    setErr(""); setMsg("");
    try {
      await api("/store/addresses/", { body: { label: label.trim() || "Home", address: typed, lat: point.lat, lng: point.lng } });
      setMsg("Address saved with its map position.");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const updatePin = async () => {
    if (!sameText || !point) return;
    setErr(""); setMsg("");
    try {
      await api(`/store/addresses/${sameText.id}/`, { method: "PATCH", body: { lat: point.lat, lng: point.lng } });
      setMsg("Saved address updated with the new pin.");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const remove = async () => {
    if (!sameText) return;
    try { await api(`/store/addresses/${sameText.id}/`, { method: "DELETE" }); load(); } catch (e: any) { setErr(e.message); }
  };

  return (
    <View>
      {list.length > 0 && (
        <>
          <Muted>Your saved addresses</Muted>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0, marginVertical: 4 }}>
            {list.map((a) => (
              <Chip key={a.id} label={a.label} active={a.address === typed}
                onPress={() => onPick(a.address, a.lat != null && a.lng != null ? { lat: a.lat, lng: a.lng } : null)} />
            ))}
          </ScrollView>
        </>
      )}
      {sameText && point && !exact && <Button title={`Use this new pin for "${sameText.label}"`} kind="ghost" onPress={updatePin} />}
      {sameText && <Button title={`Remove "${sameText.label}"`} kind="ghost" onPress={remove} />}
      {typed.length >= 8 && !sameText && (
        <>
          <Input placeholder="Name for this address (Home, Work...)" value={label} onChangeText={setLabel} maxLength={30} />
          <Button title="Save this address for next time" kind="ghost" onPress={save} disabled={!point} />
          {!point && <Muted>Set the location on the map first, then you can save it.</Muted>}
        </>
      )}
      <Err msg={err} />
      {msg ? <Muted>{msg}</Muted> : null}
    </View>
  );
}