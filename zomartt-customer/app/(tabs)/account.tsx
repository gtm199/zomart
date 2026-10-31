import { Text } from "react-native";
import { Button, Card, Muted, Screen } from "../../components/ui";
import { useSession } from "../../store/session";

export default function Account() {
  const { shopper, signOut } = useSession();
  return (
    <Screen>
      <Card>
        <Text style={{ fontWeight: "700", fontSize: 16 }}>{shopper?.name}</Text>
        <Muted>{shopper?.phone}</Muted>
      </Card>
      <Muted>Shops only see your name and number on the orders you send them.</Muted>
      <Button title="Sign out" kind="danger" onPress={signOut} />
    </Screen>
  );
}