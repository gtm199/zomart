import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Pressable, ScrollView, Text, View } from "react-native";
import { Button, Muted, Screen, colors } from "../../components/ui";
import { useSession } from "../../store/session";

const ITEMS = [
  { title: "Purchases", subtitle: "Suppliers, receive stock, pay suppliers", icon: "cart-outline", path: "/(shop)/purchases", cap: "view_purchases" },
  { title: "Expenses", subtitle: "Rent, salary, electricity...", icon: "wallet-outline", path: "/(shop)/expenses", cap: "view_reports" },
  { title: "Reports", subtitle: "Profit, top sellers, dues", icon: "bar-chart-outline", path: "/(shop)/reports", cap: "view_reports" },
  { title: "Cash close", subtitle: "Count the drawer at end of day", icon: "calculator-outline", path: "/(shop)/cashclose", cap: "view_reports" },
  { title: "Today", subtitle: "Daily sales summary", icon: "stats-chart-outline", path: "/(shop)/today", cap: "view_shop" },
] as const;

export default function Menu() {
  const router = useRouter();
  const { shop, can, signOut } = useSession();

  return (
    <Screen>
      <ScrollView>
        <Text style={{ fontSize: 18, fontWeight: "700" }}>{shop?.name}</Text>
        <Muted>Role: {shop?.role}</Muted>
        <View style={{ height: 12 }} />

        {ITEMS.filter((i) => can(i.cap)).map((item) => (
          <Pressable
            key={item.path}
            onPress={() => router.push(item.path)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              backgroundColor: colors.card,
              borderRadius: 10,
              padding: 14,
              marginVertical: 5,
              borderWidth: 1,
              borderColor: "#e5e7eb",
            }}
          >
            <Ionicons name={item.icon} size={26} color={colors.primary} />
            <View style={{ flex: 1, marginLeft: 12 }}>
              <Text style={{ fontWeight: "600", fontSize: 16 }}>{item.title}</Text>
              <Muted>{item.subtitle}</Muted>
            </View>
            <Ionicons name="chevron-forward" size={20} color={colors.muted} />
          </Pressable>
        ))}

        <View style={{ height: 16 }} />
        <Button title="Sign out" kind="danger" onPress={signOut} />
      </ScrollView>
    </Screen>
  );
}