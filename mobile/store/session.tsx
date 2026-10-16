import React, { createContext, useContext, useEffect, useState } from "react";
import { api, loadStored, saveStored, setAuth } from "../services/api";
import { Session, Shop } from "../types";

type Ctx = {
  ready: boolean; session: Session | null; shop: Shop | null;
  signIn: (s: Session) => Promise<void>; signOut: () => Promise<void>; can: (cap: string) => boolean;
};
const SessionContext = createContext<Ctx>(null as unknown as Ctx);
export const useSession = () => useContext(SessionContext);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [session, setSession] = useState<Session | null>(null);

  const apply = (s: Session | null) => { setAuth(s?.token ?? null, s?.shops[0]?.id ?? null); setSession(s); };

  useEffect(() => {
    (async () => {
      const stored = await loadStored("session");
      if (stored) {
        try {
          const s: Session = JSON.parse(stored);
          setAuth(s.token, s.shops[0]?.id ?? null);
          apply(await api<Session>("/auth/me/")); // refresh roles; fails if token revoked
        } catch { apply(null); }
      }
      setReady(true);
    })();
  }, []);

  const signIn = async (s: Session) => { await saveStored("session", JSON.stringify(s)); apply(s); };
  const signOut = async () => {
    try { await api("/auth/logout/", { method: "POST", body: {} }); } catch {}
    await saveStored("session", null); apply(null);
  };
  const shop = session?.shops[0] ?? null;
  const can = (cap: string) => !!shop?.capabilities.includes(cap);
  return <SessionContext.Provider value={{ ready, session, shop, signIn, signOut, can }}>{children}</SessionContext.Provider>;
}
