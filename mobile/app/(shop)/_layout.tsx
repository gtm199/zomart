import { Ionicons } from "@expo/vector-icons";
import { Tabs, useRouter } from "expo-router";
import { useEffect } from "react";
import { Pressable, Text } from "react-native";
import { Button, Card, Muted, Screen, colors } from "../../components/ui";
import { startSyncLoop } from "../../services/sync";
import { useSession } from "../../store/session";

function BackToMenu() {
  const router = useRouter();
  return (
    <Pressable onPress={() => router.navigate("/(shop)/menu")} hitSlop={10} style={{ paddingHorizontal: 16 }}>
      <Ionicons name="arrow-back" size={24} color={colors.text} />
    </Pressable>
  );
}

// SDK 58: href: null makes a screen unreachable. Hiding only the button keeps the screen open-able.
const hidden = (title: string) => ({
  title,
  tabBarItemStyle: { display: "none" as const },
  headerLeft: () => <BackToMenu />,
});
const icon = (name: any) => ({ color, size }: { color: string; size: number }) => <Ionicons name={name} size={size} color={color} />;

export default function ShopTabs() {
  const { shop, refresh, signOut } = useSession();

  /* ADD THIS: temporary test
  useEffect(() => {
    console.log("TABS MOUNT");
    return () => console.log("TABS UNMOUNT");
  }, []); */

  useEffect(() => {
    if (!shop?.approved) return;
    return startSyncLoop();
  }, [shop?.id, shop?.approved]);

  if (shop && !shop.approved) {
    return (
      <Screen>
        <Card>
          <Text style={{ fontSize: 18, fontWeight: "700" }}>Waiting for approval</Text>
          <Muted>Your shop "{shop.name}" is registered. We will switch it on after a quick check, then your free trial starts.</Muted>
          <Button title="Check again" onPress={() => refresh().catch(() => {})} />
          <Button title="Sign out" kind="ghost" onPress={signOut} />
        </Card>
      </Screen>
    );
  }

  return (
    <Tabs key={shop?.id} backBehavior="history" screenOptions={{ tabBarActiveTintColor: colors.primary, headerTitleAlign: "center" }}>
      <Tabs.Screen name="pos" options={{ title: "Bill", tabBarIcon: icon("receipt-outline") }} />
      <Tabs.Screen name="catalogue" options={{ title: "Catalogue", tabBarIcon: icon("grid-outline") }} />
      <Tabs.Screen name="stock" options={{ title: "My Stock", tabBarIcon: icon("cube-outline") }} />
      <Tabs.Screen name="customers" options={{ title: "Customers", tabBarIcon: icon("people-outline") }} />
      <Tabs.Screen name="menu" options={{ title: "Menu", tabBarIcon: icon("menu-outline") }} />

      {/* Opened from the Menu tab; hidden from the bottom bar */}
      <Tabs.Screen name="purchases" options={hidden("Purchases")} />
      <Tabs.Screen name="expenses" options={hidden("Expenses")} />
      <Tabs.Screen name="reports" options={hidden("Reports")} />
      <Tabs.Screen name="cashclose" options={hidden("Cash close")} />
      <Tabs.Screen name="today" options={hidden("Today")} />
      <Tabs.Screen name="sync" options={hidden("Offline & sync")} />
      <Tabs.Screen name="notifications" options={hidden("Notices")} />
      <Tabs.Screen name="customerbills" options={hidden("Customer bills")} />
      <Tabs.Screen name="plan" options={hidden("Plan & payment")} />
      <Tabs.Screen name="staff" options={hidden("Staff")} />
      <Tabs.Screen name="shops" options={hidden("Switch shop")} />
      <Tabs.Screen name="bills" options={hidden("Past bills")} />
      <Tabs.Screen name="account" options={hidden("My account")} />
      <Tabs.Screen name="orders" options={hidden("Online orders")} />
      <Tabs.Screen name="storesettings" options={hidden("Online store")} />
    </Tabs>
  );
}