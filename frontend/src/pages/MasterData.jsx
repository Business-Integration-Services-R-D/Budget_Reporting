import { privateValue } from "@/lib/privacy";
import { useEffect, useState } from "react";
import { api, fmtMoney, formatApiError } from "@/lib/api";
import { Page, Card, EmptyState } from "@/components/Primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Database, Plus, Trash2, Edit3, Search } from "lucide-react";
import { toast } from "sonner";

const COLLECTIONS = [
  { key: "companies", label: "Şirketler", fields: ["name", "tax_no", "notes"] },
  { key: "ships", label: "Gemiler / Birimler", fields: ["name", "manager", "armator", "imo", "flag", "notes"] },
  { key: "armators", label: "Armatörler", fields: ["name", "notes"] },
  { key: "managers", label: "Manager'lar", fields: ["name", "notes"] },
  { key: "people", label: "Kişi & Alt Şirketler", fields: ["name", "notes"] },
  { key: "vendors", label: "Tedarikçiler", fields: ["name", "country", "tax_no", "iban", "contact", "phone", "email", "notes"] },
  { key: "countries", label: "Ülkeler", fields: ["name", "code"] },
  { key: "banks", label: "Banka & Kasa", fields: ["name", "type", "currency", "iban", "balance", "company", "notes"] },
  { key: "expense_types", label: "Masraf Türleri", fields: ["code", "name", "notes"] },
  { key: "accounting_codes", label: "Muhasebe Kodları", fields: ["code", "name", "notes"] },
  { key: "currencies", label: "Para Birimleri", fields: ["code", "name", "rate_to_tl"] },
  { key: "payment_statuses", label: "Ödeme Durumları", fields: ["name", "color", "order"] },
  { key: "payment_methods", label: "Ödeme Şekilleri", fields: ["name", "notes"] },
];

const FIELD_LABELS = {
  name: "Ad", code: "Kod", notes: "Notlar", tax_no: "Vergi No",
  manager: "Manager", armator: "Armatör", imo: "IMO No", flag: "Bayrak",
  iban: "IBAN", contact: "İletişim Kişisi", phone: "Telefon", email: "Email",
  type: "Tip", currency: "Para Birimi", balance: "Açılış Bakiyesi", current_balance: "Mevcut Bakiye", company: "Şirket",
  rate_to_tl: "TL Karşılığı", color: "Renk", order: "Sıra", country: "Ülke",
};

const STATUS_COLORS = [
  { value: "neutral", label: "Gri", color: "#636366" },
  { value: "warning", label: "Sarı", color: "#B26205" },
  { value: "info", label: "Mavi", color: "#0062CC" },
  { value: "danger", label: "Kırmızı", color: "#D92D20" },
  { value: "success", label: "Yeşil", color: "#1F8942" },
];

const StatusColor = ({ value }) => {
  const option = STATUS_COLORS.find((c) => c.value === value);
  if (!option) return <span>{value || "—"}</span>;
  return (
    <span className="inline-flex items-center gap-2">
      <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: option.color }} />
      {option.label}
    </span>
  );
};

export default function MasterData() {
  const [activeKey, setActiveKey] = useState(COLLECTIONS[0].key);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [search, setSearch] = useState("");
  const [currencies, setCurrencies] = useState([]);

  const active = COLLECTIONS.find(c => c.key === activeKey);
  const tableFields = activeKey === "banks"
    ? active.fields.flatMap((field) => field === "balance" ? [field, "current_balance"] : [field])
    : active.fields;

  const load = async () => {
    setLoading(true);
    try {
      if (activeKey === "banks") {
        const [{ data: definitions }, { data: balances }, { data: currencyDefinitions }] = await Promise.all([
          api.get("/master/banks"),
          api.get("/bank-accounts"),
          api.get("/master/currencies"),
        ]);
        setCurrencies(currencyDefinitions);
        const balancesById = new Map(balances.map((bank) => [bank.id, bank]));
        setItems(definitions.map((definition) => ({
          ...definition,
          current_balance: balancesById.get(definition.id)?.current_balance ?? Number(definition.balance || 0),
          balance_currency: balancesById.get(definition.id)?.balance_currency || definition.currency || "TL",
          balance_estimated: balancesById.get(definition.id)?.balance_estimated || false,
        })));
      } else {
        const { data } = await api.get(`/master/${activeKey}`);
        setItems(data);
        if (activeKey === "currencies") setCurrencies(data);
      }
    } catch (e) { toast.error(formatApiError(e)); }
    finally { setLoading(false); }
  };

  useEffect(() => { setSearch(""); load(); /* eslint-disable-next-line */ }, [activeKey]);

  const filtered = items.filter(i => {
    if (!search) return true;
    return Object.values(i).some(v => String(v || "").toLowerCase().includes(search.toLowerCase()));
  });

  const openCreate = () => {
    const defaults = activeKey === "payment_statuses" ? { color: "neutral" }
      : activeKey === "banks" ? { currency: currencies.some((item) => item.code === "USD") ? "USD" : currencies[0]?.code || "TL" }
      : {};
    setEditing(defaults);
    setOpen(true);
  };
  const openEdit = (item) => { setEditing({...item}); setOpen(true); };

  const save = async () => {
    try {
      const payload = { ...editing };
      for (const derivedField of ["current_balance", "balance_currency", "balance_estimated"]) {
        delete payload[derivedField];
      }
      if (editing.id) {
        await api.put(`/master/${activeKey}/${editing.id}`, payload);
        toast.success("Güncellendi");
      } else {
        await api.post(`/master/${activeKey}`, payload);
        toast.success("Eklendi");
      }
      setOpen(false); setEditing(null); load();
    } catch (e) { toast.error(formatApiError(e)); }
  };

  const remove = async (id) => {
    if (!window.confirm("Silinsin mi?")) return;
    await api.delete(`/master/${activeKey}/${id}`);
    toast.success("Silindi"); load();
  };

  return (
    <Page title="Tanımlamalar" subtitle="Master data — tüm dropdown'ların kaynağı">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <Card className="lg:col-span-3 overflow-hidden">
          <div className="px-5 py-4 border-b border-[#E5E5EA]/50">
            <h3 className="text-base font-medium text-[#1D1D1F]">Kategoriler</h3>
            <p className="text-xs text-[#86868B] mt-0.5">{COLLECTIONS.length} bölüm</p>
          </div>
          <div className="py-2 max-h-[75vh] overflow-y-auto">
            {COLLECTIONS.map(c => (
              <button
                key={c.key}
                data-testid={`mcol-${c.key}`}
                onClick={() => setActiveKey(c.key)}
                className={`w-full px-5 py-2 text-left text-sm transition ${activeKey === c.key ? "bg-[#FAFAFA] text-[#1D1D1F] font-medium" : "text-[#3A3A3C] hover:bg-[#FAFAFA]"}`}
              >
                {c.label}
              </button>
            ))}
          </div>
        </Card>

        <Card className="lg:col-span-9 overflow-hidden">
          <div className="px-4 sm:px-6 py-4 border-b border-[#E5E5EA]/50 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-[#1D1D1F]">{active.label}</h3>
              <p className="text-xs text-[#86868B] mt-0.5">{privateValue(filtered.length)} kayıt</p>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative flex-1 sm:flex-initial">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#86868B]"/>
                <Input data-testid="input-master-search" placeholder="Ara…" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 pl-9 w-full sm:w-56 bg-[#F5F5F7] border-0 rounded-lg"/>
              </div>
              <Button data-testid="btn-new-master" onClick={openCreate} className="bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-lg h-9 gap-1.5 shrink-0">
                <Plus className="w-4 h-4"/> Yeni
              </Button>
            </div>
          </div>

          {loading ? (
            <div className="p-6 space-y-3">{[...Array(6)].map((_, i) => <div key={i} className="skeleton h-10 w-full"/>)}</div>
          ) : filtered.length === 0 ? (
            <EmptyState icon={Database} title="Kayıt yok" message="Yeni kayıt ekleyerek başlayın." action={<Button onClick={openCreate} className="bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-lg gap-1.5"><Plus className="w-4 h-4"/>Yeni Ekle</Button>}/>
          ) : (
            <div className="overflow-x-auto max-h-[65vh] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="bg-[#FAFAFA] sticky top-0">
                  <tr className="text-left">
                    {tableFields.map((f) => (
                      <th key={f} className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">{FIELD_LABELS[f] || f}</th>
                    ))}
                    <th className="px-4 py-2.5"></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => (
                    <tr key={row.id} data-testid={`row-master-${row.id}`} onClick={() => openEdit(row)} className="border-b border-[#F5F5F7] hover:bg-[#FAFAFA] cursor-pointer transition">
                      {tableFields.map((f) => (
                        <td key={f} className="px-4 py-2 text-[#1D1D1F] truncate max-w-xs">
                          {activeKey === "payment_statuses" && f === "color" ? <StatusColor value={row[f]} />
                            : activeKey === "banks" && ["balance", "current_balance"].includes(f) ? (
                              <span title={f === "current_balance" && row.balance_estimated ? "Eski farklı dövizli hareketler güncel kurla tahmin edilmiştir" : undefined}>
                                {fmtMoney(row[f], row.balance_currency || row.currency || "TL")}{f === "current_balance" && row.balance_estimated ? " *" : ""}
                              </span>
                            ) : ["balance", "rate_to_tl"].includes(f) ? privateValue(String(row[f] ?? "—")) : String(row[f] ?? "—")}
                        </td>
                      ))}
                      <td className="px-4 py-2 text-right">
                        <button onClick={(e) => { e.stopPropagation(); remove(row.id); }} className="p-1.5 rounded-md hover:bg-[#FFEBEA] text-[#86868B] hover:text-[#D92D20] transition">
                          <Trash2 className="w-4 h-4"/>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="w-full sm:max-w-md overflow-y-auto rounded-l-3xl">
          <SheetHeader>
            <SheetTitle>{editing?.id ? "Düzenle" : "Yeni"} — {active.label}</SheetTitle>
            <SheetDescription>Detayları girin ve kaydedin.</SheetDescription>
          </SheetHeader>
          {editing && (
            <div className="mt-6 space-y-4">
              {active.fields.map((f) => (
                <div key={f} className="space-y-1.5">
                  <Label className="text-[11px] font-semibold uppercase tracking-wider text-[#86868B]">{FIELD_LABELS[f] || f}</Label>
                  {activeKey === "payment_statuses" && f === "color" ? (
                    <Select value={editing.color || ""} onValueChange={(color) => setEditing({ ...editing, color })}>
                      <SelectTrigger data-testid="select-status-color" aria-label="Renk" className="bg-[#F5F5F7] border-0 rounded-lg">
                        <SelectValue placeholder="Renk seçin" />
                      </SelectTrigger>
                      <SelectContent>
                        {editing.color && !STATUS_COLORS.some((c) => c.value === editing.color) && (
                          <SelectItem value={editing.color}>{editing.color}</SelectItem>
                        )}
                        {STATUS_COLORS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            <StatusColor value={option.value} />
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : activeKey === "banks" && f === "currency" ? (
                    <Select value={editing.currency || ""} onValueChange={(currency) => setEditing({ ...editing, currency })}>
                      <SelectTrigger data-testid="select-bank-currency" aria-label="Para Birimi" className="bg-[#F5F5F7] border-0 rounded-lg">
                        <SelectValue placeholder="Para birimi seçin" />
                      </SelectTrigger>
                      <SelectContent className="max-h-72">
                        {editing.currency && !currencies.some((item) => item.code === editing.currency) && (
                          <SelectItem value={editing.currency}>{editing.currency}</SelectItem>
                        )}
                        {currencies.map((item) => (
                          <SelectItem key={item.id || item.code} value={item.code}>
                            {item.code}{item.name ? ` · ${item.name}` : ""}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : <Input
                    data-testid={`input-${f}`}
                    inputMode={["balance", "rate_to_tl"].includes(f) ? "decimal" : undefined}
                    value={editing[f] ?? ""}
                    onChange={(e) => setEditing({...editing, [f]: e.target.value})}
                    className="bg-[#F5F5F7] border-0 rounded-lg"
                  />}
                  {activeKey === "banks" && f === "balance" && (
                    <p className="text-xs text-[#86868B]">Bu alan açılış bakiyesidir. Güncel bakiye ödeme ve tahsilat hareketlerinden otomatik hesaplanır.</p>
                  )}
                </div>
              ))}
              <div className="flex gap-2 pt-4 border-t border-[#E5E5EA]">
                <Button data-testid="btn-save-master" onClick={save} className="bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-lg flex-1">{editing.id ? "Güncelle" : "Kaydet"}</Button>
                <Button variant="outline" onClick={() => setOpen(false)} className="rounded-lg">İptal</Button>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </Page>
  );
}
