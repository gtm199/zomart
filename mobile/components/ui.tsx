import React, { useRef, useState } from "react";
import { KeyboardAvoidingView, Pressable, StyleSheet, Text, TextInput, TextInputProps, View } from "react-native";

export const colors = { primary: "#0f766e", bg: "#f6f7f8", card: "#fff", text: "#111827", muted: "#6b7280", danger: "#b91c1c", border: "#d1d5db" };

export function Button({ title, onPress, kind = "primary", disabled }: { title: string; onPress: () => void; kind?: "primary" | "ghost" | "danger"; disabled?: boolean }) {
  const bg = kind === "primary" ? colors.primary : kind === "danger" ? colors.danger : "transparent";
  return (
    <Pressable onPress={onPress} disabled={disabled} style={[s.btn, { backgroundColor: bg, opacity: disabled ? 0.5 : 1, borderWidth: kind === "ghost" ? 1 : 0, borderColor: colors.primary }]}>
      <Text style={{ color: kind === "ghost" ? colors.primary : "#fff", fontWeight: "600" }}>{title}</Text>
    </Pressable>
  );
}
export const Input = (p: TextInputProps) => <TextInput placeholderTextColor={colors.muted} {...p} style={[s.input, p.style]} />;
export const Card = ({ children }: { children: React.ReactNode }) => <View style={s.card}>{children}</View>;
export const Screen = ({ children }: { children: React.ReactNode }) => <View style={s.screen}>{children}</View>;
export const Muted = ({ children }: { children: React.ReactNode }) => <Text style={{ color: colors.muted, fontSize: 13 }}>{children}</Text>;
export const Err = ({ msg }: { msg: string }) => (msg ? <Text style={{ color: colors.danger, marginVertical: 4 }}>{msg}</Text> : null);

/** Put this around the scrolling part of a screen. The keyboard then pushes the content up instead of covering it. */
export function KeyboardAware({ children }: { children: React.ReactNode }) {
  const ref = useRef<View>(null);
  const [top, setTop] = useState(0); // how far this area is from the top of the phone's screen
  return (
    <View ref={ref} style={{ flex: 1 }} onLayout={() => ref.current?.measureInWindow((_x, y) => setTop(y))}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior="padding" keyboardVerticalOffset={top}>
        {children}
      </KeyboardAvoidingView>
    </View>
  );
}
const s = StyleSheet.create({
  btn: { paddingVertical: 12, paddingHorizontal: 16, borderRadius: 8, alignItems: "center", marginVertical: 4 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 10, backgroundColor: "#fff", marginVertical: 4, color: colors.text },
  card: { backgroundColor: colors.card, borderRadius: 10, padding: 12, marginVertical: 5, borderWidth: 1, borderColor: "#e5e7eb" },
  screen: { flex: 1, backgroundColor: colors.bg, padding: 12 },
});
