import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Switch, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { Page, ShopProduct } from "../../types";

export default function Stock() {
  const [q, setQ] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [items, setItems] = useState<ShopProduct[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [addQty, setAddQty] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const path = `/shop/products/?search=${encodeURIComponent(q)}${lowOnly ? "&low_stock=true" : ""}`;
      setItems((await api<Page<ShopProduct>>(path)).results);
    } catch (e: any) {
      setErr(e.message);
    }
  }, [q, lowOnly]);

  // Reload every time this screen comes into view (e.g. after saving a purchase)
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const startEdit = (sp: ShopProduct) => {
    setOpen(sp.id);
    setPrice(sp.selling_price);
    setCost(sp.purchase_cost ?? "");
    setAddQty("");
    setErr("");
  };

  const save = async (sp: ShopProduct) => {
    setErr("");
    try {
      const body: Record<string, string> = {};
      if (price && price !== sp.selling_price) body.selling_price = price;
      if (sp.purchase_cost !== undefined && cost && cost !== sp.purchase_cost) body.purchase_cost = cost;
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

  return (
    <Screen>
      <Input placeholder="Search my products" value={q} onChangeText={setQ} />
      <View style={{ flexDirection: "row", alignItems: "center" }}>
        <Switch value={lowOnly} onValueChange={setLowOnly} />
        <Text> Low stock only</Text>
      </View>
      <Err msg={err} />
      <FlatList
        data={items}
        keyExtractor={(i) => String(i.id)}
        renderItem={({ item: sp }) => (
          <Card>
            <Text style={{ fontWeight: "600" }}>{sp.master_product.display_name}</Text>
            <Text style={{ color: sp.is_low_stock ? colors.danger : colors.text }}>
              Stock {sp.stock_qty} · Sell ₹{sp.selling_price}
              {sp.purchase_cost !== undefined ? ` · Cost ₹${sp.purchase_cost}` : ""}
            </Text>
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
                <Muted>Stock received (+)</Muted>
                <Input placeholder="0" keyboardType="decimal-pad" value={addQty} onChangeText={setAddQty} />
                <Button title="Save" onPress={() => save(sp)} />
                <Button title="Cancel" kind="ghost" onPress={() => setOpen(null)} />
              </>
            ) : (
              <Button title="Edit price / cost / stock" kind="ghost" onPress={() => startEdit(sp)} />
            )}
          </Card>
        )}
      />
    </Screen>
  );
}