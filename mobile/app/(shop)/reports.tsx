import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { DateField } from "../../components/DateField";
import { api } from "../../services/api";
import { MAX_EXPORT_MONTHS, addMonths, buildReportHtml, iso, parseIso, shareReportPdf, validateExportRange } from "../../services/reportPdf";

type Range = "today" | "week" | "month";

function rangeDates(r: Range) {
  const now = new Date();
  if (r === "today") return [iso(now), iso(now)];
  if (r === "week") return [iso(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6)), iso(now)];
  return [iso(new Date(now.getFullYear(), now.getMonth(), 1)), iso(now)];
}

const Row = ({ label, value, bold }: { label: string; value: string; bold?: boolean }) => (
  <View style={{ flexDirection: "row", justifyContent: "space-between", marginVertical: 2 }}>
    <Text style={{ fontWeight: bold ? "700" : "400" }}>{label}</Text>
    <Text style={{ fontWeight: bold ? "700" : "400" }}>{value}</Text>
  </View>
);

export default function Reports() {
  const [range, setRange] = useState<Range>("month");
  const [pl, setPl] = useState<any>(null);
  const [sa, setSa] = useState<any>(null);
  const [ag, setAg] = useState<any>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    const [from, to] = rangeDates(range);
    try {
      const [a, b, c] = await Promise.all([
        api(`/shop/reports/profit-loss/?from=${from}&to=${to}`),
        api(`/shop/reports/sales-analysis/?from=${from}&to=${to}`),
        api(`/shop/reports/ageing/`),
      ]);
      setPl(a); setSa(b); setAg(c);
    } catch (e: any) { setErr(e.message); }
  }, [range]);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  
  const today = new Date();
  const [pdfFrom, setPdfFrom] = useState(iso(new Date(today.getFullYear(), today.getMonth(), 1)));
  const [pdfTo, setPdfTo] = useState(iso(today));
  const [exporting, setExporting] = useState(false);
  const [exportErr, setExportErr] = useState("");

  const todayDate = new Date(); todayDate.setHours(0, 0, 0, 0);
  const fromDate = parseIso(pdfFrom) ?? todayDate;
  const maxTo = (() => {
    const m = addMonths(fromDate, MAX_EXPORT_MONTHS);
    return m < todayDate ? m : todayDate;
  })();

  const onFromChange = (v: string) => {
    setPdfFrom(v);
    setExportErr("");
    const f = parseIso(v)!;
    const t = parseIso(pdfTo);
    const limit = addMonths(f, MAX_EXPORT_MONTHS);
    const cap = limit < todayDate ? limit : todayDate;
    if (!t || t < f) setPdfTo(v);            // To before From -> same day
    else if (t > cap) setPdfTo(iso(cap));    // beyond 3 months -> clamp
  };

  const preset = (months: number) => {
    const t = new Date();
    if (months === 1) {
      // previous calendar month
      setPdfFrom(iso(new Date(t.getFullYear(), t.getMonth() - 1, 1)));
      setPdfTo(iso(new Date(t.getFullYear(), t.getMonth(), 0)));
    } else {
      setPdfFrom(iso(addMonths(t, -months)));
      setPdfTo(iso(t));
    }
    setExportErr("");
  };

  const exportPdf = async () => {
    const msg = validateExportRange(pdfFrom, pdfTo);
    setExportErr(msg);
    if (msg) return;
    setExporting(true);
    try {
      const q = `from=${pdfFrom.trim()}&to=${pdfTo.trim()}&export=pdf`;
      const [a, b, c] = await Promise.all([
        api(`/shop/reports/profit-loss/?${q}`),
        api(`/shop/reports/sales-analysis/?${q}`),
        api(`/shop/reports/ageing/`),
      ]);
      await shareReportPdf(buildReportHtml({ from: pdfFrom.trim(), to: pdfTo.trim(), pl: a, sa: b, ag: c }),
        `Report_${pdfFrom.trim()}_to_${pdfTo.trim()}`);
    } catch (e: any) {
      setExportErr(e.message || "Could not create the PDF.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <Screen>
      <ScrollView keyboardShouldPersistTaps="handled">
        <View style={{ flexDirection: "row", gap: 6 }}>
          <Button title="Today" kind={range === "today" ? "primary" : "ghost"} onPress={() => setRange("today")} />
          <Button title="7 days" kind={range === "week" ? "primary" : "ghost"} onPress={() => setRange("week")} />
          <Button title="This month" kind={range === "month" ? "primary" : "ghost"} onPress={() => setRange("month")} />
        </View>
        <Err msg={err} />
        
        <Card>
          <Text style={{ fontWeight: "700", marginBottom: 4 }}>Export PDF</Text>
          <Muted>Pick any dates, up to {MAX_EXPORT_MONTHS} months.</Muted>
          <View style={{ flexDirection: "row", gap: 6, marginTop: 6 }}>
            <Button title="Last month" kind="ghost" onPress={() => preset(1)} />
            <Button title="Last 3 months" kind="ghost" onPress={() => preset(3)} />
          </View>
          <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
            <DateField label="From" value={pdfFrom} onChange={onFromChange} maximumDate={todayDate} />
            <DateField label="To" value={pdfTo} onChange={(v) => { setPdfTo(v); setExportErr(""); }}
              minimumDate={fromDate} maximumDate={maxTo} />
          </View>
          <Muted>Max To date for this range: {iso(maxTo)}</Muted>
          <Err msg={exportErr} />
          <Button title={exporting ? "Preparing PDF…" : "Export PDF"} onPress={exportPdf} disabled={exporting} />
        </Card>


        {pl && (
          <Card>
            <Text style={{ fontWeight: "700", marginBottom: 4 }}>Profit &amp; loss</Text>
            <Row label="Sales (after returns)" value={`₹${pl.net_sales}`} />
            <Row label="Cost of goods sold" value={`₹${pl.cost_of_goods_sold}`} />
            <Row label="Gross profit" value={`₹${pl.gross_profit}`} bold />
            <Row label="Expenses" value={`₹${pl.expenses_total}`} />
            {pl.expenses_by_category.map((e: any) => <Muted key={e.category}>   {e.category}: ₹{e.amount}</Muted>)}
            <Row label="Net profit" value={`₹${pl.net_profit}`} bold />
            <Muted>Collected: {Object.entries(pl.money_collected_by_method).map(([k, v]) => `${k.toUpperCase()} ₹${v}`).join("  ") || "nothing yet"}</Muted>
          </Card>
        )}

        {sa && (
          <>
            <Card>
              <Text style={{ fontWeight: "700", marginBottom: 4 }}>Top sellers</Text>
              {sa.top_sellers.length === 0 && <Muted>No sales in this period.</Muted>}
              {sa.top_sellers.map((p: any) => <Row key={p.product} label={`${p.product} × ${p.quantity}`} value={`₹${p.sales}`} />)}
            </Card>
            <Card>
              <Text style={{ fontWeight: "700", marginBottom: 4 }}>Not selling (in stock, no sales)</Text>
              {sa.slow_movers.length === 0 && <Muted>None.</Muted>}
              {sa.slow_movers.slice(0, 10).map((p: any) => <Row key={p.product} label={`${p.product} (${p.stock})`} value={`₹${p.stock_value_at_cost}`} />)}
            </Card>
          </>
        )}

        {ag && (
          <>
            <Card>
              <Text style={{ fontWeight: "700", marginBottom: 4 }}>Customers owe you: ₹{ag.receivables.total}</Text>
              {Object.entries(ag.receivables.buckets).map(([k, v]) => <Row key={k} label={k} value={`₹${v}`} />)}
              {ag.receivables.rows.slice(0, 8).map((r: any) => <Muted key={r.name + r.phone}>{r.name}: ₹{r.balance}</Muted>)}
            </Card>
            <Card>
              <Text style={{ fontWeight: "700", marginBottom: 4 }}>You owe suppliers: ₹{ag.payables.total}</Text>
              {Object.entries(ag.payables.buckets).map(([k, v]) => <Row key={k} label={k} value={`₹${v}`} />)}
              {ag.payables.rows.slice(0, 8).map((r: any) => <Muted key={r.name + r.phone}>{r.name}: ₹{r.balance}</Muted>)}
            </Card>
          </>
        )}
      </ScrollView>
    </Screen>
  );
}