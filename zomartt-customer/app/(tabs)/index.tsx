import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen } from "../../components/ui";
import { api } from "../../services/api";

export type Shop = {
  id: number; name: string; city: string; address: string; phone: string; accepts_delivery: boolean; accepts_pickup: boolean;
  delivery_fee: string; free_delivery_above: string | null; min_order: string; store_note: string;
};

export default function MyShops() {
  const router = useRouter();
  const [mine, setMine] = useState<Shop[]>([]);
  const [code, setCode] = useState("");
  const [search, setSearch] = useState("");
  const [found, setFound] = useState<Shop[]>([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    try { setMine(await api<Shop[]>("/store/my-shops/")); setErr(""); } catch (e: any) { setErr(e.message); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const open = (s: Shop) => router.push({ pathname: "/shop/[id]", params: { id: String(s.id) } });

  const addByCode = async () => {
    setErr(""); setMsg("");
    try {
      const r = await api<Shop[]>(`/store/shops/?code=${encodeURIComponent(code.trim())}`);
      if (r.length === 0) { setErr("No shop has that code. Check it with the shop."); return; }
      await api("/store/my-shops/", { body: { shop: r[0].id } });
      setCode(""); setMsg(`${r[0].name} added.`); load();
    } catch (e: any) { setErr(e.message); }
  };
  const doSearch = async (t: string) => {
    setSearch(t);
    if (t.trim().length < 2) return setFound([]);
    try { setFound(await api<Shop[]>(`/store/shops/?search=${encodeURIComponent(t.trim())}`)); } catch {}
  };
  const add = async (s: Shop) => {
    try { await api("/store/my-shops/", { body: { shop: s.id } }); setFound([]); setSearch(""); load(); } catch (e: any) { setErr(e.message); }
  };

  return (
    <Screen>
      <FlatList
        data={mine}
        keyExtractor={(s) => String(s.id)}
        ListHeaderComponent={
          <>
            <Card>
              <Text style={{ fontWeight: "700" }}>Add a shop</Text>
              <Input placeholder="Shop code (ask your shop)" autoCapitalize="characters" value={code} onChangeText={setCode} />
              <Button title="Add shop by code" onPress={addByCode} disabled={code.trim().length < 4} />
              <Input placeholder="Or search by shop name or town" value={search} onChangeText={doSearch} />
              {found.map((s) => (
                <View key={s.id} style={{ marginTop: 6 }}>
                  <Text style={{ fontWeight: "600" }}>{s.name}</Text>
                  <Muted>{[s.address, s.city].filter(Boolean).join(", ")}</Muted>
                  <Button title="Add" kind="ghost" onPress={() => add(s)} />
                </View>
              ))}
              <Err msg={err} />
              {msg ? <Muted>{msg}</Muted> : null}
            </Card>
            <Text style={{ fontWeight: "700", marginTop: 8 }}>My shops</Text>
          </>
        }
        ListEmptyComponent={<Muted>No shops yet. Add your shop with its code above.</Muted>}
        renderItem={({ item: s }) => (
          <Card>
            <Text style={{ fontWeight: "700", fontSize: 16 }}>{s.name}</Text>
            <Muted>{[s.address, s.city].filter(Boolean).join(", ")}</Muted>
            <Muted>{[s.accepts_delivery ? "Home delivery" : "", s.accepts_pickup ? "Pickup" : ""].filter(Boolean).join(" · ")}</Muted>
            <Button title="Order from this shop" onPress={() => open(s)} />
          </Card>
        )}
      />
    </Screen>
  );
}