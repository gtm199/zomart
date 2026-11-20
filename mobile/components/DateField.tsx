import DateTimePicker, { DateTimePickerAndroid, DateTimePickerEvent } from "@react-native-community/datetimepicker";
import { useState } from "react";
import { Modal, Platform, Pressable, Text, View } from "react-native";
import { colors } from "./ui";
import { iso, parseIso } from "../services/reportPdf";

type Props = {
  label: string;
  value: string; // YYYY-MM-DD
  onChange: (v: string) => void;
  minimumDate?: Date;
  maximumDate?: Date;
  clearable?: boolean;        // optional dates (expiry): shows "Clear", which sets ""
  placeholder?: string;       // shown when no date is chosen
};

const pretty = (s: string, placeholder = "Select date") => {
  const d = parseIso(s);
  return d ? d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : placeholder;
};

export function DateField({ label, value, onChange, minimumDate, maximumDate, clearable, placeholder }: Props) {
  const current = parseIso(value) ?? new Date();
  const [iosOpen, setIosOpen] = useState(false);
  const [iosTemp, setIosTemp] = useState(current);

  const open = () => {
    if (Platform.OS === "android") {
      DateTimePickerAndroid.open({
        value: current,
        mode: "date",
        minimumDate,
        maximumDate,
        onChange: (e: DateTimePickerEvent, d?: Date) => {
          if (e.type === "set" && d) onChange(iso(d));
        },
      });
    } else {
      setIosTemp(current);
      setIosOpen(true);
    }
  };

  return (
    <View style={{ flex: 1 }}>
      <Text style={{ color: colors.muted, fontSize: 13 }}>{label}</Text>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 2 }}>
        <Pressable
          onPress={open}
          style={{ flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 10, backgroundColor: colors.card }}
        >
          <Text style={{ color: parseIso(value) ? colors.text : colors.muted }}>📅  {pretty(value, placeholder)}</Text>
        </Pressable>
        {clearable && parseIso(value) ? (
          <Text style={{ color: colors.danger, fontWeight: "600", padding: 6 }} onPress={() => onChange("")}>Clear</Text>
        ) : null}
      </View>

      {Platform.OS === "ios" && (
        <Modal visible={iosOpen} transparent animationType="fade" onRequestClose={() => setIosOpen(false)}>
          <Pressable
            style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.35)", justifyContent: "center", padding: 16 }}
            onPress={() => setIosOpen(false)}
          >
            <Pressable style={{ backgroundColor: colors.card, borderRadius: 12, padding: 12 }} onPress={() => {}}>
              <DateTimePicker
                value={iosTemp}
                mode="date"
                display="inline"
                minimumDate={minimumDate}
                maximumDate={maximumDate}
                onChange={(_, d) => d && setIosTemp(d)}
              />
              <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 20, marginTop: 6 }}>
                <Text style={{ color: colors.muted, fontWeight: "600" }} onPress={() => setIosOpen(false)}>Cancel</Text>
                <Text
                  style={{ color: colors.primary, fontWeight: "700" }}
                  onPress={() => { onChange(iso(iosTemp)); setIosOpen(false); }}
                >
                  Done
                </Text>
              </View>
            </Pressable>
          </Pressable>
        </Modal>
      )}
    </View>
  );
}
