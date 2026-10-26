import { useFocusEffect } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";
import { FlatList, Pressable, ScrollView, Text } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { Master } from "../../types";

type PageResp = { count: number; next: string | null; results: Master[] };
type Category = { id: number; name: string; parent: number | null; sort_order: number; product_count: number };

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={{
        paddingVertical: 8, paddingHorizontal: 14, borderRadius: 18, marginRight: 8, borderWidth: 1,
        borderColor: active ? colors.primary : colors.border, backgroundColor: active ? colors.primary : "#fff",
      }}
    >
      <Text style={{ color: active ? "#fff" : colors.text, fontWeight: active ? "700" : "400" }}>{label}</Text>
    </Pressable>
  );
}

export default function Catalogue() {
  const [q, setQ] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [top, setTop] = useState<number | null>(null);   // chosen main category
  const [sub, setSub] = useState<number | null>(null);   // chosen sub-category
  const [items, setItems] = useState<Master[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [stock, setStock] = useState("");
  const [err, setErr] = useState("");
  const requestId = useRef(0);

  const catId = sub ?? top;

  // ----- categories -----
  const childrenOf = useCallback((id: number) => categories.filter((c) => c.parent === id), [categories]);
  const total = useCallback((c: Category) => c.product_count + childrenOf(c.id).reduce((a, k) => a + k.product_count, 0), [childrenOf]);
  const tops = useMemo(() => categories.filter((c) => c.parent === null && total(c) > 0), [categories, total]);
  const subs = useMemo(() => (top ? childrenOf(top).filter((c) => c.product_count > 0) : []), [top, childrenOf]);

  useFocusEffect(
    useCallback(() => {
      api<Category[]>("/catalog/categories/").then(setCategories).catch(() => {});
    }, [])
  );

  // ----- products -----
  const load = useCallback(async (p: number, term: string, cat: number | null) => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const path = `/catalog/products/?search=${encodeURIComponent(term)}&page=${p}${cat ? `&category=${cat}` : ""}`;
      const r = await api<PageResp>(path);
      if (id !== requestId.current) return; // a newer search started, ignore this late answer
      setItems((prev) => (p === 1 ? r.results : [...prev, ...r.results]));
      setCount(r.count);
      setHasMore(!!r.next);
      setPage(p);
      setErr("");
    } catch (e: any) {
      if (id === requestId.current) setErr(e.message);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  // Runs when the screen opens and whenever the search text or category changes.
  useFocusEffect(
    useCallback(() => {
      const t = setTimeout(() => load(1, q, catId), 300);
      return () => clearTimeout(t);
    }, [q, catId, load])
  );

  const loadMore = () => {
    if (hasMore && !loading) load(page + 1, q, catId);
  };

  const chooseTop = (id: number | null) => { setTop(id); setSub(null); };

  const add = async (m: Master) => {
    setErr("");
    try {
      const sp = await api<{ id: number }>("/shop/products/", {
        body: { master_product: m.id, selling_price: price, purchase_cost: cost || "0", opening_stock: stock || "0" },
      });
      setItems((prev) => prev.map((x) => (x.id === m.id ? { ...x, my_listing_id: sp.id } : x))); // no reload, keep your place
      setOpen(null); setPrice(""); setCost(""); setStock("");
    } catch (e: any) { setErr(e.message); }
  };

  const suggest = async () => {
    try {
      await api("/shop/product-suggestions/", { body: { name: q, pack_size: "1", unit: "pc" } });
      setErr("Suggestion sent to the catalogue team.");
    } catch (e: any) { setErr(e.message); }
  };

  const chosenName = categories.find((c) => c.id === catId)?.name;

  return (
    <Screen>
      <Input placeholder="Search central catalogue" value={q} onChangeText={setQ} />

      {tops.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0, marginVertical: 4 }}>
          <Chip label="All" active={top === null} onPress={() => chooseTop(null)} />
          {tops.map((c) => (
            <Chip key={c.id} label={`${c.name} (${total(c)})`} active={top === c.id} onPress={() => chooseTop(c.id)} />
          ))}
        </ScrollView>
      )}
      {subs.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0, marginBottom: 4 }}>
          <Chip label="All in this group" active={sub === null} onPress={() => setSub(null)} />
          {subs.map((c) => (
            <Chip key={c.id} label={`${c.name} (${c.product_count})`} active={sub === c.id} onPress={() => setSub(c.id)} />
          ))}
        </ScrollView>
      )}

      {count > 0 && <Muted>{chosenName ? `${chosenName}: ` : ""}showing {items.length} of {count} products</Muted>}
      <Err msg={err} />
      <FlatList
        data={items}
        keyExtractor={(m) => String(m.id)}
        onEndReached={loadMore}
        onEndReachedThreshold={0.5}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={
          loading ? <Muted>Loading...</Muted>
          : q ? <Button title={`Can't find "${q}"? Suggest it`} kind="ghost" onPress={suggest} />
          : <Muted>No products here yet.</Muted>
        }
        ListFooterComponent={
          loading && items.length > 0 ? <Muted>Loading more...</Muted>
          : hasMore ? <Button title="Load more" kind="ghost" onPress={loadMore} /> : null
        }
        renderItem={({ item: m }) => (
          <Card>
            <Text style={{ fontWeight: "600" }}>{m.display_name}</Text>
            <Muted>{m.category_name ? `${m.category_name} · ` : ""}MRP {m.mrp ?? "n/a"}</Muted>
            {m.my_listing_id ? <Muted>✓ In your shop</Muted> : open === m.id ? (
              <>
                <Input placeholder="Selling price" keyboardType="decimal-pad" value={price} onChangeText={setPrice} />
                <Input placeholder="Purchase cost" keyboardType="decimal-pad" value={cost} onChangeText={setCost} />
                <Input placeholder="Opening stock" keyboardType="decimal-pad" value={stock} onChangeText={setStock} />
                <Button title="Add to my shop" onPress={() => add(m)} disabled={!price} />
                <Button title="Cancel" kind="ghost" onPress={() => setOpen(null)} />
              </>
            ) : <Button title="Add to my shop" kind="ghost" onPress={() => setOpen(m.id)} />}
          </Card>
        )}
      />
    </Screen>
  );
}