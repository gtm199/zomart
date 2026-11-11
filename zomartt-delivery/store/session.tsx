import React, { createContext, useContext, useEffect, useState } from "react";
import { api, keep, setAuth } from "../services/api";
import { stopTracking } from "../services/tracking";

export type Shop = { id: number; name: string; role: string };
type Ctx = {
  ready: boolean; signedIn: boolean; name: string; shops: Shop[]; shop: Shop | null;
  signIn: (username: string, password: string) => Promise<void>;
  chooseShop: (id: number) => Promise<void>;
  signOut: () => Promise<void>;
};
const SessionContext = createContext<Ctx>(null as unknown as Ctx);
export const useSession = () => useContext(SessionContext);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [name, setName] = useState("");
  const [shops, setShops] = useState<Shop[]>([]);
  const [shop, setShop] = useState<Shop | null>(null);

  useEffect(() => {
    (async () => {
      const [t, list, sid, n] = await Promise.all([keep.get("token"), keep.get("shops"), keep.get("shop"), keep.get("name")]);
      if (t && list && sid) {
        const all: Shop[] = JSON.parse(list);
        const current = all.find((s) => String(s.id) === sid) ?? all[0];
        setAuth(t, current.id);
        setShops(all); setShop(current); setName(n ?? ""); setSignedIn(true);
      }
      setReady(true);
    })();
  }, []);

  const signIn = async (username: string, password: string) => {
    setAuth(null, null);
    const r = await api<{ token: string; user: { full_name: string; username: string }; shops: Shop[] }>("/auth/login/", { body: { username, password } });
    const mine = r.shops.filter((s) => s.role === "delivery");
    if (mine.length === 0) throw new Error("This login is not a delivery account. Ask the shop owner to add you as delivery staff.");
    const first = mine[0];
    setAuth(r.token, first.id);
    await keep.set("token", r.token);
    await keep.set("shops", JSON.stringify(mine));
    await keep.set("shop", String(first.id));
    await keep.set("name", r.user.full_name || r.user.username);
    setShops(mine); setShop(first); setName(r.user.full_name || r.user.username); setSignedIn(true);
  };

  const chooseShop = async (id: number) => {
    const s = shops.find((x) => x.id === id);
    if (!s) return;
    setAuth((await keep.get("token")) ?? null, s.id);
    await keep.set("shop", String(s.id));
    setShop(s);
  };

  const signOut = async () => {
    await stopTracking();
    try { await api("/auth/logout/", { method: "POST", body: {} }); } catch {}
    setAuth(null, null);
    for (const k of ["token", "shops", "shop", "name", "tripOrder"]) await keep.del(k);
    setSignedIn(false); setShops([]); setShop(null); setName("");
  };

  return <SessionContext.Provider value={{ ready, signedIn, name, shops, shop, signIn, chooseShop, signOut }}>{children}</SessionContext.Provider>;
}