import "../services/tracking"; // defines the background location task when the app starts
import { Stack, useRouter, useSegments } from "expo-router";
import { useEffect } from "react";
import { SessionProvider, useSession } from "../store/session";

function Guard() {
  const { ready, signedIn } = useSession();
  const segments = useSegments();
  const router = useRouter();
  useEffect(() => {
    if (!ready) return;
    const inAuth = segments[0] === "(auth)";
    if (!signedIn && !inAuth) router.replace("/(auth)/login");
    if (signedIn && inAuth) router.replace("/");
  }, [ready, signedIn, segments]);

  return (
    <Stack>
      <Stack.Screen name="(auth)" options={{ headerShown: false }} />
      <Stack.Screen name="index" options={{ title: "My deliveries" }} />
      <Stack.Screen name="delivery/[id]" options={{ title: "Delivery" }} />
    </Stack>
  );
}

export default function Root() {
  return (
    <SessionProvider>
      <Guard />
    </SessionProvider>
  );
}