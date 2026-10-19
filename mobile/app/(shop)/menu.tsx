import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import SyncBanner from "../../components/SyncBanner";
import { Button, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

const ITEMS = [
  { title: "Plan & payment", subtitle: "Your plan, expiry date and how to pay", icon: "card-outline", path: "/(shop)/plan", cap: "view_shop" },
  { title: "Purchases", subtitle: "Suppliers, receive stock, pay suppliers", icon: "cart-outline", path: "/(shop)/purchases", cap: "view_purchases" },
  { title: "Expenses", subtitle: "Rent, salary, electricity...", icon: "wallet-outline", path: "/(shop)/expenses", cap: "view_reports" },
  { title: "Reports", subtitle: "Profit, top sellers, dues", icon: "bar-chart-outline", path: "/(shop)/reports", cap: "view_reports" },
  { title: "Cash close", subtitle: "Count the drawer at end of day", icon: "calculator-outline", path: "/(shop)/cashclose", cap: "view_reports" },
  { title: "Today", subtitle: "Daily sales summary", icon: "stats-chart-outline", path: "/(shop)/today", cap: "view_shop" },
  { title: "Staff", subtitle: "Add cashiers, switch them off", icon: "people-circle-outline", path: "/(shop)/staff", cap: "manage_members" },
  { title: "Offline & sync", subtitle: "Bills waiting to upload, bills to review", icon: "sync-outline", path: "/(shop)/sync", cap: "sell" },
  { title: "Past bills", subtitle: "Find a bill, share PDF, print", icon: "documents-outline", path: "/(shop)/bills", cap: "view_sales" },
] as const;

type Plan = { write_allowed: boolean; days_left: number | null; reminder_days: number };

export default function Menu() {
  const router = useRouter();
  const { shop, shops, can, signOut } = useSession();
  const [alerts, setAlerts] = useState<{ expired_count: number; expiring_soon_count: number } | null>(null);
  const [notices, setNotices] = useState(0);
  const [plan, setPlan] = useState<Plan | null>(null);

  useFocusEffect(
    useCallback(() => {
      api("/shop/subscription/").then((r: any) => setPlan(r)).catch(() => {});
      api<{ unread_count: number }>("/shop/notifications/").then((r) => setNotices(r.unread_count)).catch(() => {});
      if (can("view_products")) api("/shop/products/expiry-alerts/").then((r: any) => setAlerts(r)).catch(() => {});
    }, [])
  );

  const expired = alerts?.expired_count ?? 0;
  const soon = alerts?.expiring_soon_count ?? 0;
  const planWarning =
    plan && !plan.write_allowed
      ? "Your plan has expired. You can look at your data but not save changes."
      : plan && plan.days_left !== null && plan.days_left < 0
      ? `Your plan expired ${-plan.days_left} day(s) ago. Please renew now.`
      : plan && plan.days_left !== null && plan.days_left <= plan.reminder_days
      ? `Your plan expires in ${plan.days_left} day(s).`
      : "";

  const card = (title: string, sub: string, color: string, bg: string, onPress: () => void) => (
    <Pressable onPress={onPress} style={{ backgroundColor: bg, borderRadius: 10, padding: 14, marginBottom: 8, borderWidth: 1, borderColor: color }}>
      <Text style={{ fontWeight: "700", color }}>{title}</Text>
      <Muted>{sub}</Muted>
    </Pressable>
  );

  return (
    <Screen>
      <ScrollView>
        <Text style={{ fontSize: 18, fontWeight: "700" }}>{shop?.name}</Text>
        <Muted>Role: {shop?.role}</Muted>
        <View style={{ height: 12 }} />

        <SyncBanner />
        {planWarning !== "" && card(planWarning, "Tap to renew", colors.danger, "#fee2e2", () => router.push("/(shop)/plan"))}
        {notices > 0 && card(`${notices} new notice(s) from the catalogue team`, "Tap to read", colors.danger, "#fee2e2", () => router.push("/(shop)/notifications"))}
        {expired + soon > 0 &&
          card(
            `${expired > 0 ? `${expired} product(s) expired. ` : ""}${soon > 0 ? `${soon} expiring within 30 days.` : ""}`,
            "Tap to open My Stock", expired > 0 ? colors.danger : "#b45309", "#fef3c7", () => router.navigate("/(shop)/stock")
          )}

        {ITEMS.filter((i) => can(i.cap)).map((item) => (
          <Pressable
            key={item.path}
            onPress={() => router.push(item.path)}
            style={{ flexDirection: "row", alignItems: "center", backgroundColor: colors.card, borderRadius: 10, padding: 14, marginVertical: 5, borderWidth: 1, borderColor: "#e5e7eb" }}
          >
            <Ionicons name={item.icon} size={26} color={colors.primary} />
            <View style={{ flex: 1, marginLeft: 12 }}>
              <Text style={{ fontWeight: "600", fontSize: 16 }}>{item.title}</Text>
              <Muted>{item.subtitle}</Muted>
            </View>
            <Ionicons name="chevron-forward" size={20} color={colors.muted} />
          </Pressable>
        ))}

        {shops.length > 1 && (
          <Pressable
            onPress={() => router.push("/(shop)/shops")}
            style={{ flexDirection: "row", alignItems: "center", backgroundColor: colors.card, borderRadius: 10, padding: 14, marginVertical: 5, borderWidth: 1, borderColor: "#e5e7eb" }}
          >
            <Ionicons name="storefront-outline" size={26} color={colors.primary} />
            <View style={{ flex: 1, marginLeft: 12 }}>
              <Text style={{ fontWeight: "600", fontSize: 16 }}>Switch shop</Text>
              <Muted>You have {shops.length} shops</Muted>
            </View>
            <Ionicons name="chevron-forward" size={20} color={colors.muted} />
          </Pressable>
        )}

        <View style={{ height: 16 }} />
        <Button title="Sign out" kind="danger" onPress={signOut} />
      </ScrollView>
    </Screen>
  );
}