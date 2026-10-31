import { useRouter } from "expo-router";
import { FlatList, Text, View } from "react-native";
import { Button, Card, Muted, Screen } from "../../components/ui";
import { lineCents, useCart } from "../../store/cart";

export default function Cart() {
  const router = useRouter();
  const cart = useCart();
  const shop = cart.shop;

  if (!shop || cart.lines.length === 0) {
    return <Screen><Muted>Your basket is empty. Open a shop and add items.</Muted></Screen>;
  }
  return (
    <Screen>
      <Text style={{ fontWeight: "700", fontSize: 16 }}>Basket · {shop.name}</Text>
      <FlatList
        data={cart.lines}
        keyExtractor={(l) => String(l.id)}
        renderItem={({ item: l }) => (
          <Card>
            <Text style={{ fontWeight: "600" }}>{l.name}</Text>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <Muted>₹{Number(l.price)} × {l.qty}{l.loose ? ` ${l.unit}` : ""} = ₹{(lineCents(l.price, l.qty) / 100).toFixed(2)}</Muted>
              <View style={{ flexDirection: "row", gap: 8 }}>
                <Button title="−" kind="ghost" onPress={() => cart.setQty(shop, l, Math.max(0, l.qty - (l.loose ? 0.25 : 1)))} />
                <Button title="+" kind="ghost" onPress={() => cart.setQty(shop, l, l.qty + (l.loose ? 0.25 : 1))} />
              </View>
            </View>
          </Card>
        )}
      />
      <Text style={{ fontSize: 20, fontWeight: "700" }}>Items ₹{cart.total.toFixed(2)}</Text>
      <Muted>Delivery fee, if any, is added at checkout.</Muted>
      <Button title="Continue to checkout" onPress={() => router.push("/checkout")} />
      <Button title="Empty basket" kind="ghost" onPress={cart.clear} />
    </Screen>
  );
}