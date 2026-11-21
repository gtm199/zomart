import { Image } from "expo-image";
import { useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors } from "./ui";

/**
 * The product picture (the server builds all sizes from one Cloudinary image):
 *   uri       = small picture for lists (image_thumb, 300 px)
 *   mediumUri = detail size (image_medium, 800 px) - shown at once when the picture is opened
 *   fullUri   = large picture opened on tap (1600 px); falls back to medium, then small, if it fails to load
 * Tap to open full-screen (tap anywhere, press ✕, or use the back button to close).
 * With no picture (or if it fails to load) the first letter is shown - a product without an image works normally.
 * Pictures are cached on the phone (expo-image, disk cache).
 */
export default function ProductImage({ uri, mediumUri, fullUri, name, size = 64 }: {
  uri?: string | null; mediumUri?: string | null; fullUri?: string | null; name: string; size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [bigIndex, setBigIndex] = useState(0);   // which of the large sizes is shown (moves on if one fails)
  const insets = useSafeAreaInsets();
  const small = uri || mediumUri || fullUri || null;
  const big = [fullUri, mediumUri, small].filter((u, i, a): u is string => !!u && a.indexOf(u) === i);

  if (!small || failed) {
    return (
      <View style={{ width: size, height: size, borderRadius: 8, backgroundColor: "#e5e7eb", alignItems: "center", justifyContent: "center" }}>
        <Text style={{ fontSize: size * 0.4, fontWeight: "700", color: colors.muted }}>{(name || "?").trim().charAt(0).toUpperCase()}</Text>
      </View>
    );
  }

  return (
    <>
      <Pressable onPress={() => { setBigIndex(0); setOpen(true); }} accessibilityRole="imagebutton" accessibilityLabel={`Open picture of ${name}`}>
        <Image
          source={{ uri: small }}
          recyclingKey={small}
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
          {big[bigIndex] ? (
            <Image
              source={{ uri: big[bigIndex] }}
              placeholder={{ uri: mediumUri || small }}   // shows at once while the large one loads
              style={{ width: "100%", height: "78%" }}
              contentFit="contain"
              transition={200}
              cachePolicy="disk"
              onError={() => setBigIndex((i) => i + 1)}
            />
          ) : (
            <Text style={{ color: "#fff" }}>The picture could not be loaded.</Text>
          )}
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
