import { Image } from "expo-image";
import { useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors } from "./ui";

/**
 * The product picture. Tap it to see the large picture full-screen (tap anywhere, press ✕, or use the back button to close).
 * uri = the small picture shown in lists; fullUri = the large one opened on tap (the small one is used if there is none).
 * Shows the first letter if there is no picture.
 */
export default function ProductImage({ uri, fullUri, name, size = 64 }: { uri?: string | null; fullUri?: string | null; name: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const insets = useSafeAreaInsets();

  if (!uri || failed) {
    return (
      <View style={{ width: size, height: size, borderRadius: 8, backgroundColor: "#e5e7eb", alignItems: "center", justifyContent: "center" }}>
        <Text style={{ fontSize: size * 0.4, fontWeight: "700", color: colors.muted }}>{(name || "?").trim().charAt(0).toUpperCase()}</Text>
      </View>
    );
  }

  return (
    <>
      <Pressable onPress={() => setOpen(true)} accessibilityRole="imagebutton" accessibilityLabel={`Open picture of ${name}`}>
        <Image
          source={{ uri }}
          style={{ width: size, height: size, borderRadius: 8, backgroundColor: "#f3f4f6" }}
          contentFit="cover"
          transition={150}
          cachePolicy="disk"
          onError={() => setFailed(true)}
        />
      </Pressable>

      <Modal visible={open} transparent animationType="fade" statusBarTranslucent onRequestClose={() => setOpen(false)}>
        <Pressable
          onPress={() => setOpen(false)}
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.92)", justifyContent: "center", alignItems: "center" }}
        >
          <Image
            source={{ uri: fullUri || uri }}
            placeholder={{ uri }}            // the small picture shows at once while the large one loads
            style={{ width: "100%", height: "78%" }}
            contentFit="contain"
            transition={200}
            cachePolicy="disk"
          />
          <Text style={{ color: "#fff", marginTop: 12, paddingHorizontal: 20, textAlign: "center", fontSize: 15 }}>{name}</Text>
          <Pressable
            onPress={() => setOpen(false)}
            hitSlop={12}
            style={{ position: "absolute", top: insets.top + 12, right: 16, width: 40, height: 40, borderRadius: 20, backgroundColor: "rgba(255,255,255,0.2)", alignItems: "center", justifyContent: "center" }}
          >
            <Text style={{ color: "#fff", fontSize: 20, fontWeight: "700" }}>✕</Text>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}