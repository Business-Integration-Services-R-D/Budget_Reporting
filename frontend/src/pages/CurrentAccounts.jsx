import { useAuth } from "@/contexts/AuthContext";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, fmtUSD, fmtDate, formatApiError } from "@/lib/api";
import { privateValue } from "@/lib/privacy";
import { Page, Card, EmptyState } from "@/components/Primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ArrowRight, Check, Loader2, Search, Scale, Users } from "lucide-react";
import { toast } from "sonner";

const today = () => {
  const date = new Date();
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};

const accountLabel = (account) => {
  if (account.has_open_documents && Math.abs(account.balance) < 0.005) return "Açık borç ve alacak var";
  if (account.balance > 0) return "Net borcumuz";
  if (account.balance < 0) return "Net alacağımız";
  if (account.unallocated_paid > 0 || account.unallocated_received > 0) return "Dağıtılmamış hareket var";
  return "Hesap kapalı";
};

export default function CurrentAccounts() {
  const { user } = useAuth();
  const canWrite = ["admin", "manager", "accountant", "finance"].includes(user?.role);
  const [accounts, setAccounts] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(null);
  const [saving, setSaving] = useState(false);

  const loadAccounts = useCallback(async () => {
    const { data } = await api.get("/current-accounts");
    setAccounts(data);
    return data;
  }, []);

  const openAccount = useCallback(async (account) => {
    setSelected(account);
    const { data } = await api.get(`/current-accounts/${encodeURIComponent(account.id || account.name)}`);
    setDetail(data);
  }, []);

  useEffect(() => {
    loadAccounts().catch((error) => toast.error(formatApiError(error))).finally(() => setLoading(false));
  }, [loadAccounts]);

  const filtered = useMemo(() => {
    const query = search.toLocaleLowerCase("tr-TR").trim();
    return query ? accounts.filter((account) => account.name?.toLocaleLowerCase("tr-TR").includes(query)) : accounts;
  }, [accounts, search]);

  const entries = useMemo(() => {
    if (!detail) return [];
    const documents = (detail.payables || []).map((item) => ({
      ...item, rowId: `document-${item.id}`, rowDate: item.due_date, rowType: item.kind === "RECEIVABLE" ? "ALACAK" : "BORÇ",
      rowAmount: item.usd_amount, tone: item.kind === "RECEIVABLE" ? "text-[#1F8942]" : "text-[#D92D20]",
    }));
    const movements = (detail.payments || []).map((item) => ({
      ...item, rowId: `movement-${item.id}`, rowDate: item.date,
      rowType: item.is_offset ? "MAHSUP" : item.type === "TAHSİL" ? "TAHSİLAT" : "ÖDEME",
      rowAmount: item.usd_amount, tone: item.is_offset ? "text-[#6E45A5]" : "text-[#16753A]",
    }));
    return [...documents, ...movements].sort((a, b) => String(b.rowDate || "").localeCompare(String(a.rowDate || "")));
  }, [detail]);

  const startOffset = () => {
    const maximum = Math.min(detail.summary.open_debt, detail.summary.open_receivable);
    setOffset({ step: 1, amount_usd: maximum, date: today(), maximum });
  };

  const saveOffset = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await api.post(`/current-accounts/${encodeURIComponent(detail.id || detail.name)}/offset`, {
        amount_usd: Number(offset.amount_usd), date: offset.date,
      });
      toast.success("Cari mahsup tamamlandı; banka ve nakit bakiyesi değişmedi");
      setOffset(null);
      const rows = await loadAccounts();
      const refreshed = rows.find((item) => item.id === detail.id) || selected;
      await openAccount(refreshed);
    } catch (error) { toast.error(formatApiError(error)); }
    finally { setSaving(false); }
  };

  const summary = detail?.summary;
  const amount = Number(offset?.amount_usd || 0);
  const validOffset = amount > 0 && amount <= Number(offset?.maximum || 0) + 0.005;

  return (
    <Page title="Cari Hesaplar" subtitle={`${privateValue(accounts.length)} cari · Açık belgeler ve dağıtılmamış hareketler`}>
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <Card className="lg:col-span-4 overflow-hidden">
          <div className="px-5 py-4 border-b border-[#E5E5EA]/50">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#86868B]" />
              <Input data-testid="input-search-ca" placeholder="Cari ara…" value={search} onChange={(event) => setSearch(event.target.value)} className="h-9 pl-9 bg-[#F5F5F7] border-0 rounded-lg" />
            </div>
          </div>
          {loading ? <div className="p-5 space-y-3">{[...Array(8)].map((_, index) => <div key={index} className="skeleton h-12 w-full" />)}</div>
            : filtered.length === 0 ? <EmptyState icon={Users} title="Cari hesap yok" message="Borç veya alacak girişi yapın." />
            : <div className="divide-y divide-[#F5F5F7] max-h-[75vh] overflow-y-auto">
              {filtered.map((account, index) => (
                <button key={account.id || index} data-testid={`ca-${index}`} onClick={() => openAccount(account)} className={`w-full px-5 py-3 flex items-center justify-between hover:bg-[#FAFAFA] text-left transition ${selected?.id === account.id ? "bg-[#FAFAFA]" : ""}`}>
                  <div className="min-w-0 flex-1 pr-3">
                    <div className="text-sm font-medium text-[#1D1D1F] truncate">{account.name}</div>
                    <div className="text-xs text-[#86868B]">{privateValue(account.count)} belge · {accountLabel(account)}</div>
                  </div>
                  <div className={`text-sm font-semibold tabular-nums ${account.balance > 0 ? "text-[#D92D20]" : account.balance < 0 ? "text-[#1F8942]" : "text-[#1D1D1F]"}`}>{fmtUSD(Math.abs(account.balance))}</div>
                </button>
              ))}
            </div>}
        </Card>

        <Card className="lg:col-span-8 overflow-hidden">
          {!selected || !detail ? <EmptyState icon={Users} title="Cari seçin" message="Açık belgeleri ve hareketleri görmek için soldan bir cari seçin." /> : <>
            <div className="px-4 sm:px-6 py-4 border-b border-[#E5E5EA]/50 flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-[#1D1D1F] truncate">{detail.name}</h3>
                <p className="text-xs text-[#86868B] mt-1">{accountLabel(summary)}</p>
              </div>
              <Button data-testid="start-offset" disabled={!canWrite || summary.open_debt <= 0 || summary.open_receivable <= 0} onClick={startOffset} className="rounded-lg bg-[#111111] hover:bg-[#2C2C2E] text-white gap-2">
                <Scale className="w-4 h-4" /> Borç ve Alacağı Mahsup Et
              </Button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-[#E5E5EA] border-b border-[#E5E5EA]">
              <Metric label="Açık borç" value={summary.open_debt} />
              <Metric label="Açık alacak" value={summary.open_receivable} />
              <Metric label="Dağıtılmamış ödeme" value={summary.unallocated_paid} />
              <Metric label="Dağıtılmamış tahsilat" value={summary.unallocated_received} />
            </div>
            <div className="px-4 sm:px-6 py-2.5 text-xs text-[#636366] bg-[#FAFAFA] border-b border-[#E5E5EA]">
              Net cari: <strong>{fmtUSD(Math.abs(summary.balance))}</strong> · {accountLabel(summary)}. Mahsup yalnızca açık belgeleri eşleştirir; banka ve nakit akışını değiştirmez.
            </div>
            <div className="overflow-x-auto max-h-[58vh] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="bg-[#FAFAFA] sticky top-0"><tr className="text-left">
                  <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Tarih</th>
                  <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">İşlem</th>
                  <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Açıklama</th>
                  <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">USD</th>
                </tr></thead>
                <tbody>{entries.map((entry) => <tr key={entry.rowId} className="border-b border-[#F5F5F7]">
                  <td className="px-4 py-2.5 tabular-nums whitespace-nowrap">{fmtDate(entry.rowDate)}</td>
                  <td className={`px-4 py-2.5 font-medium ${entry.tone}`}>{entry.rowType}</td>
                  <td className="px-4 py-2.5 min-w-56"><div className="truncate max-w-md">{entry.description || entry.expense_type || entry.payment_method || "—"}</div>{entry.is_offset && <div className="text-[10px] text-[#86868B]">Nakit hareketi oluşturmaz</div>}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{fmtUSD(entry.rowAmount)}</td>
                </tr>)}</tbody>
              </table>
            </div>
          </>}
        </Card>
      </div>

      <Sheet open={Boolean(offset)} onOpenChange={(open) => !open && !saving && setOffset(null)}>
        <SheetContent className="w-full sm:max-w-lg overflow-y-auto rounded-l-3xl">
          {offset && <div className="space-y-6">
            <SheetHeader><SheetTitle>Cari Mahsup</SheetTitle><SheetDescription>{offset.step === 1 ? "Açık borç ve alacaktan eşleştirilecek tutarı belirleyin." : "İşlem sonrası bakiyeleri kontrol edip onaylayın."}</SheetDescription></SheetHeader>
            <div className="flex items-center gap-2 text-xs"><Step active label="1 · Tutar" /><ArrowRight className="w-4 h-4 text-[#AEAEB2]" /><Step active={offset.step === 2} label="2 · Kontrol" /></div>
            <div className="rounded-2xl bg-[#F5F5F7] p-4 space-y-3">
              <div className="font-semibold">{detail.name}</div>
              <PreviewRow label="Açık borç" value={summary.open_debt} />
              <PreviewRow label="Açık alacak" value={summary.open_receivable} />
              <PreviewRow label="En fazla mahsup" value={offset.maximum} strong />
            </div>
            {offset.step === 1 ? <>
              <div className="space-y-2"><Label htmlFor="offset-amount">Mahsup tutarı (USD)</Label><Input id="offset-amount" data-testid="offset-amount" type="number" min="0.01" max={offset.maximum} step="0.01" value={offset.amount_usd} onChange={(event) => setOffset({ ...offset, amount_usd: event.target.value })} /></div>
              <div className="space-y-2"><Label htmlFor="offset-date">İşlem tarihi</Label><Input id="offset-date" type="date" value={offset.date} onChange={(event) => setOffset({ ...offset, date: event.target.value })} /></div>
              {!validOffset && <p className="text-sm text-[#D92D20]">Tutar sıfırdan büyük ve en fazla {fmtUSD(offset.maximum)} olmalıdır.</p>}
              <Button data-testid="offset-next" disabled={!validOffset || !offset.date} onClick={() => setOffset({ ...offset, step: 2 })} className="w-full rounded-lg bg-[#111111] text-white">Devam Et <ArrowRight className="w-4 h-4 ml-2" /></Button>
            </> : <>
              <div className="rounded-2xl border border-[#E5E5EA] p-4 space-y-3">
                <PreviewRow label="Mahsup edilecek" value={amount} strong />
                <PreviewRow label="Kalan açık borç" value={Math.max(0, summary.open_debt - amount)} />
                <PreviewRow label="Kalan açık alacak" value={Math.max(0, summary.open_receivable - amount)} />
                <div className="pt-3 border-t border-[#E5E5EA] flex gap-2 text-sm text-[#636366]"><Check className="w-4 h-4 text-[#1F8942] shrink-0 mt-0.5" /><span>Banka/kasa bakiyesi ile dashboard nakit akışı değişmeyecek.</span></div>
              </div>
              <div className="flex gap-2"><Button variant="outline" disabled={saving} onClick={() => setOffset({ ...offset, step: 1 })}>Geri</Button><Button data-testid="confirm-offset" disabled={saving || !validOffset} onClick={saveOffset} className="flex-1 rounded-lg bg-[#111111] text-white">{saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}Mahsubu Onayla</Button></div>
            </>}
          </div>}
        </SheetContent>
      </Sheet>
    </Page>
  );
}

const Metric = ({ label, value }) => <div className="bg-white p-4"><div className="text-[10px] uppercase tracking-wider text-[#86868B]">{label}</div><div className="mt-1 text-base font-semibold tabular-nums">{fmtUSD(value)}</div></div>;
const PreviewRow = ({ label, value, strong }) => <div className={`flex justify-between gap-4 text-sm ${strong ? "pt-3 border-t border-[#E5E5EA] font-semibold" : ""}`}><span className="text-[#636366]">{label}</span><span className="tabular-nums">{fmtUSD(value)}</span></div>;
const Step = ({ active, label }) => <span className={`px-3 py-1.5 rounded-full ${active ? "bg-[#111111] text-white" : "bg-[#F5F5F7] text-[#86868B]"}`}>{label}</span>;
