import { Stack, useRouter, useSegments } from "expo-router";
import { useEffect } from "react";
import { SessionProvider, useSession } from "../store/session";

function Guard() {
  const { ready, session } = useSession();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    //console.log("GUARD", { hasSession: !!session, seg: segments.join("/") }); //to be removed
    const inAuth = segments[0] === "(auth)";
    if (!session && !inAuth) router.replace("/(auth)/login");
    if (session && inAuth) router.replace("/(shop)/pos");
  }, [ready, session, segments]);
  return <Stack screenOptions={{ headerShown: false }} />;
}
export default function Root() {
  return <SessionProvider><Guard /></SessionProvider>;
}
