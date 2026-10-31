import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";
import { FlatList, Pressable, ScrollView, Text, View } from "react-native";
import { Button, Card, Chip, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { useCart } from "../../store/cart";
import type { Shop } from "../(tabs)/index";

type Product = { id: number; name: string; category: number | null; category_name: string; unit: string; loose: boolean; selling_price: string; image: string; in_stock: boolean };
type Category = { id: number; name: string; parent: number | null; sort_order: number; product_count: number };
type Page = { count: number; next: string | null; results: Product[] };

const qtyText = (q: number, unit: string) => (unit === "kg" && q < 1 ? `${Math.round(q * 1000)} g` : unit === "l" && q < 1 ? `${Math.round(q * 1000)} ml` : `${q}${unit === "pc" ? "" : " " + unit}`);

export default function ShopScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const cart = useCart();
  const [shop, setShop] = useState<Shop | null>(null);
  const [q, setQ] = useState("");
  const [cats, setCats] = useState<Category[]>([]);
  const [top, setTop] = useState<number | null>(null);
  const [sub, setSub] = useState<number | null>(null);
  const [items, setItems] = useState<Product[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const req = useRef(0);
  const catId = sub ?? top;

  const tops = useMemo(() => cats.filter((c) => c.parent === null && c.product_count + cats.filter((k) => k.parent === c.id).reduce((a, k) => a + k.product_count, 0) > 0), [cats]);
  const subs = useMemo(() => (top ? cats.filter((c) => c.parent === top && c.product_count > 0) : []), [cats, top]);
  const totalOf = (c: Category) => c.product_count + cats.filter((k) => k.parent === c.id).reduce((a, k) => a + k.product_count, 0);

  useFocusEffect(useCallback(() => {
    api<Shop>(`/store/shops/${id}/`).then(setShop).catch((e) => setErr(e.message));
    api<Category[]>(`/store/shops/${id}/categories/`).then(setCats).catch(() => {});
  }, [id]));

  const load = useCallback(async (p: number) => {
    const rid = ++req.current;
    setLoading(true);
    try {
      const r = await api<Page>(`/store/shops/${id}/products/?search=${encodeURIComponent(q)}&page=${p}${catId ? `&category=${catId}` : ""}`);
      if (rid !== req.current) return;
      setItems((prev) => (p === 1 ? r.results : [...prev, ...r.results]));
      setHasMore(!!r.next); setPage(p); setErr("");
    } catch (e: any) { if (rid === req.current) setErr(e.message); }
    finally { if (rid === req.current) setLoading(false); }
  }, [id, q, catId]);

  useFocusEffect(useCallback(() => {
    const t = setTimeout(() => load(1), 300);
    return () => clearTimeout(t);
  }, [load]));

  const cartShop = { id: Number(id), name: shop?.name ?? "Shop" };
  const step = (p: Product) => (p.loose ? 0.25 : 1);
  const change = (p: Product, delta: number) =>
    cart.setQty(cartShop, { id: p.id, name: p.name, price: p.selling_price, unit: p.unit, loose: p.loose }, Math.max(0, cart.qtyOf(p.id) + delta));

  const inBasket = cart.shop?.id === Number(id) ? cart.lines.length : 0;

  return (
    <Screen safeBottom>
      {shop && (
        <Card>
          <Text style={{ fontWeight: "700", fontSize: 16 }}>{shop.name}</Text>
          <Muted>
            {[shop.accepts_delivery ? `Delivery ₹${Number(shop.delivery_fee)}${shop.free_delivery_above ? ` (free above ₹${Number(shop.free_delivery_above)})` : ""}` : "", shop.accepts_pickup ? "Pickup" : ""].filter(Boolean).join(" · ")}
            {Number(shop.min_order) > 0 ? ` · minimum order ₹${Number(shop.min_order)}` : ""}
          </Muted>
          {shop.store_note ? <Muted>{shop.store_note}</Muted> : null}
        </Card>
      )}
      <Input placeholder="Search products" value={q} onChangeText={setQ} />
      {tops.length > 0 && (
        <View style={{ height: 46 }}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ alignItems: "center", height: 46 }}>
            <Chip label="All" active={top === null} onPress={() => { setTop(null); setSub(null); }} />
            {tops.map((c) => <Chip key={c.id} label={`${c.name} (${totalOf(c)})`} active={top === c.id} onPress={() => { setTop(c.id); setSub(null); }} />)}
          </ScrollView>
        </View>
      )}
      {subs.length > 0 && (
        <View style={{ height: 46 }}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ alignItems: "center", height: 46 }}>
            <Chip label="All in this group" active={sub === null} onPress={() => setSub(null)} />
            {subs.map((c) => <Chip key={c.id} label={`${c.name} (${c.product_count})`} active={sub === c.id} onPress={() => setSub(c.id)} />)}
          </ScrollView>
        </View>
      )}
      <Err msg={err} />
      <FlatList
        style={{ flex: 1 }}
        data={items}
        keyExtractor={(p) => String(p.id)}
        onEndReached={() => { if (hasMore && !loading) load(page + 1); }}
        onEndReachedThreshold={0.5}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={loading ? <Muted>Loading...</Muted> : <Muted>No products found.</Muted>}
        ListFooterComponent={loading && items.length > 0 ? <Muted>Loading more...</Muted> : null}
        renderItem={({ item: p }) => {
          const n = cart.shop?.id === Number(id) ? cart.qtyOf(p.id) : 0;
          return (
            <Card>
              <Text style={{ fontWeight: "600" }}>{p.name}</Text>
              <Muted>{p.category_name ? `${p.category_name} · ` : ""}₹{Number(p.selling_price)}{p.loose ? ` per ${p.unit}` : ""}</Muted>
              {!p.in_stock ? <Text style={{ color: colors.danger }}>Out of stock</Text> : n > 0 ? (
                <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
                  <Button title="−" kind="ghost" onPress={() => change(p, -step(p))} />
                  <Text style={{ fontWeight: "700", minWidth: 70, textAlign: "center" }}>{qtyText(n, p.loose ? p.unit : "pc")}</Text>
                  <Button title="+" kind="ghost" onPress={() => change(p, step(p))} />
                </View>
              ) : <Button title={p.loose ? "Add 250 g / 250 ml" : "Add"} kind="ghost" onPress={() => change(p, step(p))} />}
            </Card>
          );
        }}
      />
      {inBasket > 0 && (
        <Pressable onPress={() => router.navigate("/(tabs)/cart")}
          style={{ backgroundColor: colors.primary, borderRadius: 10, padding: 14, marginTop: 6 }}>
          <Text style={{ color: "#fff", fontWeight: "700", textAlign: "center" }}>View basket ({inBasket} item{inBasket > 1 ? "s" : ""}) · ₹{cart.total.toFixed(2)}</Text>
        </Pressable>
      )}
    </Screen>
  );
}