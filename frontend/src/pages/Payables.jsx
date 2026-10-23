import { useAuth } from "@/contexts/AuthContext";
import { privateValue } from "@/lib/privacy";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, fmtUSD, fmtDate, formatApiError } from "@/lib/api";
import { Page, Card, StatusBadge, EmptyState } from "@/components/Primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { InlineAddTable, InlineAddToggle, parseMoney, formatMoney } from "@/components/InlineAddTable";
import { Plus, Search, Filter, ArrowDownToLine, ArrowUpFromLine, Loader2, Trash2, CreditCard, X, Paperclip, Sparkles, FileText, Download } from "lucide-react";
import { toast } from "sonner";

const ADD_PANEL_ID = "payable-inline-add";

/**
 * Generic Payables/Receivables list page.
 * kindProp = "PAYABLE" or "RECEIVABLE"
 */
export default function PayablesPage({ kindProp = "PAYABLE", title = "Borçlar" }) {
  const { user } = useAuth();
  const canWrite = ["admin", "manager", "accountant", "finance", "operations"].includes(user?.role);
  const canApprove = ["admin", "manager", "accountant"].includes(user?.role);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [shipFilter, setShipFilter] = useState("all");

  const [masters, setMasters] = useState({ ships: [], vendors: [], expense_types: [], currencies: [], statuses: [], armators: [], companies: [], people: [], countries: [] });
  const [fxRates, setFxRates] = useState([]);
  const addPanelRef = useRef(null);

  const kindLabel = kindProp === "PAYABLE" ? "Borç" : "Alacak";

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ kind: kindProp });
      if (statusFilter !== "all") params.append("status", statusFilter);
      if (shipFilter !== "all") params.append("ship", shipFilter);
      if (search) params.append("search", search);
      const { data } = await api.get(`/payables?${params.toString()}`);
      setItems(data);
    } catch (e) { toast.error(formatApiError(e)); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [statusFilter, shipFilter, kindProp]);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); /* eslint-disable-next-line */ }, [search]);

  useEffect(() => {
    (async () => {
      const [ships, vendors, expTypes, currencies, statuses, armators, companies, people, countries, fx] = await Promise.all([
        api.get("/master/ships"), api.get("/master/vendors"), api.get("/master/expense_types"),
        api.get("/master/currencies"), api.get("/master/payment_statuses"), api.get("/master/armators"),
        api.get("/master/companies"), api.get("/master/people"), api.get("/master/countries"),
        api.get("/fx/latest"),
      ]);
      setMasters({
        ships: ships.data, vendors: vendors.data, expense_types: expTypes.data,
        currencies: currencies.data, statuses: statuses.data, armators: armators.data,
        companies: companies.data, people: people.data, countries: countries.data,
      });
      setFxRates(fx.data);
    })();
  }, []);

  /** Tutarı güncel TCMB kurlarıyla USD'ye çevirir. */
  const toUsd = (amount, code) => {
    if (!amount) return 0;
    if (!code || code === "USD") return amount;
    const from = fxRates.find((c) => c.code === code);
    const usd = fxRates.find((c) => c.code === "USD");
    if (!from?.rate_to_tl || !usd?.rate_to_tl) return 0;
    return (amount * from.rate_to_tl) / usd.rate_to_tl;
  };

  const addRowTemplate = useMemo(() => ({
    order_date: "",
    due_date: "",
    vendor: "",
    ship: "",
    armator: "",
    expense_type: "",
    expense_code: "",
    country: "",
    description: "",
    original_amount: "",
    currency: "USD",
    usd_amount: "",
    status: "ONAY BEKLİYOR",
  }), []);

  const addColumns = useMemo(() => [
    { key: "order_date", label: "Sipariş Tarihi", type: "date", width: 132 },
    { key: "due_date", label: "Vade Tarihi", type: "date", required: true, width: 132, minFrom: "order_date" },
    { key: "vendor", label: "Tedarikçi / Firma", type: "select", width: 200, options: masters.vendors.map((v) => v.name) },
    { key: "ship", label: "Gemi / Birim", type: "select", width: 160, options: masters.ships.map((s) => s.name) },
    { key: "armator", label: "Armatör", type: "select", width: 160, options: masters.armators.map((a) => a.name) },
    { key: "expense_type", label: "Masraf Türü", type: "select", width: 170, options: masters.expense_types.map((e) => e.name) },
    { key: "country", label: "Ülke", type: "select", width: 150, options: masters.countries.map((c) => c.name) },
    { key: "description", label: "Açıklama", type: "text", placeholder: "Açıklama giriniz…", width: 200 },
    { key: "original_amount", label: "Tutar", type: "money", required: true, width: 130 },
    { key: "currency", label: "Para Birimi", type: "select", searchable: false, width: 120, options: masters.currencies.map((c) => c.code) },
    { key: "usd_amount", label: "USD Karşılığı", type: "money", width: 130 },
    { key: "status", label: "Onay", type: "select", searchable: false, width: 160, options: canApprove ? ["TASLAK", "ONAY BEKLİYOR", "ONAYLANDI"] : ["TASLAK", "ONAY BEKLİYOR"] },
  ], [masters, canApprove]);

  /** Vade tarihi en erken sipariş tarihi olabilir. */
  const validateAddRow = (row) => (
    row.order_date && row.due_date && row.due_date < row.order_date
      ? { due_date: "Vade tarihi sipariş tarihinden önce olamaz" }
      : {}
  );

  /** Masraf kodunu masraf türünden, USD karşılığını tutar/para biriminden türetir. */
  const onAddRowChange = ({ row, key, touched }) => {
    if (key === "expense_type") {
      return { expense_code: masters.expense_types.find((e) => e.name === row.expense_type)?.code || "" };
    }
    if ((key === "original_amount" || key === "currency") && !touched.usd_amount) {
      const amount = parseMoney(row.original_amount);
      return { usd_amount: amount ? formatMoney(toUsd(amount, row.currency)) : "" };
    }
    return null;
  };

  const saveNewRows = async (rows) => {
    if (!canWrite) { toast.error("Kayıt düzenleme yetkiniz yok"); return { failed: rows.map((r) => r._id) }; }
    const results = await Promise.allSettled(rows.map((r) => {
      const amount = parseMoney(r.original_amount);
      const usd = parseMoney(r.usd_amount);
      return api.post("/payables", {
        kind: kindProp,
        order_date: r.order_date || null,
        due_date: r.due_date,
        vendor: r.vendor || null,
        ship: r.ship || null,
        armator: r.armator || null,
        expense_type: r.expense_type || null,
        expense_code: r.expense_code || null,
        country: r.country || null,
        description: r.description.trim() || null,
        original_amount: amount,
        currency: r.currency,
        usd_amount: usd || toUsd(amount, r.currency),
        status: r.status,
      });
    }));

    const failed = rows.filter((_, i) => results[i].status === "rejected").map((r) => r._id);
    const savedCount = rows.length - failed.length;
    if (savedCount > 0) {
      toast.success(`${savedCount} ${kindLabel.toLowerCase()} kaydı eklendi`);
      load();
    }
    if (failed.length) {
      toast.error(formatApiError(results.find((r) => r.status === "rejected").reason));
    }
    return { failed };
  };

  const summary = useMemo(() => {
    const total = items.reduce((s, i) => s + (i.usd_amount || 0), 0);
    const open = items.filter(i => !["ÖDENDİ", "İPTAL"].includes(i.status)).reduce((s, i) => s + (i.remaining_usd ?? i.usd_amount ?? 0), 0);
    return { total, open, count: items.length };
  }, [items]);

  const openEdit = (item) => { setEditing(item); setOpen(true); };

  const save = async () => {
    try {
      if (editing.id) {
        await api.put(`/payables/${editing.id}`, editing);
        toast.success("Güncellendi");
      } else {
        await api.post("/payables", editing);
        toast.success("Eklendi");
      }
      setOpen(false); setEditing(null); load();
    } catch (e) { toast.error(formatApiError(e)); }
  };

  const remove = async (id) => {
    if (!window.confirm("Bu kayıt silinsin mi?")) return;
    await api.delete(`/payables/${id}`);
    toast.success("Silindi");
    load();
  };

  return (
    <Page
      title={title}
      subtitle={`${privateValue(summary.count)} kayıt · Açık: ${fmtUSD(summary.open)}`}
      actions={
        <InlineAddToggle
          testId="btn-new-payable"
          open={addOpen}
          onToggle={() => (addOpen ? addPanelRef.current?.requestClose() : setAddOpen(true))}
          label={`${kindLabel} Ekle`}
          controls={ADD_PANEL_ID}
        />
      }
    >
      {/* Inline ekleme tablosu — başlık ile filtreler arasında açılır */}
      <InlineAddTable
        ref={addPanelRef}
        id={ADD_PANEL_ID}
        open={addOpen}
        onClose={() => setAddOpen(false)}
        columns={addColumns}
        rowTemplate={addRowTemplate}
        onSave={saveNewRows}
        onRowChange={onAddRowChange}
        validateRow={validateAddRow}
        storageKey={`marti:draft:payables:${kindProp}`}
        onDraftRestored={() => setAddOpen(true)}
        saveLabel={`${kindLabel}ları Kaydet`}
        regionLabel={`Yeni ${kindLabel} ekleme tablosu`}
        minTableWidth={1920}
        testIdPrefix="payable-add"
      />

      {/* Filters */}
      <Card className="p-4 mb-4 flex gap-3 items-center flex-wrap">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#86868B]"/>
          <Input
            data-testid="input-search"
            placeholder="Açıklama, firma, gemi…"
            value={search} onChange={(e) => setSearch(e.target.value)}
            className="h-9 pl-9 bg-[#F5F5F7] border-0 rounded-lg focus-visible:bg-white"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger data-testid="filter-status" className="w-[180px] h-9 bg-[#F5F5F7] border-0 rounded-lg"><SelectValue/></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tüm durumlar</SelectItem>
            {masters.statuses.map((s) => <SelectItem key={s.id} value={s.name}>{s.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={shipFilter} onValueChange={setShipFilter}>
          <SelectTrigger data-testid="filter-ship" className="w-[180px] h-9 bg-[#F5F5F7] border-0 rounded-lg"><SelectValue/></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tüm gemiler</SelectItem>
            {masters.ships.map((s) => <SelectItem key={s.id} value={s.name}>{s.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </Card>

      {/* Table */}
      <Card className="overflow-hidden">
        {loading ? (
          <div className="p-6 space-y-3">
            {[...Array(6)].map((_, i) => <div key={i} className="skeleton h-10 w-full"/>)}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={kindProp === "PAYABLE" ? ArrowDownToLine : ArrowUpFromLine}
            title="Henüz kayıt yok"
            message={`Yeni bir ${kindLabel.toLowerCase()} ekleyerek başlayabilirsiniz.`}
            action={<Button onClick={() => setAddOpen(true)} className="bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-lg gap-1.5"><Plus className="w-4 h-4"/>Yeni Ekle</Button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[#FAFAFA] border-b border-[#E5E5EA] sticky top-0">
                <tr className="text-left">
                  <th className="px-4 py-3 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Vade</th>
                  <th className="px-4 py-3 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Tedarikçi</th>
                  <th className="px-4 py-3 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Gemi / Birim</th>
                  <th className="px-4 py-3 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Masraf</th>
                  <th className="px-4 py-3 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">Tutar</th>
                  <th className="px-4 py-3 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">USD</th>
                  <th className="px-4 py-3 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Durum</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr
                    key={p.id}
                    data-testid={`row-payable-${p.id}`}
                    onClick={() => openEdit(p)}
                    className="border-b border-[#F5F5F7] hover:bg-[#FAFAFA] cursor-pointer transition"
                  >
                    <td className="px-4 py-3 text-[#1D1D1F] whitespace-nowrap tabular-nums">{fmtDate(p.due_date)}</td>
                    <td className="px-4 py-3 text-[#1D1D1F] max-w-xs truncate">{p.vendor || "—"}</td>
                    <td className="px-4 py-3 text-[#3A3A3C]">{p.ship || "—"}</td>
                    <td className="px-4 py-3 text-[#3A3A3C] text-xs">{p.expense_type || "—"}</td>
                    <td className="px-4 py-3 text-right tabular-nums text-[#1D1D1F]">{privateValue(p.original_amount?.toLocaleString("tr-TR"))} <span className="text-[#86868B]">{p.currency}</span></td>
                    <td className="px-4 py-3 text-right tabular-nums font-medium text-[#1D1D1F]">{fmtUSD(p.usd_amount)}{p.remaining_usd != null && <div className="text-xs font-normal text-[#86868B]">Kalan {fmtUSD(p.remaining_usd)}</div>}</td>
                    <td className="px-4 py-3"><StatusBadge value={p.status}/></td>
                    <td className="px-4 py-3 text-right">
                      <button
                        data-testid={`btn-delete-${p.id}`}
                        onClick={(e) => { e.stopPropagation(); remove(p.id); }}
                        className="p-1.5 rounded-md hover:bg-[#FFEBEA] text-[#86868B] hover:text-[#D92D20] transition"
                      ><Trash2 className="w-4 h-4"/></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Slide-over form */}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="w-full sm:max-w-xl overflow-y-auto rounded-l-3xl border-l border-[#E5E5EA]">
          <SheetHeader>
            <SheetTitle data-testid="form-title">{editing?.id ? "Kaydı Düzenle" : `Yeni ${kindProp === "PAYABLE" ? "Borç" : "Alacak"}`}</SheetTitle>
            <SheetDescription>Borç bilgilerini doldurun. USD karşılığı otomatik hesaplanır.</SheetDescription>
          </SheetHeader>

          {editing && (
            <div className="mt-6 space-y-4">
              {/* OCR Action */}
              {!editing.id && (
                <OCRBlock onParsed={(parsed) => setEditing({
                  ...editing,
                  vendor: parsed.vendor || editing.vendor,
                  description: parsed.description || editing.description,
                  due_date: parsed.due_date || editing.due_date,
                  order_date: parsed.invoice_date || editing.order_date,
                  original_amount: parsed.original_amount ?? editing.original_amount,
                  currency: parsed.currency || editing.currency,
                  country: parsed.country || editing.country,
                })}/>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Sipariş Tarihi">
                  <Input data-testid="input-order-date" type="date" value={editing.order_date?.slice(0,10) || ""} onChange={(e) => setEditing({...editing, order_date: e.target.value})}/>
                </Field>
                <Field label="Vade Tarihi *">
                  <Input data-testid="input-due-date" type="date" value={editing.due_date?.slice(0,10) || ""} onChange={(e) => setEditing({...editing, due_date: e.target.value})}/>
                </Field>
              </div>

              <Field label="Tedarikçi / Firma">
                <SelectField testid="select-vendor" value={editing.vendor} onChange={(v) => setEditing({...editing, vendor: v})} options={masters.vendors.map(v => v.name)}/>
              </Field>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Gemi / Birim">
                  <SelectField testid="select-ship" value={editing.ship} onChange={(v) => setEditing({...editing, ship: v})} options={masters.ships.map(s => s.name)}/>
                </Field>
                <Field label="Armatör">
                  <SelectField testid="select-armator" value={editing.armator} onChange={(v) => setEditing({...editing, armator: v})} options={masters.armators.map(a => a.name)}/>
                </Field>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Masraf Türü">
                  <SelectField testid="select-expense" value={editing.expense_type} onChange={(v) => {
                    const item = masters.expense_types.find(e => e.name === v);
                    setEditing({...editing, expense_type: v, expense_code: item?.code});
                  }} options={masters.expense_types.map(e => e.name)}/>
                </Field>
                <Field label="Ülke">
                  <SelectField testid="select-country" value={editing.country} onChange={(v) => setEditing({...editing, country: v})} options={masters.countries.map(c => c.name)}/>
                </Field>
              </div>

              <Field label="Açıklama">
                <Textarea data-testid="input-description" value={editing.description || ""} onChange={(e) => setEditing({...editing, description: e.target.value})} rows={2} className="bg-[#F5F5F7] border-0 rounded-lg"/>
              </Field>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <Field label="Tutar *">
                  <Input data-testid="input-amount" type="number" step="0.01" value={editing.original_amount || ""} onChange={(e) => setEditing({...editing, original_amount: parseFloat(e.target.value) || 0})}/>
                </Field>
                <Field label="Para Birimi">
                  <SelectField testid="select-currency" value={editing.currency} onChange={(v) => setEditing({...editing, currency: v})} options={masters.currencies.map(c => c.code)}/>
                </Field>
                <Field label="USD Karşılığı">
                  <Input data-testid="input-usd-amount" type="number" step="0.01" value={editing.usd_amount || ""} onChange={(e) => setEditing({...editing, usd_amount: parseFloat(e.target.value) || 0})}/>
                </Field>
              </div>

              <Field label="Belge onayı">
                {editing.status === "İPTAL" ? <StatusBadge value="İPTAL" /> : <Select value={editing.approval_status || (editing.status === "TASLAK" ? "draft" : editing.status === "ONAY BEKLİYOR" ? "pending" : "approved")} onValueChange={(approval_status) => setEditing({ ...editing, approval_status })}>
                  <SelectTrigger aria-label="Belge onayı" className="bg-[#F5F5F7] border-0 rounded-lg"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="draft">Taslak</SelectItem><SelectItem value="pending">Onay bekliyor</SelectItem><SelectItem value="approved" disabled={!canApprove}>Onaylandı</SelectItem></SelectContent>
                </Select>}
              </Field>
              <Field label="Ödeme durumu">
                <span className="text-sm">{editing.payment_status === "paid" || editing.status === "ÖDENDİ" ? "Tamamlandı" : editing.payment_status === "partial" || editing.status === "KISMİ ÖDEME" ? "Kısmi ödeme" : "Henüz ödeme/tahsilat yok"}</span>
                <p className="mt-1 text-xs text-[#86868B]">Ödeme durumu bağlı hareketlerden hesaplanır. Belge onayı ayrı izlenir.</p>
              </Field>

              {/* Dosya Ekleri (sadece edit modunda — id varsa) */}
              {editing.id && <AttachmentsBlock resource="payable" resourceId={editing.id}/>}

              <div className="flex gap-2 pt-4 border-t border-[#E5E5EA]">
                <Button disabled={!canWrite} data-testid="btn-save" onClick={save} className="bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-lg flex-1">
                  {editing.id ? "Güncelle" : "Kaydet"}
                </Button>
                <Button variant="outline" onClick={() => setOpen(false)} className="rounded-lg">İptal</Button>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </Page>
  );
}

const Field = ({ label, children }) => (
  <div className="space-y-1.5">
    <Label className="text-[11px] font-semibold uppercase tracking-wider text-[#86868B]">{label}</Label>
    {children}
  </div>
);

const SelectField = ({ value, onChange, options, testid }) => (
  <Select value={value || ""} onValueChange={onChange}>
    <SelectTrigger data-testid={testid} className="bg-[#F5F5F7] border-0 rounded-lg"><SelectValue placeholder="Seçin"/></SelectTrigger>
    <SelectContent className="max-h-80">
      {options.filter(Boolean).map((o, i) => <SelectItem key={i} value={o}>{o}</SelectItem>)}
    </SelectContent>
  </Select>
);

const OCRBlock = ({ onParsed }) => {
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  const handle = async (file) => {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post("/ocr/invoice", form, { headers: { "Content-Type": "multipart/form-data" } });
      if (data?.error) {
        toast.error("OCR hatası: " + data.error);
      } else {
        onParsed(data || {});
        toast.success("Fatura okundu — form alanları dolduruldu");
      }
    } catch (e) {
      toast.error(formatApiError(e));
    } finally { setBusy(false); }
  };

  return (
    <div className="rounded-xl border border-dashed border-[#E5E5EA] bg-gradient-to-br from-[#FAFAFA] to-white p-4">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-[#111111] to-[#2C2C2E] grid place-items-center shrink-0">
          <Sparkles className="w-4 h-4 text-white" strokeWidth={1.5}/>
        </div>
        <div className="flex-1">
          <div className="text-sm font-medium text-[#1D1D1F]">Fatura görselinden otomatik doldur</div>
          <div className="text-xs text-[#86868B] mt-0.5">PDF/JPG/PNG yükle — AI ile tedarikçi, tutar, vade okunsun</div>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,application/pdf"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handle(e.target.files[0])}
        />
        <Button
          data-testid="btn-ocr"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          variant="outline"
          className="rounded-lg gap-1.5 h-9 shrink-0"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin"/> : <Sparkles className="w-4 h-4"/>}
          {busy ? "Okunuyor..." : "OCR ile Doldur"}
        </Button>
      </div>
    </div>
  );
};

const AttachmentsBlock = ({ resource, resourceId }) => {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef(null);

  const load = async () => {
    try {
      const { data } = await api.get(`/uploads/by-resource/${resource}/${resourceId}`);
      setFiles(data);
    } catch {}
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [resourceId]);

  const handleUpload = async (file) => {
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("attached_to", resource);
      form.append("attached_id", resourceId);
      await api.post("/uploads", form, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Dosya yüklendi");
      load();
    } catch (e) { toast.error(formatApiError(e)); }
    finally { setUploading(false); }
  };

  const removeFile = async (id) => {
    if (!window.confirm("Bu dosya silinsin mi?")) return;
    await api.delete(`/uploads/${id}`);
    toast.success("Silindi");
    load();
  };

  const downloadFile = (id, name) => {
    api.get(`/uploads/${id}`, { responseType: "blob" })
      .then((response) => {
        const blob = response.data;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e) => toast.error(formatApiError(e)));
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-[11px] font-semibold uppercase tracking-wider text-[#86868B]">Ekler ({files.length})</Label>
        <input
          ref={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/webp,application/pdf"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
        />
        <Button
          data-testid="btn-attach"
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
          variant="outline"
          size="sm"
          className="h-7 rounded-md text-xs gap-1.5"
        >
          {uploading ? <Loader2 className="w-3 h-3 animate-spin"/> : <Paperclip className="w-3 h-3"/>}
          Dosya Ekle
        </Button>
      </div>
      {files.length === 0 ? (
        <div className="text-xs text-[#86868B] italic">Henüz ek yok</div>
      ) : (
        <div className="space-y-1.5">
          {files.map((f) => (
            <div key={f.id} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#F5F5F7] text-xs">
              <FileText className="w-3.5 h-3.5 text-[#86868B] shrink-0"/>
              <span className="truncate flex-1 text-[#1D1D1F]">{f.filename}</span>
              <span className="text-[#86868B]">{(f.size / 1024).toFixed(0)} KB</span>
              <button onClick={() => downloadFile(f.id, f.filename)} className="p-1 rounded hover:bg-white text-[#86868B] hover:text-[#1D1D1F]">
                <Download className="w-3.5 h-3.5"/>
              </button>
              <button onClick={() => removeFile(f.id)} className="p-1 rounded hover:bg-[#FFEBEA] text-[#86868B] hover:text-[#D92D20]">
                <Trash2 className="w-3.5 h-3.5"/>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
