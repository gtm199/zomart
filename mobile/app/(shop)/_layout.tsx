import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { colors } from "../../components/ui";

export default function ShopTabs() {
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: colors.primary, headerTitleAlign: "center" }}>
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
        name="today"
        options={{ title: "Today", tabBarIcon: ({ color, size }) => <Ionicons name="stats-chart-outline" size={size} color={color} /> }}
      />
    </Tabs>
  );
}