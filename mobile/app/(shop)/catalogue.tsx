import { useEffect, useState } from "react";
import { FlatList, Text } from "react-native";
import { Button, Card, Err, Input, Muted, Screen } from "../../components/ui";
import { api } from "../../services/api";
import { Master, Page } from "../../types";

export default function Catalogue() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Master[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [stock, setStock] = useState("");
  const [err, setErr] = useState("");

  const load = async (t: string) => {
    try { setItems((await api<Page<Master>>(`/catalog/products/?search=${encodeURIComponent(t)}`)).results); } catch (e: any) { setErr(e.message); }
  };
  useEffect(() => { load(""); }, []);

  const add = async (m: Master) => {
    setErr("");
    try {
      await api("/shop/products/", { body: { master_product: m.id, selling_price: price, purchase_cost: cost || "0", opening_stock: stock || "0" } });
      setOpen(null); setPrice(""); setCost(""); setStock(""); load(q);
    } catch (e: any) { setErr(e.message); }
  };
  const suggest = async () => {
    try { await api("/shop/product-suggestions/", { body: { name: q, pack_size: "1", unit: "pc" } }); setErr("Suggestion sent to the catalogue team."); }
    catch (e: any) { setErr(e.message); }
  };

  return (
    <Screen>
      <Input placeholder="Search central catalogue" value={q} onChangeText={(t) => { setQ(t); load(t); }} />
      <Err msg={err} />
      <FlatList data={items} keyExtractor={(m) => String(m.id)}
        ListEmptyComponent={q ? <Button title={`Can't find "${q}"? Suggest it`} kind="ghost" onPress={suggest} /> : null}
        renderItem={({ item: m }) => (
          <Card>
            <Text style={{ fontWeight: "600" }}>{m.display_name}</Text>
            <Muted>MRP {m.mrp ?? "n/a"}</Muted>
            {m.my_listing_id ? <Muted>✓ In your shop</Muted> : open === m.id ? (
              <>
                <Input placeholder="Selling price" keyboardType="decimal-pad" value={price} onChangeText={setPrice} />
                <Input placeholder="Purchase cost" keyboardType="decimal-pad" value={cost} onChangeText={setCost} />
                <Input placeholder="Opening stock" keyboardType="decimal-pad" value={stock} onChangeText={setStock} />
                <Button title="Add to my shop" onPress={() => add(m)} disabled={!price} />
              </>
            ) : <Button title="Add to my shop" kind="ghost" onPress={() => setOpen(m.id)} />}
          </Card>
        )} />
    </Screen>
  );
}
