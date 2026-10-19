import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Switch, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { Page, ShopProduct } from "../../types";

const WARN = "#b45309";

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
  const [items, setItems] = useState<ShopProduct[]>([]);
  const [alerts, setAlerts] = useState<{ expired_count: number; expiring_soon_count: number } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [expiry, setExpiry] = useState("");
  const [addQty, setAddQty] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      setErr("");
      const path = `/shop/products/?search=${encodeURIComponent(q)}${lowOnly ? "&low_stock=true" : ""}${expiringOnly ? "&expiring=true" : ""}`;
      setItems((await api<Page<ShopProduct>>(path)).results);
      setAlerts(await api("/shop/products/expiry-alerts/"));
    } catch (e: any) {
      setErr(e.message);
    }
  }, [q, lowOnly, expiringOnly]);

  // Reload every time this screen comes into view (e.g. after saving a purchase)
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const startEdit = (sp: ShopProduct) => {
    setOpen(sp.id);
    setPrice(sp.selling_price);
    setCost(sp.purchase_cost ?? "");
    setExpiry(sp.expiry_date ?? "");
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
      const body: Record<string, string | null> = {};
      if (price && price !== sp.selling_price) body.selling_price = price;
      if (sp.purchase_cost !== undefined && cost && cost !== sp.purchase_cost) body.purchase_cost = cost;
      if (expiry !== (sp.expiry_date ?? "")) body.expiry_date = expiry === "" ? null : expiry;
      if (Object.keys(body).length > 0) {
        await api(`/shop/products/${sp.id}/`, { method: "PATCH", body });
      }
      if (addQty) {
        await api(`/shop/products/${sp.id}/adjust-stock/`, { body: { quantity_delta: addQty, movement_type: "purchase" } });
      }
      setOpen(null);
      setAddQty("");
      load();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const alertCount = (alerts?.expired_count ?? 0) + (alerts?.expiring_soon_count ?? 0);

  return (
    <Screen>
      <Input placeholder="Search my products" value={q} onChangeText={setQ} />
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
      </View>
      <Err msg={err} />
      <FlatList
        data={items}
        keyExtractor={(i) => String(i.id)}
        renderItem={({ item: sp }) => {
          const ex = expiryLine(sp);
          return (
            <Card>
              <Text style={{ fontWeight: "600" }}>{sp.master_product.display_name}</Text>
              <Text style={{ color: sp.is_low_stock ? colors.danger : colors.text }}>
                Stock {sp.stock_qty}{sp.master_product.is_loose ? ` ${sp.master_product.unit}` : ""}
                {sp.purchase_cost !== undefined ? ` · Cost ₹${sp.purchase_cost}` : ""}
              </Text>
              {ex && <Text style={{ color: ex.color, fontWeight: sp.expiry_status === "ok" ? "400" : "700" }}>{ex.text}</Text>}
              {!sp.master_active && <Text style={{ color: colors.danger, fontWeight: "700" }}>Removed from catalogue: cannot be sold</Text>}
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
                  <Muted>Stock received (+)</Muted>
                  <Input placeholder="0" keyboardType="decimal-pad" value={addQty} onChangeText={setAddQty} />
                  <Button title="Save" onPress={() => save(sp)} />
                  <Button title="Cancel" kind="ghost" onPress={() => setOpen(null)} />
                </>
              ) : (
                <Button title="Edit price / cost / expiry / stock" kind="ghost" onPress={() => startEdit(sp)} />
              )}
            </Card>
          );
        }}
      />
    </Screen>
  );
}