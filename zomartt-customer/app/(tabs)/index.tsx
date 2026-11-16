import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { Alert, FlatList, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";

export type Shop = {
  id: number; name: string; city: string; address: string; phone: string; accepts_delivery: boolean; accepts_pickup: boolean;
  delivery_fee: string; free_delivery_above: string | null; min_order: string; store_note: string;
  online_orders?: boolean;   // false: the shop can be added, but it does not take online orders yet
};

const NOT_ONLINE = "This shop does not take online orders yet. You can keep it in My shops; ordering opens when the shop switches online orders on.";
const takesOrders = (s: Shop) => s.online_orders !== false;
const place = (s: Shop) => [s.address, s.city].filter(Boolean).join(", ");

export default function MyShops() {
  const router = useRouter();
  const [mine, setMine] = useState<Shop[]>([]);
  const [code, setCode] = useState("");
  const [search, setSearch] = useState("");
  const [found, setFound] = useState<Shop[]>([]);
  const [searched, setSearched] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const latest = useRef(0);     // only the newest search may fill the list (answers can come back out of order)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try { setMine(await api<Shop[]>("/store/my-shops/")); setErr(""); } catch (e: any) { setErr(e.message); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const added = new Set(mine.map((s) => s.id));
  const open = (s: Shop) => router.push({ pathname: "/shop/[id]", params: { id: String(s.id) } });

  const addShop = async (s: Shop) => {
    setErr(""); setMsg(""); setBusy(s.id);
    try {
      await api("/store/my-shops/", { body: { shop: s.id } });
      setMsg(`${s.name} added to My shops.${takesOrders(s) ? "" : " It does not take online orders yet."}`);
      await load();
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(null); }
  };

  const addByCode = async () => {
    setErr(""); setMsg("");
    try {
      const r = await api<Shop[]>(`/store/shops/?code=${encodeURIComponent(code.trim())}`);
      if (r.length === 0) { setErr("No shop has that code. Check it with the shop, or search by name below."); return; }
      if (added.has(r[0].id)) { setMsg(`${r[0].name} is already in My shops.`); setCode(""); return; }
      await addShop(r[0]);
      setCode("");
    } catch (e: any) { setErr(e.message); }
  };

  const runSearch = async (t: string) => {
    const ticket = ++latest.current;
    try {
      const r = await api<Shop[]>(`/store/shops/?search=${encodeURIComponent(t)}`);
      if (ticket === latest.current) { setFound(r); setSearched(true); }
    } catch (e: any) { if (ticket === latest.current) setErr(e.message); }
  };
  const onSearch = (t: string) => {
    setSearch(t); setErr("");
    if (timer.current) clearTimeout(timer.current);
    if (t.trim().length < 2) { latest.current++; setFound([]); setSearched(false); return; }
    timer.current = setTimeout(() => runSearch(t.trim()), 300);
  };
  const clearSearch = () => { latest.current++; setSearch(""); setFound([]); setSearched(false); };

  const remove = (s: Shop) => Alert.alert("Remove shop?", `Remove ${s.name} from My shops? Your orders and credit with it stay.`, [
    { text: "Cancel", style: "cancel" },
    { text: "Remove", style: "destructive", onPress: async () => {
      try { await api("/store/my-shops/", { method: "DELETE", body: { shop: s.id } }); setMsg(`${s.name} removed.`); load(); }
      catch (e: any) { setErr(e.message); }
    } },
  ]);

  const askCredit = async (s: Shop) => {
    setErr(""); setMsg("");
    try { await api("/store/credit/request/", { body: { shop: s.id } }); setMsg(`You asked ${s.name} for credit. Watch the Account tab.`); }
    catch (e: any) { setErr(e.message); }
  };

  return (
    <Screen>
      <FlatList
        data={mine}
        keyExtractor={(s) => String(s.id)}
        keyboardShouldPersistTaps="handled"
        ListHeaderComponent={
          <>
            <Card>
              <Text style={{ fontWeight: "700" }}>Add a shop</Text>
              <Muted>You can add as many shops as you like.</Muted>
              <Input placeholder="Shop code (ask your shop)" autoCapitalize="characters" value={code} onChangeText={setCode} />
              <Button title="Add shop by code" onPress={addByCode} disabled={code.trim().length < 4} />
              <Input placeholder="Or search by shop name, town or shop mobile" value={search} onChangeText={onSearch}
                autoCorrect={false} returnKeyType="search" />
              {found.map((s) => (
                <View key={s.id} style={{ marginTop: 6, paddingTop: 6, borderTopWidth: 1, borderTopColor: "#e5e7eb" }}>
                  <Text style={{ fontWeight: "600" }}>{s.name}</Text>
                  {place(s) ? <Muted>{place(s)}</Muted> : null}
                  {s.phone ? <Muted>Shop mobile: {s.phone}</Muted> : null}
                  {!takesOrders(s) ? <Muted>Not taking online orders yet</Muted> : null}
                  {added.has(s.id)
                    ? <Text style={{ color: colors.primary, fontWeight: "600", marginVertical: 6 }}>✓ In My shops</Text>
                    : <Button title={busy === s.id ? "Adding…" : "Add"} kind="ghost" disabled={busy !== null} onPress={() => addShop(s)} />}
                </View>
              ))}
              {searched && found.length === 0 ? <Muted>No shop matches “{search.trim()}”. Try the town or the shop's mobile number.</Muted> : null}
              {search ? <Button title="Clear search" kind="ghost" onPress={clearSearch} /> : null}
              <Err msg={err} />
              {msg ? <Muted>{msg}</Muted> : null}
            </Card>
            <Text style={{ fontWeight: "700", marginTop: 8 }}>My shops ({mine.length})</Text>
          </>
        }
        ListEmptyComponent={<Muted>No shops yet. Add your shop with its code or search for it above.</Muted>}
        renderItem={({ item: s }) => (
          <Card>
            <Text style={{ fontWeight: "700", fontSize: 16 }}>{s.name}</Text>
            {place(s) ? <Muted>{place(s)}</Muted> : null}
            {s.phone ? <Muted>Shop mobile: {s.phone}</Muted> : null}
            {takesOrders(s) ? (
              <>
                <Muted>{[s.accepts_delivery ? "Home delivery" : "", s.accepts_pickup ? "Pickup" : ""].filter(Boolean).join(" · ")}</Muted>
                <Button title="Order from this shop" onPress={() => open(s)} />
                <Button title="Ask for credit (pay later)" kind="ghost" onPress={() => askCredit(s)} />
              </>
            ) : <Muted>{NOT_ONLINE}</Muted>}
            <Button title="Remove from My shops" kind="ghost" onPress={() => remove(s)} />
          </Card>
        )}
      />
    </Screen>
  );
}
