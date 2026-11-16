import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { Button, Card, Err, Muted, Screen, colors } from "../../components/ui";
import { DateField } from "../../components/DateField";
import { api } from "../../services/api";
import { kvGet, kvSet } from "../../services/localdb";
import {
  GST_REPORT_DISCLAIMER, MAX_EXPORT_MONTHS, addMonths, buildGstReportHtml, buildReportHtml, financialYear, iso, parseIso,
  shareReportPdf, validateExportRange,
} from "../../services/reportPdf";
import { useSession } from "../../store/session";

type Limits = {
  gst_enabled: boolean; max_export_months: number; max_range_days: number; gst_report_max_months: number;
  gst_amount_switch?: boolean;   // the server offers the with/without GST switch only where GST is collected
};
type Amounts = "incl" | "excl";

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
  const { can } = useSession();
  const [range, setRange] = useState<Range>("month");
  const [limits, setLimits] = useState<Limits | null>(null);   // the server decides; the app only shows it
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
  useFocusEffect(useCallback(() => { api<Limits>("/shop/reports/limits/").then(setLimits).catch(() => {}); }, []));
  const maxMonths = limits?.max_export_months ?? MAX_EXPORT_MONTHS;

  // ---------- amounts with or without GST (remembered on this phone) ----------
  const [amounts, setAmounts] = useState<Amounts>("incl");
  useFocusEffect(useCallback(() => { kvGet("report_amounts").then((v) => { if (v === "excl" || v === "incl") setAmounts(v); }).catch(() => {}); }, []));
  const showSwitch = !!limits?.gst_amount_switch;
  const exTax = showSwitch && amounts === "excl";      // shops without the switch keep today's view
  const chooseAmounts = (a: Amounts) => { setAmounts(a); kvSet("report_amounts", a).catch(() => {}); };
  const sales = (r: any) => (exTax ? r.sales_ex_tax ?? r.sales : r.sales);
  
  const today = new Date();
  const [pdfFrom, setPdfFrom] = useState(iso(new Date(today.getFullYear(), today.getMonth(), 1)));
  const [pdfTo, setPdfTo] = useState(iso(today));
  const [exporting, setExporting] = useState(false);
  const [exportErr, setExportErr] = useState("");

  const todayDate = new Date(); todayDate.setHours(0, 0, 0, 0);
  const fromDate = parseIso(pdfFrom) ?? todayDate;
  const maxTo = (() => {
    const m = addMonths(fromDate, maxMonths);
    return m < todayDate ? m : todayDate;
  })();

  const onFromChange = (v: string) => {
    setPdfFrom(v);
    setExportErr("");
    const f = parseIso(v)!;
    const t = parseIso(pdfTo);
    const limit = addMonths(f, maxMonths);
    const cap = limit < todayDate ? limit : todayDate;
    if (!t || t < f) setPdfTo(v);            // To before From -> same day
    else if (t > cap) setPdfTo(iso(cap));    // beyond the allowed months -> clamp
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

  // ---------- GST report (owner / manager, GST shops) ----------
  const showGst = can("view_gst_reports") && !!limits?.gst_enabled;
  const gstMax = limits?.gst_report_max_months || 12;
  const [gFrom, setGFrom] = useState(iso(financialYear(new Date())[0]));
  const [gTo, setGTo] = useState(iso(new Date()));
  const [gst, setGst] = useState<any>(null);
  const [gErr, setGErr] = useState("");
  const [gBusy, setGBusy] = useState(false);
  const gFromDate = parseIso(gFrom) ?? todayDate;
  const gMaxTo = (() => { const m = addMonths(gFromDate, gstMax); return m < todayDate ? m : todayDate; })();

  const gPreset = (kind: "fy" | "lastfy" | "lastmonth") => {
    const t = new Date();
    if (kind === "lastmonth") { setGFrom(iso(new Date(t.getFullYear(), t.getMonth() - 1, 1))); setGTo(iso(new Date(t.getFullYear(), t.getMonth(), 0))); }
    else {
      const [a, b] = financialYear(t, kind === "fy" ? 0 : -1);
      setGFrom(iso(a)); setGTo(iso(b < todayDate ? b : todayDate));
    }
    setGst(null); setGErr("");
  };
  const loadGst = async (andPdf = false) => {
    const msg = validateExportRange(gFrom, gTo, gstMax);
    setGErr(msg);
    if (msg) return;
    setGBusy(true);
    try {
      const r = await api<any>(`/shop/reports/gst/?from=${gFrom}&to=${gTo}`);
      setGst(r);
      if (andPdf) await shareReportPdf(buildGstReportHtml(r), `GST_report_${gFrom}_to_${gTo}`);
    } catch (e: any) { setGErr(e.message || "Could not load the GST report."); } finally { setGBusy(false); }
  };

  const exportPdf = async () => {
    const msg = validateExportRange(pdfFrom, pdfTo, maxMonths);
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
      await shareReportPdf(buildReportHtml({ from: pdfFrom.trim(), to: pdfTo.trim(), pl: a, sa: b, ag: c,
        exTax: showSwitch ? exTax : undefined }),
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

        {showSwitch && (
          <Card>
            <Text style={{ fontWeight: "700", marginBottom: 4 }}>Show sales amounts</Text>
            <View style={{ flexDirection: "row", gap: 6 }}>
              <Button title="Including GST" kind={amounts === "incl" ? "primary" : "ghost"} onPress={() => chooseAmounts("incl")} />
              <Button title="Excluding GST" kind={amounts === "excl" ? "primary" : "ghost"} onPress={() => chooseAmounts("excl")} />
            </View>
            <Muted>
              {exTax ? "Taxable value: your turnover without the GST you collected." : "What customers paid, GST included."}
              {" "}Profit is always worked out without GST (GST collected is owed to the government, not income).
            </Muted>
          </Card>
        )}

        <Card>
          <Text style={{ fontWeight: "700", marginBottom: 4 }}>Export PDF</Text>
          <Muted>Pick any dates, up to {maxMonths} months.</Muted>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
            <Button title="Last month" kind="ghost" onPress={() => preset(1)} />
            <Button title="Last 3 months" kind="ghost" onPress={() => preset(3)} />
            {maxMonths >= 12 && <Button title="Last 12 months" kind="ghost" onPress={() => preset(12)} />}
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


        {showGst && (
          <Card>
            <Text style={{ fontWeight: "700", marginBottom: 4 }}>GST report</Text>
            <Muted>Up to {gstMax} months (a full financial year). Sales by day or month, GST by rate, HSN-wise, credit notes, B2B invoices.</Muted>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
              <Button title="This financial year" kind="ghost" onPress={() => gPreset("fy")} />
              <Button title="Last financial year" kind="ghost" onPress={() => gPreset("lastfy")} />
              <Button title="Last month" kind="ghost" onPress={() => gPreset("lastmonth")} />
            </View>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
              <DateField label="From" value={gFrom} onChange={(v) => {
                setGFrom(v); setGst(null); setGErr("");
                const f = parseIso(v)!; const t = parseIso(gTo);
                const cap = (() => { const m = addMonths(f, gstMax); return m < todayDate ? m : todayDate; })();
                if (!t || t < f) setGTo(v); else if (t > cap) setGTo(iso(cap));
              }} maximumDate={todayDate} />
              <DateField label="To" value={gTo} onChange={(v) => { setGTo(v); setGst(null); setGErr(""); }}
                minimumDate={gFromDate} maximumDate={gMaxTo} />
            </View>
            <Err msg={gErr} />
            <Button title={gBusy ? "Loading…" : "Show GST summary"} onPress={() => loadGst(false)} disabled={gBusy} />
            <Button title={gBusy ? "Preparing PDF…" : "GST report PDF"} kind="ghost" onPress={() => loadGst(true)} disabled={gBusy} />
            {gst && (
              <>
                <Row label={`Invoices (${gst.invoices.count}) ${exTax ? "excl." : "incl."} GST`}
                  value={`₹${exTax ? gst.invoices.taxable : gst.invoices.total}`} bold />
                {exTax
                  ? <Row label="Value incl. GST" value={`₹${gst.invoices.total}`} />
                  : <Row label="Taxable value" value={`₹${gst.invoices.taxable}`} />}
                <Row label="CGST + SGST" value={`₹${gst.invoices.cgst} + ₹${gst.invoices.sgst}`} />
                {Number(gst.invoices.igst) > 0 && <Row label="IGST" value={`₹${gst.invoices.igst}`} />}
                <Row label={`Credit notes (${gst.credit_notes.count})`} value={`-₹${exTax ? gst.credit_notes.taxable : gst.credit_notes.total}`} />
                <Row label="Net tax" value={`₹${gst.net.tax}`} bold />
                {gst.by_rate.map((r: any) => (
                  <Muted key={r.rate}>   {r.rate}%: {exTax ? `taxable ₹${r.taxable}` : `value ₹${r.value}`}, tax ₹{r.tax}</Muted>
                ))}
                <Row label={`Purchases (${gst.purchases.count}) ${exTax ? "excl." : "incl."} GST`}
                  value={`₹${exTax ? (Number(gst.purchases.value) - Number(gst.purchases.gst)).toFixed(2) : gst.purchases.value}`} />
                <Row label="GST recorded on purchases" value={`₹${gst.purchases.gst}`} />
                {gst.items_missing > 0 && <Text style={{ color: colors.danger }}>{gst.items_missing} bill(s) have no item details; rate/HSN tables leave them out.</Text>}
              </>
            )}
            <Text style={{ color: "#b45309", marginTop: 6 }}>{GST_REPORT_DISCLAIMER}</Text>
          </Card>
        )}

        {pl && (
          <Card>
            <Text style={{ fontWeight: "700", marginBottom: 4 }}>Profit &amp; loss</Text>
            <Row label={showSwitch ? `Sales after returns (${exTax ? "excl." : "incl."} GST)` : "Sales (after returns)"}
              value={`₹${exTax ? pl.sales_excluding_tax : pl.net_sales}`} />
            {showSwitch && <Muted>{exTax ? `GST collected (not income): ₹${pl.tax_included_in_sales}` : `of which GST: ₹${pl.tax_included_in_sales}`}</Muted>}
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
              {sa.top_sellers.map((p: any) => <Row key={p.product} label={`${p.product} × ${p.quantity}`} value={`₹${sales(p)}`} />)}
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