import React, { createContext, useContext, useEffect, useState } from "react";
import { api, keep, setToken } from "../services/api";

export type Shopper = { id: number; name: string; phone: string };
type Ctx = { ready: boolean; shopper: Shopper | null; signIn: (p: { token: string; shopper: Shopper }) => Promise<void>; signOut: () => Promise<void> };
const SessionContext = createContext<Ctx>(null as unknown as Ctx);
export const useSession = () => useContext(SessionContext);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [shopper, setShopper] = useState<Shopper | null>(null);

  useEffect(() => {
    (async () => {
      const t = await keep.get("token");
      const saved = await keep.get("shopper");
      if (t && saved) {
        setToken(t);
        try { setShopper(await api<Shopper>("/store/auth/me/")); }
        catch (e: any) {
          if (e?.status === 401) { setToken(null); await keep.del("token"); await keep.del("shopper"); }
          else setShopper(JSON.parse(saved)); // no internet: stay signed in
        }
      }
      setReady(true);
    })();
  }, []);

  const signIn = async (p: { token: string; shopper: Shopper }) => {
    setToken(p.token);
    await keep.set("token", p.token);
    await keep.set("shopper", JSON.stringify(p.shopper));
    setShopper(p.shopper);
  };
  const signOut = async () => {
    try { await api("/store/auth/logout/", { method: "POST", body: {} }); } catch {}
    setToken(null);
    await keep.del("token");
    await keep.del("shopper");
    setShopper(null);
  };
  return <SessionContext.Provider value={{ ready, shopper, signIn, signOut }}>{children}</SessionContext.Provider>;
}