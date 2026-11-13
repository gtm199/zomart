import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, Switch, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

type Policy = {
  enabled: boolean; keep_months: number; notify_days: number; last_run_on: string | null; minimum_months: number; archived_bills: number;
  preview: { keep_months: number; bills: number; items: number; oldest: string | null; newest: string | null };
};
type Notice = { id: number; status: string; delete_after: string; bills_count: number; items_count: number; oldest_bill: string | null; newest_bill: string | null; postponed_count: number };
type Archive = { id: number; period_from: string; period_to: string; bills_count: number; items_count: number; size_bytes: number };
type Log = { id: number; run_on: string; outcome: string; announced_bills: number; bills_archived: number; items_deleted: number; message: string };
type Page<T> = { results: T[] };

const OUTCOME: Record<string, string> = {
  nothing: "Nothing to do", announced: "Warning sent", archived: "Archived", blocked: "Cancelled for safety", error: "Error", running: "Running",
};
const day = (d: string | null) => (d ? new Date(d).toLocaleDateString("en-IN") : "-");

export default function Retention() {
  const router = useRouter();
  const { shop } = useSession();
  const isOwner = shop?.role === "owner";
  const [p, setP] = useState<Policy | null>(null);
  const [months, setMonths] = useState("");
  const [days, setDays] = useState("");
  const [notices, setNotices] = useState<Notice[]>([]);
  const [archives, setArchives] = useState<Archive[]>([]);
  const [logs, setLogs] = useState<Log[]>([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    try {
      const pol = await api<Policy>("/shop/retention/policy/");
      setP(pol); setMonths(String(pol.keep_months)); setDays(String(pol.notify_days));
      setNotices((await api<Page<Notice>>("/shop/retention/notices/")).results);
      setArchives((await api<Page<Archive>>("/shop/retention/archives/")).results);
      setLogs((await api<Page<Log>>("/shop/retention/log/")).results);
      setErr("");
    } catch (e: any) { setErr(e.message); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = async (enabled?: boolean) => {
    setErr(""); setMsg("");
    try {
      const body: Record<string, unknown> = { keep_months: Number(months), notify_days: Number(days) };
      if (enabled !== undefined) body.enabled = enabled;
      setP(await api<Policy>("/shop/retention/policy/", { method: "PATCH", body }));
      setMsg("Saved.");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const post = async (path: string, done: string) => {
    setErr(""); setMsg("");
    try {
      const r = await api<any>(path, { body: {} });
      setMsg(r?.sent ? `${done} Sent to ${r.to} (${r.bills} bills).` : done);
      load();
    } catch (e: any) { setErr(e.message); }
  };

  if (!p) return <Screen><Err msg={err} /><Muted>Loading...</Muted></Screen>;
  const open = notices.filter((n) => n.status === "announced" || n.status === "postponed");

  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        <Button title="← Back to menu" kind="ghost" onPress={() => router.navigate("/(shop)/menu")} />
        <Card>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <Text style={{ fontWeight: "700", fontSize: 16 }}>Archive old bill details</Text>
            <Switch value={p.enabled} disabled={!isOwner} onValueChange={(v) => save(v)} />
          </View>
          <Muted>
            When switched on, the item lines of bills older than the period below are saved in an archive and removed from the
            live list, after a warning. The bills' numbers, dates, totals and payments, your customers and what they owe, your
            stock and your report totals do not change. Bills with money still owed are never touched.
          </Muted>
          <Muted>Ask your accountant how long you must keep bill details before you choose a period.</Muted>
          <Muted>Keep bill details for (months, at least {p.minimum_months})</Muted>
          <Input keyboardType="number-pad" value={months} onChangeText={setMonths} editable={isOwner} />
          <Muted>Warn me this many days before (7 to 60)</Muted>
          <Input keyboardType="number-pad" value={days} onChangeText={setDays} editable={isOwner} />
          <Err msg={err} />
          {msg ? <Text style={{ color: colors.primary }}>{msg}</Text> : null}
          {isOwner ? <Button title="Save" onPress={() => save()} /> : <Muted>Only the owner can change these settings.</Muted>}
          <Muted>
            Right now {p.preview.bills} bills ({p.preview.items} item lines) are older than {p.preview.keep_months} months.
            {p.last_run_on ? ` The cleanup last ran on ${day(p.last_run_on)}.` : ""} {p.archived_bills} bills are archived so far.
          </Muted>
        </Card>

        {open.map((n) => (
          <Card key={n.id}>
            <Text style={{ fontWeight: "700", color: "#b45309" }}>Warning: archive on {day(n.delete_after)}</Text>
            <Muted>{n.bills_count} bills ({n.items_count} item lines) dated {day(n.oldest_bill)} to {day(n.newest_bill)}</Muted>
            {isOwner && (
              <>
                <Button title="Email me these bills now" onPress={() => post(`/shop/retention/notices/${n.id}/email-export/`, "Done.")} />
                {n.postponed_count < 3 && (
                  <Button title={`Postpone by 30 days (${3 - n.postponed_count} left)`} kind="ghost" onPress={() => post(`/shop/retention/notices/${n.id}/postpone/`, "Postponed.")} />
                )}
                <Muted>To stop it completely, switch the setting off at the top.</Muted>
              </>
            )}
          </Card>
        ))}

        <Text style={{ fontWeight: "700", marginTop: 8 }}>Saved archives</Text>
        {archives.length === 0 && <Muted>None yet.</Muted>}
        {archives.map((a) => (
          <Card key={a.id}>
            <Text style={{ fontWeight: "600" }}>{day(a.period_from)} to {day(a.period_to)}</Text>
            <Muted>{a.bills_count} bills · {a.items_count} item lines · {(a.size_bytes / 1024).toFixed(0)} KB</Muted>
            {isOwner && <Button title="Email me this archive" kind="ghost" onPress={() => post(`/shop/retention/archives/${a.id}/email/`, "Done.")} />}
          </Card>
        ))}

        <Text style={{ fontWeight: "700", marginTop: 8 }}>Cleanup log</Text>
        {logs.length === 0 && <Muted>The cleanup has not run yet.</Muted>}
        {logs.map((l) => (
          <Card key={l.id}>
            <Text style={{ fontWeight: "600" }}>{day(l.run_on)} · {OUTCOME[l.outcome] ?? l.outcome}</Text>
            <Muted>Named in a new warning: {l.announced_bills} · Archived: {l.bills_archived} bills · Item lines removed: {l.items_deleted}</Muted>
            {l.message ? <Muted>{l.message}</Muted> : null}
          </Card>
        ))}
      </ScrollView>
    </Screen>
  );
}