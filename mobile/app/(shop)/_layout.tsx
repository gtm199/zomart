import { Ionicons } from "@expo/vector-icons";
import { Tabs, useRouter } from "expo-router";
import { Pressable } from "react-native";
import { colors } from "../../components/ui";

function BackToMenu() {
  const router = useRouter();
  return (
    <Pressable onPress={() => router.navigate("/(shop)/menu")} hitSlop={10} style={{ paddingHorizontal: 16 }}>
      <Ionicons name="arrow-back" size={24} color={colors.text} />
    </Pressable>
  );
}

const hidden = (title: string) => ({ href: null, title, headerLeft: () => <BackToMenu /> });

export default function ShopTabs() {
  return (
    <Tabs
      backBehavior="history"
      screenOptions={{ tabBarActiveTintColor: colors.primary, headerTitleAlign: "center" }}
    >
      <Tabs.Screen
        name="pos"
        options={{ title: "Bill", tabBarIcon: ({ color, size }) => <Ionicons name="receipt-outline" size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="catalogue"
        options={{ title: "Catalogue", tabBarIcon: ({ color, size }) => <Ionicons name="grid-outline" size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="stock"
        options={{ title: "My Stock", tabBarIcon: ({ color, size }) => <Ionicons name="cube-outline" size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="customers"
        options={{ title: "Customers", tabBarIcon: ({ color, size }) => <Ionicons name="people-outline" size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="menu"
        options={{ title: "Menu", tabBarIcon: ({ color, size }) => <Ionicons name="menu-outline" size={size} color={color} /> }}
      />

      {/* Opened from the Menu tab; hidden from the bottom bar */}
      <Tabs.Screen name="purchases" options={hidden("Purchases")} />
      <Tabs.Screen name="expenses" options={hidden("Expenses")} />
      <Tabs.Screen name="reports" options={hidden("Reports")} />
      <Tabs.Screen name="cashclose" options={hidden("Cash close")} />
      <Tabs.Screen name="today" options={hidden("Today")} />
    </Tabs>
  );
}