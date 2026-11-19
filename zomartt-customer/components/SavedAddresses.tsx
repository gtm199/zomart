import { useEffect, useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";
import { api } from "../services/api";
import type { Point } from "./LocationPicker";
import { Button, Chip, Err, Input, Muted, colors } from "./ui";

type Saved = { id: number; label: string; address: string; lat: number | null; lng: number | null };
const MAX_SAVED = 10;                       // the server allows 10 per customer
const QUICK_NAMES = ["Home", "Office", "Other"];

/** Delivery address chooser for checkout: pick one of your saved addresses or type a new one (and save it).
 *  Saved addresses carry their map position. Moving the pin on one can update it for every later delivery.
 *  Only an address the customer taps is highlighted. */
export default function SavedAddresses({ address, point, onAddress, onPick, onMatch }: {
  address: string;
  point: Point | null;
  onAddress: (text: string) => void;                       // typing a new address
  onPick: (address: string, point: Point | null) => void;   // a saved address was chosen (or "new": blank)
  onMatch: (id: number | null) => void;                    // the saved address this order uses (same text and pin)
}) {
  const [list, setList] = useState<Saved[]>([]);
  const [picked, setPicked] = useState<number | "new" | null>(null);
  const [label, setLabel] = useState("Home");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = () => api<{ results: Saved[] }>("/store/addresses/").then((r) => { setList(r.results); return r.results; }).catch(() => [] as Saved[]);
  useEffect(() => { load(); }, []);

  const typed = address.trim();
  const pinOf = (a: Saved): Point | null => (a.lat != null && a.lng != null ? { lat: Number(a.lat), lng: Number(a.lng) } : null);
  const samePin = (a: Saved) => {
    const p = pinOf(a);
    return p != null && point != null && Math.abs(p.lat - point.lat) < 1e-6 && Math.abs(p.lng - point.lng) < 1e-6;
  };
  const chosen = typeof picked === "number" ? list.find((a) => a.id === picked && a.address === typed) ?? null : null;
  const sameText = list.find((a) => a.address === typed);
  const exact = list.find((a) => a.address === typed && samePin(a));
  useEffect(() => { onMatch(exact ? exact.id : null); }, [exact?.id]);
  // typing over a chosen address turns it into a new one
  useEffect(() => { if (typeof picked === "number" && !chosen) setPicked("new"); }, [typed]);

  const choose = (a: Saved) => { setErr(""); setMsg(""); setPicked(a.id); onPick(a.address, pinOf(a)); };
  const startNew = () => { setErr(""); setMsg(""); setPicked("new"); onPick("", null); };

  const save = async () => {
    if (!point) return;
    setBusy(true); setErr(""); setMsg("");
    try {
      const made = await api<Saved>("/store/addresses/", { body: { label: label.trim() || "Home", address: typed, lat: point.lat, lng: point.lng } });
      await load();
      setPicked(made.id);
      setMsg(`Saved as "${made.label}".`);
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  };

  const updatePin = async (a: Saved) => {
    if (!point) return;
    setErr(""); setMsg("");
    try {
      await api(`/store/addresses/${a.id}/`, { method: "PATCH", body: { lat: point.lat, lng: point.lng } });
      await load();
      setMsg(`"${a.label}" now uses the new pin.`);
    } catch (e: any) { setErr(e.message); }
  };

  const remove = (a: Saved) => Alert.alert("Remove address?", `Remove "${a.label}" from your saved addresses?`, [
    { text: "Cancel", style: "cancel" },
    { text: "Remove", style: "destructive", onPress: async () => {
      try {
        await api(`/store/addresses/${a.id}/`, { method: "DELETE" });
        if (picked === a.id) setPicked(null);
        await load();
        setMsg(`"${a.label}" removed.`);
      } catch (e: any) { setErr(e.message); }
    } },
  ]);

  const showInput = picked === "new" || picked === null || !chosen;
  const canSave = typed.length >= 8 && !sameText;

  return (
    <View style={{ marginTop: 6 }}>
      {list.length > 0 ? <Muted>Deliver to</Muted> : null}
      {list.map((a) => {
        const on = chosen?.id === a.id;
        return (
          <Pressable key={a.id} onPress={() => choose(a)}
            style={{ flexDirection: "row", gap: 10, padding: 10, marginVertical: 4, borderRadius: 8, borderWidth: on ? 2 : 1,
              borderColor: on ? colors.primary : colors.border, backgroundColor: on ? "#ecfdf5" : "#fff" }}>
            <View style={{ width: 18, height: 18, borderRadius: 9, borderWidth: 2, marginTop: 2, alignItems: "center", justifyContent: "center",
              borderColor: on ? colors.primary : colors.muted }}>
              {on ? <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: colors.primary }} /> : null}
            </View>
            <View style={{ flex: 1 }}>
              <Text style={{ fontWeight: "700", color: colors.text }}>{a.label}</Text>
              <Text style={{ color: colors.text }}>{a.address}</Text>
              {pinOf(a) ? null : <Text style={{ color: "#b45309", fontSize: 12 }}>No map pin yet - set it on the map below</Text>}
              {on ? (
                <View style={{ flexDirection: "row", gap: 14, marginTop: 4 }}>
                  {point && !samePin(a) ? <Text style={{ color: colors.primary, fontWeight: "600" }} onPress={() => updatePin(a)}>Save new pin</Text> : null}
                  <Text style={{ color: colors.danger, fontWeight: "600" }} onPress={() => remove(a)}>Remove</Text>
                </View>
              ) : null}
            </View>
          </Pressable>
        );
      })}
      {list.length > 0 ? (
        <Pressable onPress={startNew}
          style={{ padding: 10, marginVertical: 4, borderRadius: 8, borderWidth: picked === "new" ? 2 : 1, borderStyle: "dashed",
            borderColor: picked === "new" ? colors.primary : colors.border }}>
          <Text style={{ color: colors.primary, fontWeight: "700" }}>＋ New address</Text>
        </Pressable>
      ) : null}

      {showInput ? (
        <Input placeholder="Full delivery address (house, street, landmark)" multiline value={address} onChangeText={onAddress} />
      ) : null}

      {showInput && canSave ? (
        list.length >= MAX_SAVED ? (
          <Muted>You have {MAX_SAVED} saved addresses. Remove one to save this address.</Muted>
        ) : (
          <View style={{ marginTop: 4 }}>
            <Muted>Save this address for next time as</Muted>
            <View style={{ flexDirection: "row", marginVertical: 4 }}>
              {QUICK_NAMES.map((n) => <Chip key={n} label={n} active={label === n} onPress={() => setLabel(n)} />)}
            </View>
            <Input placeholder="Or type a name (Mom's house, Shop...)" value={QUICK_NAMES.includes(label) ? "" : label}
              onChangeText={(v) => setLabel(v || "Home")} maxLength={30} />
            <Button title={busy ? "Saving..." : `Save as "${label.trim() || "Home"}"`} kind="ghost" onPress={save} disabled={!point || busy} />
            {!point ? <Muted>Set the location on the map first, then you can save it.</Muted> : null}
          </View>
        )
      ) : null}
      <Err msg={err} />
      {msg ? <Muted>{msg}</Muted> : null}
    </View>
  );
}
