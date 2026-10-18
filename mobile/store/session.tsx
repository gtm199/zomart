import React, { createContext, useContext, useEffect, useState } from "react";
import { Alert } from "react-native";
import { api, loadStored, saveStored, setAuth } from "../services/api";
import { clearAll, pendingCount, prepareLocalDb } from "../services/localdb";
import { Session, Shop } from "../types";

type Ctx = {
  ready: boolean; session: Session | null; shop: Shop | null; shops: Shop[];
  signIn: (s: Session) => Promise<void>; signOut: () => Promise<void>;
  refresh: () => Promise<void>; switchShop: (id: number) => Promise<void>; can: (cap: string) => boolean;
};
const SessionContext = createContext<Ctx>(null as unknown as Ctx);
export const useSession = () => useContext(SessionContext);

const pickShop = (s: Session, stored: string | null) => {
  const id = Number(stored);
  return s.shops.find((x) => x.id === id)?.id ?? s.shops[0]?.id ?? 0;
};

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [activeId, setActiveId] = useState<number>(0);

  const apply = (s: Session | null, id = 0) => { setAuth(s?.token ?? null, id || null); setSession(s); setActiveId(id); };

  useEffect(() => {
    (async () => {
      const stored = await loadStored("session");
      if (stored) {
        const saved: Session = JSON.parse(stored);
        const storedShop = await loadStored("active_shop");
        setAuth(saved.token, pickShop(saved, storedShop) || null);
        try {
          const fresh = await api<Session>("/auth/me/"); // refresh roles and approval
          const id = pickShop(fresh, storedShop);
          await prepareLocalDb(id);
          await saveStored("session", JSON.stringify(fresh));
          apply(fresh, id);
        } catch (e: any) {
          if (e?.status === 401) apply(null);
          else { const id = pickShop(saved, storedShop); await prepareLocalDb(id); apply(saved, id); } // no internet: keep working
        }
      }
      setReady(true);
    })();
  }, []);

  const signIn = async (s: Session) => {
    const id = pickShop(s, null);
    await saveStored("session", JSON.stringify(s));
    await saveStored("active_shop", String(id));
    await prepareLocalDb(id);
    apply(s, id);
  };

  const refresh = async () => {
    const fresh = await api<Session>("/auth/me/");
    await saveStored("session", JSON.stringify(fresh));
    apply(fresh, pickShop(fresh, String(activeId)));
  };

  const blockedByPending = async () => {
    const waiting = await pendingCount();
    if (waiting > 0) {
      Alert.alert(
        "Bills not uploaded yet",
        `${waiting} bill(s) have not reached the server. Connect to the internet and wait for them to upload, or discard them in Menu > Offline & sync, first.`
      );
      return true;
    }
    return false;
  };

  const switchShop = async (id: number) => {
    if (!session || id === activeId) return;
    if (await blockedByPending()) return;
    await prepareLocalDb(id); // the phone's offline copy belongs to one shop at a time
    await saveStored("active_shop", String(id));
    setAuth(session.token, id);
    setActiveId(id);
  };

  const signOut = async () => {
    if (await blockedByPending()) return;
    try { await api("/auth/logout/", { method: "POST", body: {} }); } catch {}
    await clearAll();
    await saveStored("session", null);
    await saveStored("active_shop", null);
    apply(null);
  };

  const shops = session?.shops ?? [];
  const shop = shops.find((s) => s.id === activeId) ?? shops[0] ?? null;
  const can = (cap: string) => !!shop?.capabilities.includes(cap);
  return (
    <SessionContext.Provider value={{ ready, session, shop, shops, signIn, signOut, refresh, switchShop, can }}>
      {children}
    </SessionContext.Provider>
  );
}
