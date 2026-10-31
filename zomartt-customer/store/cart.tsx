import React, { createContext, useContext, useState } from "react";
import { Alert } from "react-native";

export type Line = { id: number; name: string; price: string; unit: string; loose: boolean; qty: number };
export type CartShop = { id: number; name: string };
type Ctx = {
  shop: CartShop | null; lines: Line[]; total: number;
  setQty: (shop: CartShop, p: Omit<Line, "qty">, qty: number) => void; clear: () => void; qtyOf: (id: number) => number;
};
const CartContext = createContext<Ctx>(null as unknown as Ctx);
export const useCart = () => useContext(CartContext);

export const lineCents = (price: string, qty: number) => Math.round(Number(price) * 100 * qty);

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [shop, setShop] = useState<CartShop | null>(null);
  const [lines, setLines] = useState<Line[]>([]);

  const apply = (s: CartShop, p: Omit<Line, "qty">, qty: number) => {
    setShop(s);
    setLines((prev) => {
      const rest = prev.filter((l) => l.id !== p.id);
      return qty > 0 ? [...rest, { ...p, qty }] : rest;
    });
  };
  const setQty = (s: CartShop, p: Omit<Line, "qty">, qty: number) => {
    if (shop && shop.id !== s.id && lines.length > 0) {
      Alert.alert("Start a new basket?", `Your basket has items from ${shop.name}. Adding from ${s.name} will empty it.`, [
        { text: "Keep my basket", style: "cancel" },
        { text: "Start new basket", onPress: () => { setLines([]); apply(s, p, qty); } },
      ]);
      return;
    }
    apply(s, p, Math.round(qty * 1000) / 1000);
  };
  const clear = () => { setLines([]); setShop(null); };
  const total = lines.reduce((a, l) => a + lineCents(l.price, l.qty), 0) / 100;
  const qtyOf = (id: number) => lines.find((l) => l.id === id)?.qty ?? 0;
  return <CartContext.Provider value={{ shop, lines, total, setQty, clear, qtyOf }}>{children}</CartContext.Provider>;
}