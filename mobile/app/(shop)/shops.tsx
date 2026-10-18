import { useRouter } from "expo-router";
import { Text } from "react-native";
import { Button, Card, Muted, Screen, colors } from "../../components/ui";
import { useSession } from "../../store/session";

export default function Shops() {
  const router = useRouter();
  const { shops, shop, switchShop } = useSession();
  return (
    <Screen>
      <Button title="← Back to menu" kind="ghost" onPress={() => router.navigate("/(shop)/menu")} />
      {shops.map((s) => (
        <Card key={s.id}>
          <Text style={{ fontWeight: "700" }}>{s.name}</Text>
          <Muted>Your role here: {s.role}{s.approved ? "" : " · waiting for approval"}</Muted>
          {s.id === shop?.id ? (
            <Text style={{ color: colors.primary, fontWeight: "700" }}>Current shop</Text>
          ) : (
            <Button title="Use this shop" onPress={async () => { await switchShop(s.id); router.navigate("/(shop)/pos"); }} />
          )}
        </Card>
      ))}
      <Muted>Bills and stock always belong to the shop you are in. Bills waiting to upload must be sent before you switch.</Muted>
    </Screen>
  );
}