import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { FlatList, Switch, Text, View } from "react-native";
import CategoryChips, { Category } from "../../components/CategoryChips";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { hsnError } from "../../services/gst";
import { refreshAfterGstChange } from "../../services/sync";
import { ShopProduct } from "../../types";
import ProductImage from "../../components/ProductImage";

const WARN = "#b45309";
type PageResp = { count: number; next: string | null; results: ShopProduct[] };

function expiryLine(sp: ShopProduct) {
  if (!sp.expiry_date) return null;
  if (sp.expiry_status === "expired") return { text: `EXPIRED on ${sp.expiry_date}`, color: colors.danger };
  if (sp.expiry_status === "expiring_soon") return { text: `Expires in ${sp.days_to_expiry} day(s) · ${sp.expiry_date}`, color: WARN };
  return { text: `Expiry ${sp.expiry_date}`, color: colors.muted };
}

export default function Stock() {
  const [q, setQ] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [expiringOnly, setExpiringOnly] = useState(false);
  const [categories, setCategories] = useState<Category[]>([]);
  const [top, setTop] = useState<number | null>(null);   // chosen main category
  const [sub, setSub] = useState<number | null>(null);   // chosen sub-category
  const [items, setItems] = useState<ShopProduct[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [alerts, setAlerts] = useState<{ expired_count: number; expiring_soon_count: number } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [expiry, setExpiry] = useState("");
  const [addQty, setAddQty] = useState("");
  const [err, setErr] = useState("");
  const [online, setOnline] = useState(true);
  // GST (only shown when the shop has GST billing on; the server decides)
  const [gstOn, setGstOn] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [needRateOnly, setNeedRateOnly] = useState(false);
  const [gstRate, setGstRate] = useState("");
  const [hsn, setHsn] = useState("");
  const [inclGst, setInclGst] = useState(true);
  const requestId = useRef(0);

  const catId = sub ?? top; // 0 means "No category"

  const load = useCallback(async (p: number) => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const path = `/shop/products/?search=${encodeURIComponent(q)}&page=${p}${lowOnly ? "&low_stock=true" : ""}${expiringOnly ? "&expiring=true" : ""}${catId !== null ? `&category=${catId}` : ""}${gstOn && needRateOnly ? "&gst_unconfirmed=true" : ""}`;
      const r = await api<PageResp>(path);
      if (id !== requestId.current) return; // a newer search started, ignore this late answer
      setItems((prev) => (p === 1 ? r.results : [...prev, ...r.results]));
      setCount(r.count);
      setHasMore(!!r.next);
      setPage(p);
      setErr("");
      if (p === 1) setAlerts(await api("/shop/products/expiry-alerts/"));
    } catch (e: any) {
      if (id === requestId.current) setErr(e.message);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [q, lowOnly, expiringOnly, catId, gstOn, needRateOnly]);

  // Categories of my own products (reloaded whenever the screen comes into view).
  useFocusEffect(
    useCallback(() => {
      api<Category[]>("/shop/products/categories/").then(setCategories).catch(() => {});
      api<{ gst_enabled: boolean; gst_rate_suggestions: string[] }>("/shop/gst/")
        .then((g) => { setGstOn(g.gst_enabled); setSuggestions(g.gst_rate_suggestions ?? []); })
        .catch(() => {});
    }, [])
  );

  // Runs when the screen opens (also after saving a purchase) and when the search, switches or category change.
  useFocusEffect(
    useCallback(() => {
      const t = setTimeout(() => load(1), 300);
      return () => clearTimeout(t);
    }, [load])
  );

  const loadMore = () => {
    if (hasMore && !loading) load(page + 1);
  };

  const chooseTop = (id: number | null) => { setTop(id); setSub(null); };

  const startEdit = (sp: ShopProduct) => {
    setOpen(sp.id);
    setPrice(sp.selling_price);
    setCost(sp.purchase_cost ?? "");
    setExpiry(sp.expiry_date ?? "");
    setOnline(sp.online_visible !== false);
    setGstRate(sp.gst_rate ?? "");
    setHsn(sp.hsn_code ?? "");
    setInclGst(sp.price_includes_gst !== false);
    setAddQty("");
    setErr("");
  };

  const save = async (sp: ShopProduct) => {
    setErr("");
    if (expiry !== "" && !/^\d{4}-\d{2}-\d{2}$/.test(expiry)) {
      setErr("Write the expiry date as YYYY-MM-DD, for example 2027-03-31.");
      return;
    }
    try {
      //const body: Record<string, string | null> = {};
      const body: Record<string, string | boolean | null> = {};
      if (price && price !== sp.selling_price) body.selling_price = price;
      if (sp.purchase_cost !== undefined && cost && cost !== sp.purchase_cost) body.purchase_cost = cost;
      if (expiry !== (sp.expiry_date ?? "")) body.expiry_date = expiry === "" ? null : expiry;
      if (online !== (sp.online_visible !== false)) body.online_visible = online;
      let gstChanged = false;
      if (sp.gst_rate !== undefined) {   // GST shop: the server sent GST fields
        const bad = hsnError(hsn.trim());
        if (bad) { setErr(bad); return; }
        if (gstRate.trim() !== (sp.gst_rate ?? "")) {
          if (gstRate.trim() !== "" && !(Number(gstRate) >= 0 && Number(gstRate) <= 100)) { setErr("GST rate must be between 0 and 100."); return; }
          body.gst_rate = gstRate.trim() === "" ? null : gstRate.trim();
          gstChanged = true;
        }
        if (hsn.trim() !== (sp.hsn_code ?? "")) body.hsn_code = hsn.trim();
        if (inclGst !== (sp.price_includes_gst !== false)) { body.price_includes_gst = inclGst; gstChanged = true; }
      }
      if (Object.keys(body).length > 0) {
        await api(`/shop/products/${sp.id}/`, { method: "PATCH", body });
      }
      if (addQty) {
        await api(`/shop/products/${sp.id}/adjust-stock/`, { body: { quantity_delta: addQty, movement_type: "purchase" } });
      }
      if (gstChanged) refreshAfterGstChange(); // the billing screen must see the new rate, also offline
      const fresh = await api<ShopProduct>(`/shop/products/${sp.id}/`); // refresh only this product, keep your place in the list
      setItems((prev) => prev.map((x) => (x.id === fresh.id ? fresh : x)));
      setAlerts(await api("/shop/products/expiry-alerts/"));
      setOpen(null);
      setAddQty("");
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const alertCount = (alerts?.expired_count ?? 0) + (alerts?.expiring_soon_count ?? 0);
  const chosenName = categories.find((c) => c.id === catId)?.name;

  return (
    <Screen>
      <Input placeholder="Search my products" value={q} onChangeText={setQ} />
      <CategoryChips categories={categories} top={top} sub={sub} onTop={chooseTop} onSub={setSub} />
      {alertCount > 0 && (
        <Card>
          <Text style={{ color: (alerts?.expired_count ?? 0) > 0 ? colors.danger : WARN, fontWeight: "700" }}>
            {alerts?.expired_count ? `${alerts.expired_count} expired · ` : ""}
            {alerts?.expiring_soon_count ?? 0} expiring within 30 days
          </Text>
        </Card>
      )}
      <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap" }}>
        <Switch value={lowOnly} onValueChange={setLowOnly} />
        <Text> Low stock   </Text>
        <Switch value={expiringOnly} onValueChange={setExpiringOnly} />
        <Text> Expiring soon</Text>
        {gstOn && (
          <>
            <Text>   </Text>
            <Switch value={needRateOnly} onValueChange={setNeedRateOnly} />
            <Text> Needs GST rate</Text>
          </>
        )}
      </View>
      {count > 0 && <Muted>{chosenName ? `${chosenName}: ` : ""}showing {items.length} of {count} products</Muted>}
      <Err msg={err} />
      <FlatList
        style={{ flex: 1 }}
        data={items}
        keyExtractor={(i) => String(i.id)}
        onEndReached={loadMore}
        onEndReachedThreshold={0.5}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={loading ? <Muted>Loading...</Muted> : <Muted>No products found.</Muted>}
        ListFooterComponent={
          loading && items.length > 0 ? <Muted>Loading more...</Muted>
          : hasMore ? <Button title="Load more" kind="ghost" onPress={loadMore} /> : undefined
        }
        renderItem={({ item: sp }) => {
          const ex = expiryLine(sp);
          return (
            <Card>
              <View style={{ flexDirection: "row", gap: 12 }}>
                <ProductImage uri={sp.master_product.thumbnail || sp.master_product.image} fullUri={sp.master_product.image || sp.master_product.thumbnail} name={sp.master_product.display_name} size={64} />
                <View style={{ flex: 1 }}>
                  <Text style={{ fontWeight: "600" }}>{sp.master_product.display_name}</Text>
                  {sp.master_product.category_name ? <Muted>{sp.master_product.category_name}</Muted> : null}
                  <Text style={{ color: sp.is_low_stock ? colors.danger : colors.text }}>
                    Stock {sp.stock_qty}{sp.master_product.is_loose ? ` ${sp.master_product.unit}` : ""} · Sell ₹{sp.selling_price}
                    {sp.purchase_cost !== undefined ? ` · Cost ₹${sp.purchase_cost}` : ""}
                  </Text>
                </View>
              </View>
              {ex && <Text style={{ color: ex.color, fontWeight: sp.expiry_status === "ok" ? "400" : "700" }}>{ex.text}</Text>}
              {!sp.master_active && <Text style={{ color: colors.danger, fontWeight: "700" }}>Removed from catalogue: cannot be sold</Text>}
              {sp.gst_rate !== undefined && (
                sp.gst_rate === null
                  ? <Text style={{ color: WARN, fontWeight: "700" }}>GST rate not set: cannot be billed yet</Text>
                  : <Muted>GST {sp.gst_rate}%{sp.hsn_code ? ` · HSN ${sp.hsn_code}` : ""} · {sp.price_includes_gst === false ? "GST added on top" : "price includes GST"} · customer pays ₹{sp.customer_price}</Muted>
              )}
              {sp.above_mrp && (
                <Text style={{ color: colors.danger, fontWeight: "700" }}>
                  Customer pays ₹{sp.customer_price}, above the MRP ₹{sp.mrp}. Packaged goods cannot be sold above MRP - lower the price or include GST in it.
                </Text>
              )}
              {open === sp.id ? (
                <>
                  <Muted>Selling price (₹)</Muted>
                  <Input keyboardType="decimal-pad" value={price} onChangeText={setPrice} />
                  {sp.purchase_cost !== undefined && (
                    <>
                      <Muted>Cost price (₹)</Muted>
                      <Input keyboardType="decimal-pad" value={cost} onChangeText={setCost} />
                    </>
                  )}
                  <Muted>Expiry date of the stock in hand (YYYY-MM-DD, blank = none)</Muted>
                  <Input placeholder="2027-03-31" value={expiry} onChangeText={setExpiry} />
                  <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                    <Text>Show in the customer ordering app</Text>
                    <Switch value={online} onValueChange={setOnline} />
                  </View>
                  {sp.gst_rate !== undefined && (
                    <>
                      <Muted>GST rate % (you confirm it; blank = not set)</Muted>
                      <Input placeholder="e.g. 5" keyboardType="decimal-pad" value={gstRate} onChangeText={setGstRate} />
                      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                        {suggestions.map((r) => (
                          <Button key={r} title={`${r}%`} kind={gstRate !== "" && Number(gstRate) === Number(r) ? "primary" : "ghost"} onPress={() => setGstRate(r)} />
                        ))}
                      </View>
                      {sp.suggested_gst_rate ? (
                        <Muted>Catalogue suggests {sp.suggested_gst_rate}%{sp.suggested_hsn_code ? `, HSN ${sp.suggested_hsn_code}` : ""}. Check it is right for your product before using it.</Muted>
                      ) : null}
                      {sp.suggested_gst_rate && gstRate === "" ? (
                        <Button title={`Use ${sp.suggested_gst_rate}%${sp.suggested_hsn_code ? ` and HSN ${sp.suggested_hsn_code}` : ""}`} kind="ghost"
                          onPress={() => { setGstRate(sp.suggested_gst_rate ?? ""); if (!hsn && sp.suggested_hsn_code) setHsn(sp.suggested_hsn_code); }} />
                      ) : null}
                      <Muted>HSN code (4, 6 or 8 digits, optional)</Muted>
                      <Input placeholder="e.g. 1006" keyboardType="number-pad" value={hsn} onChangeText={setHsn} />
                      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                        <Text style={{ flex: 1 }}>{inclGst ? "Selling price includes GST (MRP style)" : "GST is added on top of the selling price"}</Text>
                        <Switch value={inclGst} onValueChange={setInclGst} />
                      </View>
                    </>
                  )}
                  <Muted>Stock received (+)</Muted>
                  <Input placeholder="0" keyboardType="decimal-pad" value={addQty} onChangeText={setAddQty} />
                  <Button title="Save" onPress={() => save(sp)} />
                  <Button title="Cancel" kind="ghost" onPress={() => setOpen(null)} />
                </>
              ) : (
                <Button title={sp.gst_rate !== undefined ? "Edit price / GST / cost / expiry / stock" : "Edit price / cost / expiry / stock"} kind="ghost" onPress={() => startEdit(sp)} />
              )}
            </Card>
          );
        }}
      />
    </Screen>
  );
}