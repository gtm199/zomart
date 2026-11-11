import * as Location from "expo-location";
import * as SecureStore from "expo-secure-store";
import * as TaskManager from "expo-task-manager";
import { BASE, keep } from "./api";

export const TASK = "zomartt-rider-location";

async function post(order: string, loc: Location.LocationObject) {
  const [token, shop] = await Promise.all([SecureStore.getItemAsync("token"), SecureStore.getItemAsync("shop")]);
  if (!token || !shop) return;
  const c = loc.coords;
  try {
    await fetch(`${BASE}/delivery/orders/${order}/location/`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Token ${token}`, "X-Shop-ID": shop },
      body: JSON.stringify({
        lat: c.latitude, lng: c.longitude,
        heading: c.heading != null && c.heading >= 0 ? c.heading : null,
        speed: c.speed != null && c.speed >= 0 ? c.speed : null,
        accuracy: c.accuracy ?? null,
      }),
    });
  } catch { /* no internet for a moment: the next update will arrive */ }
}

// This must run when the app starts: it is what receives the locations while the app is in the background.
TaskManager.defineTask(TASK, async ({ data, error }: any) => {
  if (error || !data?.locations?.length) return;
  const order = await SecureStore.getItemAsync("tripOrder");
  if (!order) return;
  await post(order, data.locations[data.locations.length - 1]);
});

let watcher: Location.LocationSubscription | null = null;

/** Starts sharing the rider's position. "background" keeps working with the screen off; "foreground" only while the app is open. */
export async function startTracking(orderId: number): Promise<"background" | "foreground" | "denied"> {
  const fg = await Location.requestForegroundPermissionsAsync();
  if (fg.status !== "granted") return "denied";
  await keep.set("tripOrder", String(orderId));
  try {
    const bg = await Location.requestBackgroundPermissionsAsync();
    if (bg.status === "granted") {
      await Location.startLocationUpdatesAsync(TASK, {
        accuracy: Location.Accuracy.High,
        timeInterval: 8000,
        distanceInterval: 15,
        showsBackgroundLocationIndicator: true,
        foregroundService: {
          notificationTitle: "Delivery in progress",
          notificationBody: "Sharing your location with the customer",
          notificationColor: "#0f766e",
        },
      });
      return "background";
    }
  } catch { /* Expo Go and some phones cannot do this: fall back to foreground sharing */ }
  watcher?.remove();
  watcher = await Location.watchPositionAsync(
    { accuracy: Location.Accuracy.High, timeInterval: 8000, distanceInterval: 15 },
    (loc) => { post(String(orderId), loc); }
  );
  return "foreground";
}

export async function stopTracking() {
  try { if (await Location.hasStartedLocationUpdatesAsync(TASK)) await Location.stopLocationUpdatesAsync(TASK); } catch {}
  watcher?.remove();
  watcher = null;
  await keep.del("tripOrder");
}
