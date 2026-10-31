import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { colors } from "../../components/ui";
import { useCart } from "../../store/cart";

export default function TabsLayout() {
  const { lines } = useCart();
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: colors.primary, headerTitleAlign: "center" }}>
      <Tabs.Screen name="index" options={{ title: "My shops", tabBarIcon: ({ color, size }) => <Ionicons name="storefront-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="cart" options={{ title: "Basket", tabBarBadge: lines.length > 0 ? lines.length : undefined, tabBarIcon: ({ color, size }) => <Ionicons name="basket-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="orders" options={{ title: "Orders", tabBarIcon: ({ color, size }) => <Ionicons name="receipt-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="account" options={{ title: "Account", tabBarIcon: ({ color, size }) => <Ionicons name="person-circle-outline" size={size} color={color} /> }} />
    </Tabs>
  );
}