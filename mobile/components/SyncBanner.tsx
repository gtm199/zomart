import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, Text } from "react-native";
import { colors } from "./ui";
import { getStatus, onSyncChange } from "../services/sync";

export function useSyncStatus() {
  const [s, setS] = useState({ waiting: 0, failed: 0, lastSync: null as string | null });
  useEffect(() => {
    let alive = true;
    const load = () => { getStatus().then((v) => { if (alive) setS(v); }).catch(() => {}); };
    load();
    const off = onSyncChange(load);
    return () => { alive = false; off(); };
  }, []);
  return s;
}

export default function SyncBanner() {
  const router = useRouter();
  const { waiting, failed } = useSyncStatus();
  if (waiting + failed === 0) return null;
  const bad = failed > 0;
  return (
    <Pressable
      onPress={() => router.push("/(shop)/sync")}
      style={{ backgroundColor: bad ? "#fee2e2" : "#fef3c7", borderRadius: 10, padding: 12, marginBottom: 8,
               borderWidth: 1, borderColor: bad ? colors.danger : "#f59e0b" }}
    >
      <Text style={{ fontWeight: "700", color: bad ? colors.danger : "#b45309" }}>
        {failed > 0 ? `${failed} bill(s) need attention. ` : ""}
        {waiting > 0 ? `${waiting} bill(s) waiting to upload.` : ""}
      </Text>
      <Text style={{ color: colors.muted, fontSize: 12 }}>Tap for details</Text>
    </Pressable>
  );
}