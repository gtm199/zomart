import { useCallback, useMemo } from "react";
import { Pressable, ScrollView, Text } from "react-native";
import { colors } from "./ui";

export type Category = { id: number; name: string; parent: number | null; sort_order: number; product_count: number };

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={{
        paddingVertical: 8, paddingHorizontal: 14, borderRadius: 18, marginRight: 8, borderWidth: 1,
        borderColor: active ? colors.primary : colors.border, backgroundColor: active ? colors.primary : "#fff",
      }}
    >
      <Text style={{ color: active ? "#fff" : colors.text, fontWeight: active ? "700" : "400" }}>{label}</Text>
    </Pressable>
  );
}

/** Two rows of buttons: main categories, then the sub-categories of the chosen one. Empty categories are hidden. */
export default function CategoryChips(props: {
  categories: Category[];
  top: number | null;
  sub: number | null;
  onTop: (id: number | null) => void;
  onSub: (id: number | null) => void;
}) {
  const { categories, top, sub, onTop, onSub } = props;
  const childrenOf = useCallback((id: number) => categories.filter((c) => c.parent === id), [categories]);
  const total = useCallback((c: Category) => c.product_count + childrenOf(c.id).reduce((a, k) => a + k.product_count, 0), [childrenOf]);
  const tops = useMemo(() => categories.filter((c) => c.parent === null && total(c) > 0), [categories, total]);
  const subs = useMemo(() => (top ? childrenOf(top).filter((c) => c.product_count > 0) : []), [top, childrenOf]);

  if (tops.length === 0) return null;
  return (
    <>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0, marginVertical: 4 }}>
        <Chip label="All" active={top === null} onPress={() => onTop(null)} />
        {tops.map((c) => (
          <Chip key={c.id} label={`${c.name} (${total(c)})`} active={top === c.id} onPress={() => onTop(c.id)} />
        ))}
      </ScrollView>
      {subs.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0, marginBottom: 4 }}>
          <Chip label="All in this group" active={sub === null} onPress={() => onSub(null)} />
          {subs.map((c) => (
            <Chip key={c.id} label={`${c.name} (${c.product_count})`} active={sub === c.id} onPress={() => onSub(c.id)} />
          ))}
        </ScrollView>
      )}
    </>
  );
}