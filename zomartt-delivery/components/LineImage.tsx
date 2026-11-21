import { useState } from "react";
import { Image, Modal, Pressable, Text, View } from "react-native";
import { colors } from "./ui";

/**
 * Small product picture on an order line, so the rider can check the right item is in the bag.
 * uri = tiny picture (image_tiny); tapUri = a bigger one opened on tap (image_thumb).
 * Uses React Native's own Image (no extra package, so it can go out as an over-the-air update).
 * No picture, or it fails to load: the first letter is shown.
 */
export default function LineImage({ uri, tapUri, name, size = 36 }: { uri?: string | null; tapUri?: string | null; name: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  if (!uri || failed) {
    return (
      <View style={{ width: size, height: size, borderRadius: 6, backgroundColor: "#e5e7eb", alignItems: "center", justifyContent: "center" }}>
        <Text style={{ fontSize: size * 0.42, fontWeight: "700", color: colors.muted }}>{(name || "?").trim().charAt(0).toUpperCase()}</Text>
      </View>
    );
  }
  return (
    <>
      <Pressable onPress={() => setOpen(true)} accessibilityRole="imagebutton" accessibilityLabel={`Open picture of ${name}`}>
        <Image source={{ uri }} style={{ width: size, height: size, borderRadius: 6, backgroundColor: "#f3f4f6" }}
          resizeMode="cover" onError={() => setFailed(true)} />
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable onPress={() => setOpen(false)} style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.9)", justifyContent: "center", alignItems: "center", padding: 20 }}>
          <Image source={{ uri: tapUri || uri }} style={{ width: "100%", height: "60%" }} resizeMode="contain" />
          <Text style={{ color: "#fff", marginTop: 12, textAlign: "center" }}>{name}</Text>
          <Text style={{ color: "#ccc", marginTop: 6 }}>Tap to close</Text>
        </Pressable>
      </Modal>
    </>
  );
}
