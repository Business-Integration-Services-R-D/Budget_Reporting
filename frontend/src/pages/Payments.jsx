import { useAuth } from "@/contexts/AuthContext";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, fmtUSD, fmtDate, fmtMoney, formatApiError } from "@/lib/api";
import { privateValue } from "@/lib/privacy";
import { Page, Card, StatusBadge, EmptyState } from "@/components/Primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search, CreditCard, Trash2, ArrowUpRight, ArrowDownLeft, ChevronDown, Plus, Loader2 } from "lucide-react";
import { toast } from "sonner";

const localDate = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
const actionName = (kind) => kind === "RECEIVABLE" ? "Tahsil Et" : "Ödeme Yap";
const remaining = (p) => ["ÖDENDİ", "İPTAL"].includes(p.status) ? 0 : (p.remaining_usd ?? p.usd_amount ?? 0);
const originalRemaining = (p) => ["ÖDENDİ", "İPTAL"].includes(p.status) ? 0 : (p.remaining_amount ?? (p.remaining_usd != null && p.usd_amount > 0 ? (p.original_amount || p.usd_amount) * p.remaining_usd / p.usd_amount : p.original_amount ?? p.usd_amount ?? 0));
const canSettle = (p) => !["TASLAK", "ONAY BEKLİYOR", "İPTAL"].includes(p.status) && !["draft", "pending"].includes(p.approval_status) && (p.remaining_usd ?? p.usd_amount ?? 0) > 0;
const unlinkedPaid = (p) => p.status === "ÖDENDİ" && p.remaining_usd == null;

export default function Payments() {
  const { user } = useAuth();
  const canWrite = ["admin", "manager", "accountant", "finance"].includes(user?.role);
  const [payables, setPayables] = useState([]);
  const [items, setItems] = useState([]);
  const [masters, setMasters] = useState({ banks: [], vendors: [], ships: [], companies: [], currencies: [] });
  const [fxRates, setFxRates] = useState([]);
  const [kind, setKind] = useState("PAYABLE");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [historyQuery, setHistoryQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [debts, receivables, movements] = await Promise.all([
        api.get("/payables?kind=PAYABLE&limit=5000"),
        api.get("/payables?kind=RECEIVABLE&limit=5000"),
        api.get("/payments?limit=5000&include_voided=true"),
      ]);
      setPayables([...debts.data, ...receivables.data]);
      setItems(movements.data);
    } catch (e) { setError(formatApiError(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [banks, vendors, ships, companies, currencies, fx] = await Promise.all([
          api.get("/master/banks"), api.get("/master/vendors"), api.get("/master/ships"),
          api.get("/master/companies"), api.get("/master/currencies"), api.get("/fx/latest"),
        ]);
        if (active) {
          setMasters({ banks: banks.data.filter((b) => b.active !== false), vendors: vendors.data.filter((v) => v.active !== false), ships: ships.data, companies: companies.data, currencies: currencies.data });
          setFxRates(fx.data);
        }
      } catch (e) { if (active) toast.error(formatApiError(e)); }
    })();
    return () => { active = false; };
  }, []);

  const fxRateOf = (code) => ["TL", "TRY"].includes(code) ? 1 : (fxRates.find((c) => c.code === (code === "POUND" ? "GBP" : code))?.rate_to_tl || 0);
  const changeAmount = (patch) => {
    setEditing((previous) => {
      const next = { ...previous, ...patch };
      const usdRate = Number(next.usd_fx_rate || fxRateOf("USD"));
      const converted = next.currency === "USD" ? Number(next.amount || 0)
        : usdRate > 0 ? Number(next.amount || 0) * (next.currency === "TL" ? 1 : Number(next.fx_rate || 0)) / usdRate : 0;
      next.usd_amount = Math.round((converted + Number.EPSILON) * 100) / 100;
      if (next.currency === "TL") next.fx_rate = 1;
      return next;
    });
  };
  const linkFields = (p) => ({
    payable_id: p.id, type: p.kind === "RECEIVABLE" ? "TAHSİL" : "TEDİYE",
    vendor: p.vendor || "", vendor_id: p.vendor_id || null, ship: p.ship || "",
  });
  const startPayment = (p) => {
    const code = p.currency || "USD";
    const amount = originalRemaining(p);
    const localRate = fxRateOf(code);
    const usdRate = fxRateOf("USD");
    const converted = code === "USD" ? amount : usdRate > 0 ? amount * localRate / usdRate : 0;
    setEditing({ ...linkFields(p), date: localDate(), description: p.description || "",
      currency: code, amount, usd_amount: Math.round(converted * 100) / 100, fx_rate: localRate,
      usd_fx_rate: usdRate, posting_status: "posted", approved: true,
      payment_method: "", bank_account_id: null, paying_company: "" });
  };

  const startIndependent = () => setEditing({
    type: kind === "RECEIVABLE" ? "TAHSİL" : "TEDİYE", payable_id: null,
    date: localDate(), currency: "USD", amount: "", usd_amount: 0,
    fx_rate: fxRateOf("USD"), usd_fx_rate: fxRateOf("USD"), posting_status: "posted", approved: true, vendor: "", ship: "", description: "", payment_method: "", paying_company: "",
  });
  const linked = editing && payables.find((p) => p.id === editing.payable_id);
  const isReceipt = editing?.type === "TAHSİL";

  const save = async (postingStatus = "posted") => {
    if (saving) return;
    if (!editing.date || !(Number(editing.amount) > 0) || !(Number(editing.usd_amount) > 0)) {
      toast.error("Tarih ve sıfırdan büyük bir tutar girin."); return;
    }
    if (postingStatus === "posted" && !editing.payment_method && !editing.bank_account_id) {
      toast.error("Gerçekleşen işlem için banka veya kasa seçin; hazır değilse taslak kaydedin."); return;
    }
    setSaving(true);
    try {
      const payload = { ...editing, payable_id: editing.payable_id || null, posting_status: postingStatus, approved: postingStatus === "posted" };
      if (payload.id) await api.put(`/payments/${payload.id}`, payload);
      else await api.post("/payments", payload);
      toast.success(postingStatus === "draft" ? "Taslak kaydedildi; nakit ve borç bakiyesi değişmedi" : isReceipt ? "Tahsilat kaydedildi" : "Ödeme kaydedildi");
      setEditing(null);
      await load();
    } catch (e) { toast.error(formatApiError(e)); }
    finally { setSaving(false); }
  };
  const remove = async (p) => {
    const message = p.is_offset
      ? "Bu mahsup iptal edilsin mi? Mahsubun borç ve alacak tarafı birlikte geri alınır; iki belge de yeniden hesaplanır."
      : "Bu hareket iptal edilsin mi? Geçmişi saklanır; nakit ve bağlı kaydın kalan tutarı yeniden hesaplanır.";
    if (!window.confirm(message)) return;
    try { await api.delete(`/payments/${p.id}`); toast.success("Hareket iptal edildi"); await load(); }
    catch (e) { toast.error(formatApiError(e)); }
  };

  const visible = useMemo(() => {
    const q = query.toLocaleLowerCase("tr-TR").trim();
    return payables.filter((p) => p.kind === kind &&
      (status === "all" || (status === "open" ? !["ÖDENDİ", "İPTAL"].includes(p.status) : ["ÖDENDİ", "İPTAL"].includes(p.status))) &&
      (!q || [p.vendor, p.ship, p.description, p.status].some((v) => String(v || "").toLocaleLowerCase("tr-TR").includes(q)))
    ).sort((a, b) => String(a.due_date || "9999").localeCompare(String(b.due_date || "9999")));
  }, [payables, kind, query, status]);
  const movements = items.filter((p) => !historyQuery || [p.vendor, p.description, p.payment_method,
    p.type === "TAHSİL" ? "Tahsilat" : "Ödeme"].some((v) => String(v || "").toLocaleLowerCase("tr-TR").includes(historyQuery.toLocaleLowerCase("tr-TR"))));

  const recordAction = (p) => (
    <Button size="sm" disabled={!canWrite || !canSettle(p)} data-testid={`register-pay-${p.id}`} onClick={() => startPayment(p)} className="rounded-lg bg-[#111111] hover:bg-[#2C2C2E] text-white gap-1.5">
      {p.kind === "RECEIVABLE" ? <ArrowDownLeft className="w-3.5 h-3.5" /> : <ArrowUpRight className="w-3.5 h-3.5" />}
      {["TASLAK", "ONAY BEKLİYOR"].includes(p.status) || ["draft", "pending"].includes(p.approval_status) ? "Önce onaylayın" : unlinkedPaid(p) ? (p.kind === "RECEIVABLE" ? "Tahsilatı Kaydet" : "Ödemeyi Kaydet") : actionName(p.kind)}
    </Button>
  );
  const amountDetails = (p) => <>
    <div className="font-semibold tabular-nums">{fmtUSD(remaining(p))}</div>
    {p.currency && p.currency !== "USD" && <div className="text-[11px] text-[#636366]">{fmtMoney(originalRemaining(p), p.currency)}</div>}
    <div className="text-[11px] text-[#86868B] mt-1">Toplam {fmtUSD(p.usd_amount)}</div>
    {unlinkedPaid(p) ? <div className="text-[10px] text-[#86868B] mt-1">Elle kapatıldı · Hareket bağlı değil</div>
      : p.paid_usd > 0 && <div className="text-[11px] text-[#86868B]">Mahsup edilen {fmtUSD(p.paid_usd)}</div>}
  </>;

  return (
    <Page title="Ödeme ve Tahsilat" subtitle="Borçlarını öde, alacaklarını tahsil et.">
      <Card className="overflow-hidden mb-6" data-testid="payable-register">
        <div className="p-4 sm:p-5 border-b border-[#E5E5EA] space-y-4">
          <div className="inline-flex rounded-xl bg-[#F5F5F7] p-1 gap-1" role="group" aria-label="İşlem seçimi">
            {[{ key: "PAYABLE", label: "Borç → Ödeme", Icon: ArrowUpRight }, { key: "RECEIVABLE", label: "Alacak → Tahsilat", Icon: ArrowDownLeft }].map(({ key, label, Icon }) => (
              <button key={key} data-testid={`tab-${key}`} aria-pressed={kind === key} onClick={() => setKind(key)} className={`flex items-center gap-2 px-3 sm:px-4 py-2.5 rounded-lg text-xs sm:text-sm font-medium transition ${kind === key ? "bg-white text-[#1D1D1F] shadow-sm" : "text-[#86868B] hover:text-[#1D1D1F]"}`}>
                <Icon className="w-4 h-4 shrink-0" />{label}<span className="text-[10px] text-[#86868B]">{privateValue(payables.filter((p) => p.kind === key).length)}</span>
              </button>
            ))}
          </div>
          <div className="flex gap-3 flex-wrap">
            <div className="relative flex-1 min-w-[180px]"><Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#86868B]" /><Input aria-label="Borç ve alacak ara" data-testid="register-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Firma, gemi veya açıklama ara…" className="pl-9 bg-[#F5F5F7] border-0 rounded-lg" /></div>
            <Select value={status} onValueChange={setStatus}><SelectTrigger aria-label="Kayıt durumu" className="w-40 bg-[#F5F5F7] border-0 rounded-lg"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Tüm durumlar</SelectItem><SelectItem value="open">Açık kayıtlar</SelectItem><SelectItem value="closed">Kapanan kayıtlar</SelectItem></SelectContent></Select>
          </div>
        </div>
        {error ? <div role="alert" className="p-6 text-sm text-[#D92D20]">{error}<Button variant="outline" onClick={load} className="ml-3">Tekrar Dene</Button></div>
          : loading ? <div className="p-6 space-y-3">{[1, 2, 3].map((i) => <div key={i} className="skeleton h-12" />)}</div>
          : !visible.length ? <EmptyState icon={CreditCard} title="Gösterilecek kayıt yok" message={query || status !== "all" ? "Aramayı veya durum filtresini değiştirebilirsiniz." : `${kind === "PAYABLE" ? "Borçlar" : "Alacaklar"} bölümünden eklediğiniz kayıtlar burada görünür.`} />
          : <>
            <div className="hidden lg:block overflow-x-auto"><table className="w-full text-sm"><thead className="bg-[#FAFAFA]"><tr className="text-left text-[11px] uppercase tracking-wider text-[#86868B]"><th className="px-5 py-3 font-semibold">Firma / Gemi</th><th className="px-5 py-3 font-semibold">Vade</th><th className="px-5 py-3 font-semibold text-right">Kalan USD</th><th className="px-5 py-3 font-semibold">Durum</th><th className="px-5 py-3 font-semibold text-right">İşlem</th></tr></thead>
              <tbody>{visible.map((p) => <tr key={p.id} data-testid={`register-row-${p.id}`} className="border-t border-[#F5F5F7]"><td className="px-5 py-4 max-w-xs"><div className="font-medium truncate">{p.vendor || "Firma belirtilmedi"}</div><div className="text-xs text-[#86868B] mt-1">{[p.ship, p.description].filter(Boolean).join(" · ") || "—"}</div></td><td className="px-5 py-4 whitespace-nowrap text-[#636366]">{fmtDate(p.due_date)}</td><td className="px-5 py-4 text-right">{amountDetails(p)}</td><td className="px-5 py-4"><StatusBadge value={p.status} /></td><td className="px-5 py-4 text-right whitespace-nowrap">{recordAction(p)}</td></tr>)}</tbody>
            </table></div>
            <div className="lg:hidden divide-y divide-[#F5F5F7]">{visible.map((p) => <div key={p.id} className="p-4 sm:p-5 space-y-4" data-testid={`register-card-${p.id}`}><div className="flex justify-between gap-4"><div className="min-w-0"><div className="text-sm font-medium break-words">{p.vendor || "Firma belirtilmedi"}</div><div className="text-xs text-[#86868B] mt-1">{[p.ship, p.description].filter(Boolean).join(" · ")}</div><div className="text-xs text-[#86868B] mt-2">Vade {fmtDate(p.due_date)}</div></div><div className="text-right shrink-0"><div className="text-[10px] text-[#86868B] mb-1">KALAN USD</div>{amountDetails(p)}</div></div><div className="flex items-center justify-between gap-3"><StatusBadge value={p.status} />{recordAction(p)}</div></div>)}</div>
          </>}
      </Card>

      <details className="group bg-white rounded-2xl border border-[#E5E5EA]" data-testid="payment-history">
        <summary className="list-none cursor-pointer p-4 sm:p-5 flex items-center justify-between gap-3"><div><span className="text-sm font-medium">İşlem geçmişi</span><span className="ml-2 text-xs text-[#86868B]">{privateValue(items.filter((p) => !p.voided).length)} aktif hareket</span></div><ChevronDown className="w-4 h-4 text-[#86868B] transition-transform group-open:rotate-180" /></summary>
        <div className="px-4 pb-4 sm:px-5 sm:pb-5 border-t border-[#F5F5F7]">
          <div className="flex flex-wrap gap-3 mt-4 mb-4"><Input aria-label="İşlem geçmişinde ara" value={historyQuery} onChange={(e) => setHistoryQuery(e.target.value)} placeholder="Firma, hesap veya açıklama ara…" className="bg-[#F5F5F7] border-0 rounded-lg flex-1 min-w-[180px]" /><Button disabled={!canWrite} variant="outline" size="sm" onClick={startIndependent} className="h-9 rounded-lg gap-1"><Plus className="w-3.5 h-3.5" />Bağımsız işlem ekle</Button></div>
          {!movements.length ? <p className="py-6 text-center text-sm text-[#86868B]">Gösterilecek hareket yok.</p> : <div className="divide-y divide-[#F5F5F7]">{movements.map((p) => <div key={p.id} className="flex items-center gap-3 py-3"><button disabled={p.voided || p.is_offset || !canWrite} onClick={() => setEditing({ ...p })} data-testid={`row-payment-${p.id}`} className="flex-1 min-w-0 text-left flex justify-between gap-3 rounded-lg hover:bg-[#FAFAFA] p-2 disabled:cursor-default"><div className="min-w-0"><div className="text-xs font-medium mb-1" style={{ color: p.is_offset ? "#6E45A5" : p.type === "TAHSİL" ? "#1F8942" : "#D92D20" }}>{p.is_offset ? `Cari mahsup · ${p.type === "TAHSİL" ? "Alacak" : "Borç"}` : p.type === "TAHSİL" ? "Tahsilat" : "Ödeme"}</div><div className="text-sm truncate">{p.vendor || "Firma belirtilmedi"}</div><div className="text-xs text-[#86868B] mt-1">{fmtDate(p.date)}{p.payment_method ? ` · ${p.payment_method}` : ""}</div></div><div className="shrink-0 text-right"><div className="text-sm font-semibold">{fmtUSD(p.usd_amount)}</div><div className="text-[10px] text-[#86868B] mt-1">{p.voided ? "İPTAL · Geçmiş kaydı" : p.is_offset ? "CARİ MAHSUP · Nakde yansımaz" : p.posting_status === "draft" ? "TASLAK · Nakde yansımaz" : p.payable_id ? "Kayda bağlı" : "Bağımsız"}</div></div></button><button disabled={p.voided || !canWrite} aria-label={p.is_offset ? "Mahsubu iptal et" : "Hareketi iptal et"} onClick={() => remove(p)} className="p-2 text-[#86868B] hover:text-[#D92D20]"><Trash2 className="w-4 h-4" /></button></div>)}</div>}
        </div>
      </details>

      <Sheet open={!!editing} onOpenChange={(value) => { if (!value && !saving) setEditing(null); }}>
        <SheetContent className="w-full sm:max-w-lg overflow-y-auto rounded-l-3xl">
          <SheetHeader><SheetTitle>{editing?.id ? (isReceipt ? "Tahsilatı Düzenle" : "Ödemeyi Düzenle") : isReceipt ? "Tahsilat Kaydet" : "Ödeme Kaydet"}</SheetTitle><SheetDescription>{linked ? (isReceipt ? "Seçilen alacağa tahsilat kaydedilecek." : "Seçilen borca ödeme kaydedilecek.") : "Bir borç veya alacak seçerek hareketi bağlayabilirsiniz."}</SheetDescription></SheetHeader>
          {editing && <div className="mt-6 space-y-5">
            {linked && <div className="p-4 rounded-xl bg-[#F5F5F7] space-y-2"><div className="text-[11px] font-semibold text-[#86868B]">{isReceipt ? "ALACAK → TAHSİLAT" : "BORÇ → ÖDEME"}</div><div className="text-sm font-medium">{linked.vendor || "Firma belirtilmedi"}</div><div className="text-xs text-[#86868B]">{linked.ship || "—"} · Vade {fmtDate(linked.due_date)}</div><div className="text-sm">Kalan: <strong>{fmtMoney(originalRemaining(linked), linked.currency || "USD")}</strong></div></div>}
            {(!linked || editing.id) && <>
              <Field label="İlgili borç / alacak"><Select value={editing.payable_id || "independent"} onValueChange={(id) => { const p = payables.find((row) => row.id === id); setEditing(p ? { ...editing, ...linkFields(p) } : { ...editing, payable_id: null }); }}><SelectTrigger aria-label="İlgili borç / alacak" className="bg-[#F5F5F7] border-0 rounded-lg"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="independent">Bağımsız işlem</SelectItem>{payables.filter((p) => p.id === editing.payable_id || canSettle(p)).map((p) => <SelectItem key={p.id} value={p.id}>{p.kind === "RECEIVABLE" ? "Alacak" : "Borç"} · {p.vendor || "—"} · {fmtDate(p.due_date)} · {fmtUSD(p.remaining_usd ?? p.usd_amount)}</SelectItem>)}</SelectContent></Select></Field>
              {!linked && <><Field label="İşlem"><Select value={editing.type} onValueChange={(type) => setEditing({ ...editing, type })}><SelectTrigger aria-label="İşlem türü" className="bg-[#F5F5F7] border-0 rounded-lg"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="TEDİYE">Ödeme</SelectItem><SelectItem value="TAHSİL">Tahsilat</SelectItem></SelectContent></Select></Field><Field label="Firma"><Choice value={editing.vendor} onChange={(vendor) => setEditing({ ...editing, vendor, vendor_id: null })} options={masters.vendors.map((p) => p.name)} /></Field></>}
            </>}
            <div className="grid grid-cols-2 gap-3"><Field label={isReceipt ? "Tahsilat tutarı *" : "Ödeme tutarı *"}><Input aria-label="İşlem tutarı" type="number" step="0.01" min="0.01" value={editing.amount ?? ""} onChange={(e) => changeAmount({ amount: e.target.value === "" ? "" : Number(e.target.value) })} /></Field><Field label="Para birimi"><Choice value={editing.currency} onChange={(currency) => changeAmount({ currency, fx_rate: fxRateOf(currency) })} options={[...new Set(["USD", ...masters.currencies.map((c) => c.code)])]} /></Field></div>
            <Field label="Tarih *"><Input aria-label="İşlem tarihi" type="date" value={editing.date?.slice(0, 10) || ""} onChange={(e) => setEditing({ ...editing, date: e.target.value })} /></Field>
            <Field label="Hesap / Banka (gerçekleşen işlemde zorunlu)"><Choice value={editing.payment_method} onChange={(payment_method) => setEditing({ ...editing, payment_method, bank_account_id: null })} options={masters.banks.map((b) => b.name)} /></Field>
            {editing.currency !== "USD" && <div className="grid grid-cols-2 gap-3"><Field label="TL kuru"><Input type="number" step="0.0001" disabled={editing.currency === "TL"} value={editing.currency === "TL" ? 1 : editing.fx_rate ?? ""} onChange={(e) => changeAmount({ fx_rate: Number(e.target.value) })} /></Field><Field label="USD karşılığı"><Input type="number" step="0.01" value={editing.usd_amount ?? ""} onChange={(e) => setEditing({ ...editing, usd_amount: Number(e.target.value) })} /></Field></div>}
            <details className="border-t border-[#E5E5EA] pt-4"><summary className="text-xs text-[#636366] cursor-pointer">Ek bilgiler</summary><div className="mt-4 space-y-4"><Field label="Şirket"><Choice value={editing.paying_company} onChange={(paying_company) => setEditing({ ...editing, paying_company })} options={masters.companies.map((c) => c.name)} /></Field>{!linked && <Field label="Gemi / Birim"><Choice value={editing.ship} onChange={(ship) => setEditing({ ...editing, ship })} options={masters.ships.map((s) => s.name)} /></Field>}<Field label="Açıklama"><Textarea value={editing.description || ""} onChange={(e) => setEditing({ ...editing, description: e.target.value })} className="bg-[#F5F5F7] border-0 rounded-lg" rows={2} /></Field></div></details>
            {editing.fx_difference_usd !== undefined && Math.abs(editing.fx_difference_usd) >= 0.01 && <p className="text-xs text-[#86868B]">Kayıtlı kur farkı: {fmtUSD(editing.fx_difference_usd)}. Belge özgün para birimindeki mahsup tutarıyla kapanır.</p>}
            <div className="flex flex-wrap gap-2 border-t border-[#E5E5EA] pt-4"><Button disabled={saving || !canWrite} data-testid="btn-save-payment" onClick={() => save("posted")} className="flex-1 bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-lg">{saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}{editing.id ? "Değişiklikleri Kaydet" : isReceipt ? "Tahsilatı Kaydet" : "Ödemeyi Kaydet"}</Button><Button disabled={saving || !canWrite} variant="outline" onClick={() => save("draft")} className="rounded-lg">Taslak Kaydet</Button><Button disabled={saving} variant="outline" onClick={() => setEditing(null)} className="rounded-lg">Vazgeç</Button></div>
          </div>}
        </SheetContent>
      </Sheet>
    </Page>
  );
}

const Field = ({ label, children }) => <div className="space-y-1.5"><Label className="text-xs text-[#636366]">{label}</Label>{children}</div>;
const Choice = ({ value, onChange, options }) => <Select value={value || ""} onValueChange={onChange}><SelectTrigger className="bg-[#F5F5F7] border-0 rounded-lg"><SelectValue placeholder="Seçin" /></SelectTrigger><SelectContent className="max-h-72">{[...new Set([value, ...options].filter(Boolean))].map((option) => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent></Select>;
