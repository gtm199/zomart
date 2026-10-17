import React, { createContext, useContext, useEffect, useState } from "react";
import { Alert } from "react-native";
import { api, loadStored, saveStored, setAuth } from "../services/api";
import { clearAll, pendingCount, prepareLocalDb } from "../services/localdb";
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
        const saved: Session = JSON.parse(stored);
        setAuth(saved.token, saved.shops[0]?.id ?? null);
        try {
          const fresh = await api<Session>("/auth/me/"); // refresh roles
          await prepareLocalDb(fresh.shops[0]?.id ?? 0);
          await saveStored("session", JSON.stringify(fresh));
          apply(fresh);
        } catch (e: any) {
          if (e?.status === 401) apply(null); // token revoked: sign in again
          else { await prepareLocalDb(saved.shops[0]?.id ?? 0); apply(saved); } // no internet: keep working
        }
      }
      setReady(true);
    })();
  }, []);

  const signIn = async (s: Session) => {
    await saveStored("session", JSON.stringify(s));
    await prepareLocalDb(s.shops[0]?.id ?? 0);
    apply(s);
  };

  const signOut = async () => {
    const waiting = await pendingCount();
    if (waiting > 0) {
      Alert.alert(
        "Bills not uploaded yet",
        `${waiting} bill(s) have not reached the server. Connect to the internet and wait for them to upload, or discard them in Menu > Offline & sync, before signing out.`
      );
      return;
    }
    try { await api("/auth/logout/", { method: "POST", body: {} }); } catch {}
    await clearAll();
    await saveStored("session", null);
    apply(null);
  };

  const shop = session?.shops[0] ?? null;
  const can = (cap: string) => !!shop?.capabilities.includes(cap);
  return <SessionContext.Provider value={{ ready, session, shop, signIn, signOut, can }}>{children}</SessionContext.Provider>;
}
