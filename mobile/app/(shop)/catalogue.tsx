import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { FlatList, Text } from "react-native";
import { Button, Card, Err, Input, Muted, Screen } from "../../components/ui";
import { api } from "../../services/api";
import { Master } from "../../types";

type PageResp = { count: number; next: string | null; results: Master[] };

export default function Catalogue() {
  const [q, setQ] = useState("");
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

  const load = useCallback(async (p: number, term: string) => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const r = await api<PageResp>(`/catalog/products/?search=${encodeURIComponent(term)}&page=${p}`);
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

  // Runs when the screen opens and whenever the search text changes (after a short pause while typing).
  useFocusEffect(
    useCallback(() => {
      const t = setTimeout(() => load(1, q), 300);
      return () => clearTimeout(t);
    }, [q, load])
  );

  const loadMore = () => {
    if (hasMore && !loading) load(page + 1, q);
  };

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

  return (
    <Screen>
      <Input placeholder="Search central catalogue" value={q} onChangeText={setQ} />
      {count > 0 && <Muted>Showing {items.length} of {count} products</Muted>}
      <Err msg={err} />
      <FlatList
        data={items}
        keyExtractor={(m) => String(m.id)}
        onEndReached={loadMore}
        onEndReachedThreshold={0.5}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={
          loading ? <Muted>Loading...</Muted> : q ? <Button title={`Can't find "${q}"? Suggest it`} kind="ghost" onPress={suggest} /> : null
        }
        ListFooterComponent={
          loading && items.length > 0 ? <Muted>Loading more...</Muted>
          : hasMore ? <Button title="Load more" kind="ghost" onPress={loadMore} /> : null
        }
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
                <Button title="Cancel" kind="ghost" onPress={() => setOpen(null)} />
              </>
            ) : <Button title="Add to my shop" kind="ghost" onPress={() => setOpen(m.id)} />}
          </Card>
        )}
      />
    </Screen>
  );
}