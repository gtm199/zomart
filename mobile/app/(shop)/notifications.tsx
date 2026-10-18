import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Text } from "react-native";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";

type Notice = { id: number; title: string; message: string; created_at: string; read: boolean };

export default function Notifications() {
  const router = useRouter();
  const [items, setItems] = useState<Notice[]>([]);
  const [err, setErr] = useState("");

  useFocusEffect(
    useCallback(() => {
      (async () => {
        try {
          const r = await api<{ unread_count: number; results: Notice[] }>("/shop/notifications/");
          setItems(r.results); // shown with their unread state first...
          if (r.unread_count > 0) await api("/shop/notifications/", { method: "POST", body: {} }); // ...then marked as read
          setErr("");
        } catch (e: any) {
          setErr(e.message);
        }
      })();
    }, [])
  );

  return (
    <Screen>
      <Button title="← Back to menu" kind="ghost" onPress={() => router.navigate("/(shop)/menu")} />
      <Err msg={err} />
      <FlatList
        data={items}
        keyExtractor={(n) => String(n.id)}
        ListEmptyComponent={<Muted>No notices.</Muted>}
        renderItem={({ item: n }) => (
          <Card>
            <Text style={{ fontWeight: n.read ? "400" : "700", color: n.read ? colors.text : colors.danger }}>{n.title}</Text>
            <Text>{n.message}</Text>
            <Muted>{new Date(n.created_at).toLocaleString("en-IN")}</Muted>
          </Card>
        )}
      />
    </Screen>
  );
}