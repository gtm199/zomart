import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, Switch, Text, View } from "react-native";
import { Button, Card, Err, Input, Muted, Screen, colors } from "../../components/ui";
import { api } from "../../services/api";
import { useSession } from "../../store/session";

type Policy = {
  enabled: boolean; keep_months: number; notify_days: number; clean_bills: boolean; clean_notifications: boolean;
  notification_days: number; clean_audit: boolean; audit_months: number; clean_orders: boolean; orders_months: number;
  last_run_on: string | null; audit_available: boolean; archived_bills: number; archived_orders: number;
  minimums: { bills_months: number; audit_months: number; orders_months: number; notification_days: number };
  preview: { bills: number; items: number; keep_months: number; notifications: number; audit: number | null; orders: number };
};
type Form = {
  enabled: boolean; clean_notifications: boolean; notification_days: string; clean_audit: boolean; audit_months: string;
  clean_orders: boolean; orders_months: string; clean_bills: boolean; keep_months: string; notify_days: string;
};
type Notice = { id: number; category: string; status: string; delete_after: string; bills_count: number; items_count: number; oldest_bill: string | null; newest_bill: string | null; postponed_count: number };
type Item = { key: string; title: string; sub: string; path: string };
type Log = { id: number; category: string; run_on: string; outcome: string; announced_bills: number; bills_archived: number; items_deleted: number; rows_archived: number; rows_deleted: number; message: string };
type Page<T> = { results: T[] };

const CAT: Record<string, string> = { bills: "Bill details", orders: "Online orders", audit: "Change history", notifications: "Notifications", logs: "System logs" };
const OUTCOME: Record<string, string> = {
  nothing: "Nothing to do", announced: "Warning sent", archived: "Archived", cleaned: "Deleted", blocked: "Cancelled for safety",
  skipped: "Skipped", error: "Error", running: "Running",
};
const day = (d: string | null) => (d ? new Date(d).toLocaleDateString("en-IN") : "-");

function Section(props: { title: string; on: boolean; disabled: boolean; onToggle: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <Card>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={{ fontWeight: "700", flex: 1 }}>{props.title}</Text>
        <Switch value={props.on} disabled={props.disabled} onValueChange={props.onToggle} />
      </View>
      {props.children}
    </Card>
  );
}

export default function Retention() {
  const router = useRouter();
  const { shop } = useSession();
  const isOwner = shop?.role === "owner";
  const [p, setP] = useState<Policy | null>(null);
  const [f, setF] = useState<Form | null>(null);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [logs, setLogs] = useState<Log[]>([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const fill = (pol: Policy) => {
    setP(pol);
    setF({
      enabled: pol.enabled, clean_notifications: pol.clean_notifications, notification_days: String(pol.notification_days),
      clean_audit: pol.clean_audit, audit_months: String(pol.audit_months), clean_orders: pol.clean_orders,
      orders_months: String(pol.orders_months), clean_bills: pol.clean_bills, keep_months: String(pol.keep_months),
      notify_days: String(pol.notify_days),
    });
  };

  const load = useCallback(async () => {
    try {
      fill(await api<Policy>("/shop/retention/policy/"));
      setNotices((await api<Page<Notice>>("/shop/retention/notices/")).results);
      const bills = (await api<Page<any>>("/shop/retention/archives/")).results.map((a: any): Item => ({
        key: `b${a.id}`, title: `Bill details · ${day(a.period_from)} to ${day(a.period_to)}`,
        sub: `${a.bills_count} bills · ${a.items_count} item lines · ${(a.size_bytes / 1024).toFixed(0)} KB`, path: `/shop/retention/archives/${a.id}/email/`,
      }));
      const data = (await api<Page<any>>("/shop/retention/data-archives/")).results.map((a: any): Item => ({
        key: `d${a.id}`, title: `${CAT[a.category] ?? a.category} · ${day(a.period_from)} to ${day(a.period_to)}`,
        sub: `${a.rows_count} records · ${(a.size_bytes / 1024).toFixed(0)} KB`, path: `/shop/retention/data-archives/${a.id}/email/`,
      }));
      setItems([...bills, ...data]);
      setLogs((await api<Page<Log>>("/shop/retention/log/")).results);
      setErr("");
    } catch (e: any) { setErr(e.message); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = async (override: Partial<Form> = {}) => {
    if (!f) return;
    const g = { ...f, ...override };
    setErr(""); setMsg("");
    try {
      fill(await api<Policy>("/shop/retention/policy/", {
        method: "PATCH",
        body: {
          enabled: g.enabled, clean_notifications: g.clean_notifications, notification_days: Number(g.notification_days),
          clean_audit: g.clean_audit, audit_months: Number(g.audit_months), clean_orders: g.clean_orders,
          orders_months: Number(g.orders_months), clean_bills: g.clean_bills, keep_months: Number(g.keep_months),
          notify_days: Number(g.notify_days),
        },
      }));
      setMsg("Saved.");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const post = async (path: string, done: string) => {
    setErr(""); setMsg("");
    try {
      const r = await api<any>(path, { body: {} });
      setMsg(r?.sent ? `${done} Sent to ${r.to} (${r.bills} records).` : done);
      load();
    } catch (e: any) { setErr(e.message); }
  };

  if (!p || !f) return <Screen><Err msg={err} /><Muted>Loading...</Muted></Screen>;
  const set = (k: keyof Form) => (v: string) => setF({ ...f, [k]: v });
  const open = notices.filter((n) => n.status === "announced" || n.status === "postponed");
  const lock = !isOwner;

  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        <Button title="← Back to menu" kind="ghost" onPress={() => router.navigate("/(shop)/menu")} />

        <Card>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <Text style={{ fontWeight: "700", fontSize: 16, flex: 1 }}>Automatic cleanup of old data</Text>
            <Switch value={f.enabled} disabled={lock} onValueChange={(v) => { setF({ ...f, enabled: v }); save({ enabled: v }); }} />
          </View>
          <Muted>
            Runs once a day. Bills, customers, what customers owe, stock and your report totals are never deleted. Choose below
            what to clean. Anything that is archived is copied first, and you get a warning before it happens.
          </Muted>
          <Muted>Ask your accountant how long you must keep records before you choose the periods.</Muted>
          {p.last_run_on ? <Muted>The cleanup last ran on {day(p.last_run_on)}.</Muted> : null}
        </Card>

        <Section title="Notifications" on={f.clean_notifications} disabled={lock} onToggle={(v) => setF({ ...f, clean_notifications: v })}>
          <Muted>Deleted after this many days (at least {p.minimums.notification_days}). No archive, no warning.</Muted>
          <Input keyboardType="number-pad" value={f.notification_days} onChangeText={set("notification_days")} editable={!lock} />
          <Muted>Right now {p.preview.notifications} notifications are older than that.</Muted>
        </Section>

        {p.audit_available && (
          <Section title="Change history (who changed prices, stock, credit limits)" on={f.clean_audit} disabled={lock} onToggle={(v) => setF({ ...f, clean_audit: v })}>
            <Muted>Archived, then deleted, after this many months (at least {p.minimums.audit_months}).</Muted>
            <Input keyboardType="number-pad" value={f.audit_months} onChangeText={set("audit_months")} editable={!lock} />
            <Muted>Right now {p.preview.audit ?? 0} entries are older than that.</Muted>
          </Section>
        )}

        <Section title="Finished online orders" on={f.clean_orders} disabled={lock} onToggle={(v) => setF({ ...f, clean_orders: v })}>
          <Muted>
            Delivered, cancelled and declined orders are archived, then deleted, after this many months (at least {p.minimums.orders_months}).
            Customers will no longer see them in their app. Orders still in progress, orders you marked "Keep this order", and
            orders linked to a bill with money owed are never touched.
          </Muted>
          <Input keyboardType="number-pad" value={f.orders_months} onChangeText={set("orders_months")} editable={!lock} />
          <Muted>Right now {p.preview.orders} orders are older than that. {p.archived_orders} are archived so far.</Muted>
        </Section>

        <Section title="Bill item details" on={f.clean_bills} disabled={lock} onToggle={(v) => setF({ ...f, clean_bills: v })}>
          <Muted>
            The item lines of old bills are archived and removed. The bills' numbers, dates, totals and payments stay. Bills with
            money still owed are never touched. Keep for (months, at least {p.minimums.bills_months}):
          </Muted>
          <Input keyboardType="number-pad" value={f.keep_months} onChangeText={set("keep_months")} editable={!lock} />
          <Muted>Right now {p.preview.bills} bills ({p.preview.items} item lines) are older than that. {p.archived_bills} bills are archived so far.</Muted>
        </Section>

        <Card>
          <Muted>Warn me this many days before anything is archived (7 to 60):</Muted>
          <Input keyboardType="number-pad" value={f.notify_days} onChangeText={set("notify_days")} editable={!lock} />
          <Err msg={err} />
          {msg ? <Text style={{ color: colors.primary }}>{msg}</Text> : null}
          {isOwner ? <Button title="Save" onPress={() => save()} /> : <Muted>Only the owner can change these settings.</Muted>}
        </Card>

        {open.map((n) => (
          <Card key={n.id}>
            <Text style={{ fontWeight: "700", color: "#b45309" }}>{CAT[n.category]}: archive on {day(n.delete_after)}</Text>
            <Muted>{n.bills_count} records ({n.items_count} detail lines) dated {day(n.oldest_bill)} to {day(n.newest_bill)}</Muted>
            {isOwner && (
              <>
                <Button title="Email me these records now" onPress={() => post(`/shop/retention/notices/${n.id}/email-export/`, "Done.")} />
                {n.postponed_count < 3 && (
                  <Button title={`Postpone by 30 days (${3 - n.postponed_count} left)`} kind="ghost" onPress={() => post(`/shop/retention/notices/${n.id}/postpone/`, "Postponed.")} />
                )}
                <Muted>To stop it completely, switch that cleanup off above and save.</Muted>
              </>
            )}
          </Card>
        ))}

        <Text style={{ fontWeight: "700", marginTop: 8 }}>Saved archives</Text>
        {items.length === 0 && <Muted>None yet.</Muted>}
        {items.map((a) => (
          <Card key={a.key}>
            <Text style={{ fontWeight: "600" }}>{a.title}</Text>
            <Muted>{a.sub}</Muted>
            {isOwner && <Button title="Email me this archive" kind="ghost" onPress={() => post(a.path, "Done.")} />}
          </Card>
        ))}

        <Text style={{ fontWeight: "700", marginTop: 8 }}>Cleanup log</Text>
        {logs.length === 0 && <Muted>The cleanup has not run yet.</Muted>}
        {logs.map((l) => (
          <Card key={l.id}>
            <Text style={{ fontWeight: "600" }}>{day(l.run_on)} · {CAT[l.category] ?? l.category} · {OUTCOME[l.outcome] ?? l.outcome}</Text>
            {l.category === "notifications" || l.category === "logs" ? (
              <Muted>Deleted: {l.rows_deleted}</Muted>
            ) : l.category === "bills" ? (
              <Muted>Named in a new warning: {l.announced_bills} · Archived: {l.bills_archived} bills · Item lines removed: {l.items_deleted}</Muted>
            ) : (
              <Muted>Named in a new warning: {l.announced_bills} · Archived: {l.rows_archived} · Removed: {l.rows_deleted}</Muted>
            )}
            {l.message ? <Muted>{l.message}</Muted> : null}
          </Card>
        ))}
      </ScrollView>
    </Screen>
  );
}