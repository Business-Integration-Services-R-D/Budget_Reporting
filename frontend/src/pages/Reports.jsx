import { privateValue } from "@/lib/privacy";
import { useEffect, useState } from "react";
import { api, fmtUSD, formatApiError } from "@/lib/api";
import { Page, Card, EmptyState } from "@/components/Primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FileBarChart2, Ship, Calendar, DollarSign, Building2, Clock, WalletCards, ListChecks, TableProperties, FileDown, Loader2 } from "lucide-react";
import { toast } from "sonner";

const REPORTS = [
  { id: "cash-report", label: "Kasa Raporu", icon: WalletCards, desc: "Kasa/banka hareketleri ve bakiyeler" },
  { id: "office-payments", label: "Günlük Ofis Ödemeleri", icon: ListChecks, desc: "Haftalık ödeme ihtiyacı ve bütçe sınıfı" },
  { id: "all-debts", label: "Tüm Borçlar", icon: TableProperties, desc: "Vade aylarına dağıtılmış açık borçlar" },
  { id: "by-ship-detail", label: "Gemi Bazlı Borç", icon: Ship, desc: "Toplam · Ödenen · Açık" },
  { id: "aging", label: "Yaşlandırma", icon: Clock, desc: "Vade gruplarına göre açık borç" },
  { id: "monthly-projection", label: "Aylık Projeksiyon", icon: Calendar, desc: "Gelecek ayların borç toplamı" },
  { id: "top-vendors", label: "Top 20 Tedarikçi", icon: Building2, desc: "En çok ödeme yapılan" },
  { id: "by-currency", label: "Döviz Pozisyon", icon: DollarSign, desc: "Para birimi bazında" },
];

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

export default function Reports() {
  const [selected, setSelected] = useState(REPORTS[0]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [months, setMonths] = useState("30");
  const [dataset, setDataset] = useState("reference");

  const query = () => {
    const params = new URLSearchParams();
    if (["cash-report", "office-payments", "all-debts"].includes(selected.id)) params.set("dataset", dataset);
    if (["cash-report", "office-payments"].includes(selected.id)) {
      if (start) params.set("start", start);
      if (end) params.set("end", end);
    }
    if (["all-debts", "monthly-projection"].includes(selected.id)) params.set("months", months);
    return params.toString() ? `?${params}` : "";
  };

  useEffect(() => {
    (async () => {
      setLoading(true);
      try { setData((await api.get(`/reports/${selected.id}${query()}`)).data); }
      catch (e) { toast.error(formatApiError(e)); setData(null); }
      finally { setLoading(false); }
    })();
  }, [selected, start, end, months, dataset]); // eslint-disable-line react-hooks/exhaustive-deps

  const download = async (format) => {
    setExporting(format);
    try {
      const suffix = query();
      const response = await api.get(`/export/reports/${selected.id}${suffix ? `${suffix}&` : "?"}format=${format}`, { responseType: "blob" });
      saveBlob(response.data, `marti-${selected.id}.${format}`);
      toast.success(`${format === "pdf" ? "PDF" : "Excel"} raporu indirildi`);
    } catch (e) { toast.error(formatApiError(e)); }
    finally { setExporting(""); }
  };

  return <Page title="Raporlar" subtitle="Operasyon raporlarını görüntüleyin, Excel veya PDF olarak indirin">
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <Card className="lg:col-span-4 overflow-hidden">
        <div className="px-5 py-4 border-b border-[#E5E5EA]/50"><h3 className="text-base font-medium">Rapor Şablonları</h3><p className="text-xs text-[#86868B] mt-0.5">{REPORTS.length} hazır rapor</p></div>
        <div className="divide-y divide-[#F5F5F7]">{REPORTS.map((r) => <button key={r.id} data-testid={`report-${r.id}`} onClick={() => setSelected(r)} className={`w-full px-5 py-3.5 flex items-start gap-3 hover:bg-[#FAFAFA] text-left transition ${selected.id === r.id ? "bg-[#FAFAFA]" : ""}`}>
          <div className={`w-9 h-9 rounded-lg grid place-items-center shrink-0 ${selected.id === r.id ? "bg-[#111111] text-white" : "bg-[#F5F5F7] text-[#3A3A3C]"}`}><r.icon className="w-4 h-4" strokeWidth={1.5}/></div>
          <div><div className="text-sm font-medium">{r.label}</div><div className="text-xs text-[#86868B]">{r.desc}</div></div>
        </button>)}</div>
      </Card>
      <Card className="lg:col-span-8 overflow-hidden">
        <div className="px-4 sm:px-6 py-4 border-b border-[#E5E5EA]/50 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div><h3 className="text-base font-semibold">{selected.label}</h3><p className="text-xs text-[#86868B] mt-0.5">{selected.desc}</p></div>
          <div className="flex gap-2">
            <Button variant="outline" className="rounded-lg gap-1.5" onClick={() => download("xlsx")} disabled={!!exporting}>{exporting === "xlsx" ? <Loader2 className="w-4 h-4 animate-spin"/> : <FileDown className="w-4 h-4"/>} Excel</Button>
            <Button className="rounded-lg gap-1.5 bg-[#111] text-white" onClick={() => download("pdf")} disabled={!!exporting}>{exporting === "pdf" ? <Loader2 className="w-4 h-4 animate-spin"/> : <FileDown className="w-4 h-4"/>} PDF</Button>
          </div>
        </div>
        {["cash-report", "office-payments", "all-debts"].includes(selected.id) && <div className="px-4 sm:px-6 py-3 border-b border-[#E5E5EA]/50 flex gap-3 items-center"><span className="text-xs text-[#86868B]">Veri seti</span><select aria-label="Veri seti" value={dataset} onChange={e => setDataset(e.target.value)} className="h-9 rounded-lg border border-[#E5E5EA] bg-white px-3 text-sm"><option value="reference">Kaynak PDF Verisi</option><option value="live">Canlı Sistem Verisi</option></select></div>}
        {["cash-report", "office-payments"].includes(selected.id) && <div className="px-4 sm:px-6 py-3 border-b border-[#E5E5EA]/50 flex gap-3 items-center">
          <span className="text-xs text-[#86868B]">Tarih aralığı</span><Input type="date" aria-label="Başlangıç" value={start} onChange={e => setStart(e.target.value)} className="h-9 w-40"/><Input type="date" aria-label="Bitiş" value={end} onChange={e => setEnd(e.target.value)} className="h-9 w-40"/>
        </div>}
        {["all-debts", "monthly-projection"].includes(selected.id) && <div className="px-4 sm:px-6 py-3 border-b border-[#E5E5EA]/50 flex gap-3 items-center"><span className="text-xs text-[#86868B]">Dönem</span><select aria-label="Ay sayısı" value={months} onChange={e => setMonths(e.target.value)} className="h-9 rounded-lg border border-[#E5E5EA] bg-white px-3 text-sm"><option value="12">12 ay</option><option value="24">24 ay</option><option value="30">30 ay</option><option value="36">36 ay</option></select></div>}
        <div className="p-4 sm:p-6 overflow-x-auto">{loading ? <div className="space-y-3">{[...Array(6)].map((_, i) => <div key={i} className="skeleton h-10 w-full"/>)}</div> : <ReportRenderer report={selected.id} data={data}/>}</div>
      </Card>
    </div>
  </Page>;
}

const Head = ({ children, right = false }) => <th className={`px-3 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold whitespace-nowrap ${right ? "text-right" : "text-left"}`}>{children}</th>;
const Cell = ({ children, right = false }) => <td className={`px-3 py-2.5 whitespace-nowrap ${right ? "text-right tabular-nums" : ""}`}>{children}</td>;
const SimpleTable = ({ headers, rows }) => <table className="w-full text-sm"><thead className="bg-[#FAFAFA]"><tr>{headers.map((h, i) => <Head key={h} right={i > 0}>{h}</Head>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i} className="border-b border-[#F5F5F7]">{row.map((v, j) => <Cell key={j} right={j > 0}>{v}</Cell>)}</tr>)}</tbody></table>;
const CategoryBadge = ({ value }) => {
  const colors = { BANKA: "bg-[#EAF3FA] text-[#1F4E78]", OPERASYON: "bg-[#E8F5EC] text-[#1F8942]", "DİĞER": "bg-[#FFF0E8] text-[#B54708]" };
  return <span className={`inline-flex rounded-full px-2 py-1 text-[11px] font-semibold ${colors[value] || colors["DİĞER"]}`}>{value || "DİĞER"}</span>;
};

const ReportRenderer = ({ report, data }) => {
  const empty = !data || (Array.isArray(data) && data.length === 0) || (report === "cash-report" && !data.movements?.length && !data.balances?.length) || (report === "office-payments" && !data.weeks?.length) || (report === "all-debts" && !data.rows?.length);
  if (empty) return <EmptyState icon={FileBarChart2} title="Veri yok" message="Bu rapor için henüz veri yok."/>;
  if (report === "cash-report") return <div className="space-y-8 min-w-[720px]">
    <section><h4 className="font-semibold mb-3">Hareketler</h4><SimpleTable headers={["Tarih", "Tip", "Açıklama", "Hesap", "Tutar", "USD"]} rows={data.movements.map(p => [p.date, p.type, p.description || p.vendor || "—", p.payment_method || "—", `${p.amount?.toLocaleString("tr-TR")} ${p.currency}`, fmtUSD(p.usd_amount)])}/></section>
    <section><h4 className="font-semibold mb-3">Hesap Bakiyeleri</h4>{data.dataset === "reference" ? <SimpleTable headers={["Hesap", "TL", "USD", "EUR", "POUND", "Yapı Kredi", "Şirket"]} rows={data.balances.map(b => [b.name, b.tl, b.usd, b.eur, b.pound, b.yapi_kredi, b.yapi_kredi_company])}/> : <SimpleTable headers={["Hesap", "Para Birimi", "Açılış", "Giren USD", "Çıkan USD", "Mevcut"]} rows={data.balances.map(b => [b.name, b.balance_currency, b.opening_balance?.toLocaleString("tr-TR"), fmtUSD(b.in), fmtUSD(b.out), `${b.current_balance?.toLocaleString("tr-TR")} ${b.balance_currency}`])}/>}</section>
  </div>;
  if (report === "office-payments") return <div className="space-y-6 min-w-[760px]">{data.weeks.map(week => <section key={week.week}>
    <div className="flex justify-between mb-2"><h4 className="font-semibold">{week.start} – {week.end}</h4><span className="font-semibold">{fmtUSD(week.total_usd)}</span></div>
    <SimpleTable headers={["Tarih", "Açıklama", "Firma", "Şirket/Gemi", "Tutar", "USD", "Sınıf"]} rows={week.rows.map(p => [p.date, p.description, p.vendor || "—", p.company_ship, `${p.amount?.toLocaleString("tr-TR")} ${p.currency}`, fmtUSD(p.usd_amount), <CategoryBadge value={p.budget_category}/>])}/>
  </section>)}</div>;
  if (report === "all-debts") return <div className="min-w-max"><table className="text-xs"><thead className="bg-[#FAFAFA]"><tr><Head>Grup</Head><Head>Açıklama/Firma</Head><Head>Gemi</Head><Head>Tür</Head>{data.dataset !== "reference" && <Head right>Geçmiş</Head>}<Head right>Toplam</Head>{data.months.map(m => <Head key={m} right>{m}</Head>)}</tr></thead><tbody>{data.rows.map((p, index) => <tr key={p.id || index} className={`border-b border-[#F5F5F7] ${p.is_total ? "bg-[#EAF3FA] font-semibold" : ""}`}><Cell>{p.group}</Cell><Cell>{p.description}</Cell><Cell>{p.ship}</Cell><Cell>{p.debt_type}</Cell>{data.dataset !== "reference" && <Cell right>{fmtUSD(p.overdue)}</Cell>}<Cell right>{fmtUSD(p.total)}</Cell>{data.months.map(m => <Cell key={m} right>{p.monthly[m] ? fmtUSD(p.monthly[m]) : "—"}</Cell>)}</tr>)}</tbody></table></div>;
  if (report === "by-ship-detail") return <SimpleTable headers={["Gemi", "Toplam Borç", "Ödenen", "Açık", "Kayıt"]} rows={data.map(r => [r._id || "—", fmtUSD(r.total_debt), fmtUSD(r.paid), fmtUSD(r.open), privateValue(r.count)])}/>;
  if (report === "aging") return <SimpleTable headers={["Vade Grubu", "Toplam", "Kayıt"]} rows={data.map(r => [r.bucket, fmtUSD(r.total), privateValue(r.count)])}/>;
  if (report === "monthly-projection") return <SimpleTable headers={["Ay", "Toplam", "Kayıt"]} rows={data.map(r => [r.month, fmtUSD(r.total), privateValue(r.count)])}/>;
  if (report === "top-vendors") return <SimpleTable headers={["Tedarikçi", "Toplam Ödenen", "İşlem"]} rows={data.map(r => [r.vendor, fmtUSD(r.total), privateValue(r.count)])}/>;
  if (report === "by-currency") return <SimpleTable headers={["Para Birimi", "Borç", "Alacak", "Net"]} rows={data.map(r => [r.currency, privateValue(r.borç?.toLocaleString("tr-TR")), privateValue(r.alacak?.toLocaleString("tr-TR")), privateValue((r.alacak-r.borç).toLocaleString("tr-TR"))])}/>;
  return null;
};
