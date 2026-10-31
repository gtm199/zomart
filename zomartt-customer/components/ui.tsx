import React from "react";
import { Pressable, StyleSheet, Text, TextInput, TextInputProps, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

export const colors = { primary: "#0f766e", bg: "#f6f7f8", card: "#fff", text: "#111827", muted: "#6b7280", danger: "#b91c1c", border: "#d1d5db" };

export function Button({ title, onPress, kind = "primary", disabled }: { title: string; onPress: () => void; kind?: "primary" | "ghost" | "danger"; disabled?: boolean }) {
  const bg = kind === "primary" ? colors.primary : kind === "danger" ? colors.danger : "transparent";
  return (
    <Pressable onPress={onPress} disabled={disabled}
      style={[s.btn, { backgroundColor: bg, opacity: disabled ? 0.5 : 1, borderWidth: kind === "ghost" ? 1 : 0, borderColor: colors.primary }]}>
      <Text style={{ color: kind === "ghost" ? colors.primary : "#fff", fontWeight: "600" }}>{title}</Text>
    </Pressable>
  );
}
export const Input = (p: TextInputProps) => <TextInput placeholderTextColor={colors.muted} {...p} style={[s.input, p.style]} />;
export const Card = ({ children }: { children: React.ReactNode }) => <View style={s.card}>{children}</View>;
/*export const Screen = ({ children }: { children: React.ReactNode }) => <View style={s.screen}>{children}</View>; */
/** safeBottom: keeps the bottom of the screen above the phone's navigation bar. Use it on screens
 *  that are not inside the bottom tab bar (shop, checkout, order details). */
export const Screen = ({ children, safeBottom = false }: { children: React.ReactNode; safeBottom?: boolean }) => {
  const insets = useSafeAreaInsets();
  return <View style={[s.screen, safeBottom && { paddingBottom: 16 + Math.max(insets.bottom, 8) }]}>{children}</View>;
};
export const Muted = ({ children }: { children: React.ReactNode }) => <Text style={{ color: colors.muted, fontSize: 13 }}>{children}</Text>;
export const Err = ({ msg }: { msg: string }) => (msg ? <Text style={{ color: colors.danger, marginVertical: 4 }}>{msg}</Text> : null);

export function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress}
      style={{ height: 36, paddingHorizontal: 14, borderRadius: 18, marginRight: 8, borderWidth: 1, justifyContent: "center", alignItems: "center",
        borderColor: active ? colors.primary : colors.border, backgroundColor: active ? colors.primary : "#fff" }}>
      <Text numberOfLines={1} style={{ color: active ? "#fff" : colors.text, fontWeight: active ? "700" : "400", includeFontPadding: false }}>{label}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  btn: { paddingVertical: 12, paddingHorizontal: 16, borderRadius: 8, alignItems: "center", marginVertical: 4 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 10, backgroundColor: "#fff", marginVertical: 4, color: colors.text },
  card: { backgroundColor: colors.card, borderRadius: 10, padding: 12, marginVertical: 5, borderWidth: 1, borderColor: "#e5e7eb" },
  screen: { flex: 1, backgroundColor: colors.bg, padding: 12 },
});