import { Stack, useRouter, useSegments } from "expo-router";
import { useEffect } from "react";
import { CartProvider } from "../store/cart";
import { SessionProvider, useSession } from "../store/session";

function Guard() {
  const { ready, shopper } = useSession();
  const segments = useSegments();
  const router = useRouter();
  useEffect(() => {
    if (!ready) return;
    const inAuth = segments[0] === "(auth)";
    if (!shopper && !inAuth) router.replace("/(auth)/login");
    if (shopper && inAuth) router.replace("/(tabs)");
  }, [ready, shopper, segments]);

  return (
    <Stack>
      <Stack.Screen name="(auth)" options={{ headerShown: false }} />
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="shop/[id]" options={{ title: "Shop" }} />
      <Stack.Screen name="checkout" options={{ title: "Checkout" }} />
      <Stack.Screen name="order/[id]" options={{ title: "Your order" }} />
    </Stack>
  );
}

export default function Root() {
  return (
    <SessionProvider>
      <CartProvider>
        <Guard />
      </CartProvider>
    </SessionProvider>
  );
}