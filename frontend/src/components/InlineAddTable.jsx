/**
 * Inline (sayfa akışı içinde açılan) çok satırlı kayıt ekleme tablosu.
 * Modal/drawer kullanmaz — başlık ile filtreler arasında yumuşak biçimde açılıp kapanır.
 */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Card } from "@/components/Primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { cn } from "@/lib/utils";
import { Plus, Trash2, Loader2, ChevronDown, Check } from "lucide-react";
import { toast } from "sonner";

const ANIM_MS = 260;

let rowSeq = 0;
const nextRowId = () => `row-${Date.now().toString(36)}-${(rowSeq += 1)}`;

/** "1.250,50" / "1250.5" / 1250.5 → 1250.5 */
export const parseMoney = (raw) => {
  if (typeof raw === "number") return raw;
  if (!raw) return 0;
  let s = String(raw).trim().replace(/\s/g, "");
  if (!s) return 0;
  if (s.includes(",")) {
    s = s.replace(/\./g, "").replace(",", ".");
  } else {
    const parts = s.split(".");
    // Tek nokta ve son grup 1-2 haneli ise ondalık ayırıcı, aksi halde binlik
    if (parts.length > 2 || (parts.length === 2 && parts[1].length === 3)) s = parts.join("");
  }
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : 0;
};

export const formatMoney = (n, decimals = 2) =>
  new Intl.NumberFormat("tr-TR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(n || 0);

/** Sayısal hücrelerde yalnızca rakam ve ayırıcılara izin verir. */
const sanitizeNumeric = (s) => s.replace(/[^\d.,-]/g, "");

/** Uzun listelerde arama gerekir; kısa listelerde düz select yeterli. */
const isSearchable = (column) => column.searchable ?? (column.options?.length || 0) > 20;

const MAX_DATE = "2099-12-31";

/**
 * Tarih alanında yıl üst sınırını uygular. Native date input 4 haneden uzun yıl
 * yazılmasına izin verdiği için taşan değer üst sınıra çekilir.
 */
const clampDate = (value, max = MAX_DATE) => {
  if (!value) return value;
  const [year] = value.split("-");
  if (year.length > 4 || value > max) return max;
  return value;
};

const CELL_CLASS =
  "h-9 w-full bg-[#F5F5F7] border-0 shadow-none rounded-lg text-[13px] text-[#1D1D1F] placeholder:text-[#A1A1A6] focus-visible:bg-white focus-visible:ring-1 focus-visible:ring-[#007AFF]";
const CELL_ERROR_CLASS = "bg-[#FFF1F0] ring-1 ring-[#FECDCB] focus-visible:ring-[#D92D20]";

export const makeEmptyRow = (template) => ({ ...template, _id: nextRowId() });

/** Sayfa yenilendiğinde kaybolmasın diye doldurulan satırlar yerel taslakta tutulur. */
const readDraft = (storageKey, template) => {
  if (!storageKey) return null;
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || !parsed.length) return null;
    return parsed.map((row) => ({ ...template, ...row, _id: row?._id || nextRowId() }));
  } catch {
    return null;
  }
};

const writeDraft = (storageKey, rows) => {
  if (!storageKey) return;
  try {
    if (!rows.length) window.localStorage.removeItem(storageKey);
    else window.localStorage.setItem(storageKey, JSON.stringify(rows));
  } catch {
    /* kota dolu veya depolama kapalı — taslak atlanır */
  }
};

/** Sayfa başlığındaki aç/kapa butonu */
export const InlineAddToggle = ({ open, onToggle, label, controls, testId }) => (
  <Button
    type="button"
    data-testid={testId}
    aria-expanded={open}
    aria-controls={controls}
    onClick={onToggle}
    className="bg-[#111111] hover:bg-[#2C2C2E] text-white gap-1.5 rounded-lg h-9"
  >
    {!open && <Plus className="w-4 h-4" />}
    {label}
    <ChevronDown className={cn("w-4 h-4 transition-transform duration-200 ease-out", open && "-rotate-180")} />
  </Button>
);

export const InlineAddTable = forwardRef(({
  id,
  open,
  onClose,
  columns,
  rowTemplate,
  onSave,
  onRowChange,
  storageKey,
  onDraftRestored,
  saveLabel,
  regionLabel,
  validateRow,
  minTableWidth = 960,
  testIdPrefix = "inline-add",
}, ref) => {
  const restoredDraft = useRef(readDraft(storageKey, rowTemplate));
  const [mounted, setMounted] = useState(open);
  const [expanded, setExpanded] = useState(open);
  const [rows, setRows] = useState(() => restoredDraft.current || [makeEmptyRow(rowTemplate)]);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [confirmingClose, setConfirmingClose] = useState(false);
  const [contentHeight, setContentHeight] = useState(0);

  const innerRef = useRef(null);

  const isRowEmpty = useCallback(
    (row) => columns.every((c) => String(row[c.key] ?? "") === String(rowTemplate[c.key] ?? "")),
    [columns, rowTemplate]
  );

  const filledRows = useMemo(() => rows.filter((r) => !isRowEmpty(r)), [rows, isRowEmpty]);
  const isDirty = filledRows.length > 0;

  /**
   * Alanlar arası kurallar (ör. vade ≥ sipariş tarihi) satırlardan türetilir;
   * böylece taslak geri yüklendiğinde de uyarı ilk render'da görünür.
   */
  const crossErrors = useMemo(() => {
    if (!validateRow) return {};
    const map = {};
    rows.forEach((r) => {
      const rowErrors = validateRow(r);
      if (rowErrors && Object.keys(rowErrors).length) map[r._id] = rowErrors;
    });
    return map;
  }, [rows, validateRow]);

  const reset = useCallback(() => {
    setRows([makeEmptyRow(rowTemplate)]);
    setErrors({});
    setConfirmingClose(false);
  }, [rowTemplate]);

  // Yenileme sonrası taslak varsa panel kendiliğinden açılır
  useEffect(() => {
    if (!restoredDraft.current) return;
    restoredDraft.current = null;
    onDraftRestored?.();
    toast.info("Kaydedilmemiş taslağınız geri yüklendi");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Doldurulmuş satırları yerel taslakta tut
  useEffect(() => {
    writeDraft(storageKey, filledRows);
  }, [filledRows, storageKey]);

  // Açılma / kapanma: kapanış animasyonu bitene kadar içerik DOM'da kalır
  const hasOpened = useRef(open);
  useEffect(() => {
    if (open) {
      hasOpened.current = true;
      setMounted(true);
      const raf = requestAnimationFrame(() => setExpanded(true));
      return () => cancelAnimationFrame(raf);
    }
    setExpanded(false);
    // Hiç açılmamışsa (ör. ilk render) taslağı temizlemeye gerek yok
    if (!hasOpened.current) return;
    const t = setTimeout(() => {
      setMounted(false);
      reset();
    }, ANIM_MS);
    return () => clearTimeout(t);
  }, [open, reset]);

  // İçerik yüksekliğini izle — satır eklendiğinde de yumuşak büyüme
  useLayoutEffect(() => {
    const el = innerRef.current;
    if (!mounted || !el) return;
    const update = () => setContentHeight(el.offsetHeight);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [mounted]);

  // Açıldığında ilk hücreye odaklan
  useEffect(() => {
    if (!expanded) return;
    const t = setTimeout(() => {
      const first = innerRef.current?.querySelector("tbody input");
      first?.focus({ preventScroll: true });
    }, ANIM_MS);
    return () => clearTimeout(t);
  }, [expanded]);

  const setCell = (rowId, key, value) => {
    const target = rows.find((r) => r._id === rowId);
    if (!target) return;
    // Elle dokunulan alanlar otomatik hesaplamayla ezilmez
    const touched = { ...(target._touched || {}), [key]: true };
    let next = { ...target, [key]: value, _touched: touched };
    const patch = onRowChange?.({ row: next, key, touched });
    if (patch) next = { ...next, ...patch };

    setRows((prev) => prev.map((r) => (r._id === rowId ? next : r)));
    setErrors((prev) => {
      if (!prev[rowId]?.[key]) return prev;
      const cleared = { ...prev, [rowId]: { ...prev[rowId] } };
      delete cleared[rowId][key];
      return cleared;
    });
  };

  const addRow = () => setRows((prev) => [...prev, makeEmptyRow(rowTemplate)]);

  const removeRow = (rowId) => {
    setErrors((prev) => {
      const next = { ...prev };
      delete next[rowId];
      return next;
    });
    setRows((prev) => (prev.length === 1 ? [makeEmptyRow(rowTemplate)] : prev.filter((r) => r._id !== rowId)));
  };

  const validate = useCallback(
    (row) => {
      const rowErrors = {};
      columns.forEach((c) => {
        if (!c.required) return;
        if (c.type === "money") {
          if (parseMoney(row[c.key]) <= 0) rowErrors[c.key] = "Tutar giriniz";
        } else if (!String(row[c.key] ?? "").trim()) {
          rowErrors[c.key] = "Zorunlu alan";
        }
      });
      return { ...rowErrors, ...(validateRow?.(row) || {}) };
    },
    [columns, validateRow]
  );

  const requestClose = useCallback(() => {
    if (!isDirty) {
      onClose();
      return;
    }
    setConfirmingClose(true);
  }, [isDirty, onClose]);

  // Başlıktaki aç/kapa butonu da aynı onay akışını kullanır
  useImperativeHandle(ref, () => ({ requestClose }), [requestClose]);

  const discardAndClose = () => {
    setConfirmingClose(false);
    onClose();
  };

  const submit = async () => {
    if (saving) return;
    if (!filledRows.length) {
      toast.error("Kaydedilecek satır yok");
      return;
    }
    const nextErrors = {};
    filledRows.forEach((r) => {
      const e = validate(r);
      if (Object.keys(e).length) nextErrors[r._id] = e;
    });
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) {
      toast.error("Eksik veya hatalı alanlar var");
      return;
    }

    setSaving(true);
    try {
      const result = await onSave(filledRows);
      const failed = result?.failed || [];
      if (failed.length) {
        setRows((prev) => prev.filter((r) => failed.includes(r._id)));
        return;
      }
      onClose();
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key !== "Escape" || saving) return;
    e.stopPropagation();
    if (isDirty) setConfirmingClose(true);
    else onClose();
  };

  const suggestionColumns = useMemo(() => columns.filter((c) => c.suggestions?.length), [columns]);

  return (
    <div
      id={id}
      role="region"
      aria-label={regionLabel}
      aria-hidden={!expanded}
      style={{ maxHeight: expanded ? contentHeight : 0 }}
      className="overflow-hidden transition-[max-height] duration-[260ms] ease-out"
    >
      <div ref={innerRef} className="pb-4">
        {mounted && (
          <Card className="overflow-hidden" onKeyDown={handleKeyDown}>
            {suggestionColumns.map((c) => (
              <datalist key={c.key} id={`${id}-${c.key}-options`}>
                {c.suggestions.map((o) => (
                  <option key={o} value={o} />
                ))}
              </datalist>
            ))}

            <div className="overflow-x-auto">
              <table className="w-full text-sm" style={{ minWidth: minTableWidth }}>
                <thead>
                  <tr className="border-b border-[#E5E5EA]">
                    {columns.map((c) => (
                      <th
                        key={c.key}
                        scope="col"
                        style={{ width: c.width }}
                        className="px-3 py-3 text-left text-[13px] font-medium text-[#1D1D1F] whitespace-nowrap"
                      >
                        {c.label}
                        {c.required && <span className="text-[#D92D20]"> *</span>}
                      </th>
                    ))}
                    <th scope="col" className="px-3 py-3 text-right text-[13px] font-medium text-[#1D1D1F] w-[72px]">
                      İşlem
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, rowIndex) => (
                    <tr key={row._id} className="border-b border-[#F5F5F7]" data-testid={`${testIdPrefix}-row`}>
                      {columns.map((c) => {
                        const fieldId = `${id}-${row._id}-${c.key}`;
                        const error = errors[row._id]?.[c.key] || crossErrors[row._id]?.[c.key];
                        return (
                          <td key={c.key} className="px-3 py-2.5 align-top">
                            <label htmlFor={fieldId} className="sr-only">
                              {`${rowIndex + 1}. satır ${c.label}`}
                            </label>
                            <Cell
                              id={fieldId}
                              column={c}
                              listId={c.suggestions?.length ? `${id}-${c.key}-options` : undefined}
                              value={row[c.key] ?? ""}
                              min={c.minFrom ? row[c.minFrom] || undefined : undefined}
                              invalid={Boolean(error)}
                              onChange={(v) => setCell(row._id, c.key, v)}
                            />
                            {error && <p className="mt-1 text-[11px] text-[#D92D20] whitespace-nowrap">{error}</p>}
                          </td>
                        );
                      })}
                      <td className="px-3 py-2.5 align-top text-right">
                        <button
                          type="button"
                          data-testid={`${testIdPrefix}-row-delete`}
                          onClick={() => removeRow(row._id)}
                          aria-label={`${rowIndex + 1}. satırı sil`}
                          className="mt-1 p-1.5 rounded-md text-[#A1A1A6] hover:bg-[#FFEBEA] hover:text-[#D92D20] transition-colors"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {confirmingClose && (
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 border-t border-[#FCE088] bg-[#FFFBEB]">
                <span className="text-[13px] text-[#B26205]">
                  {filledRows.length} satırda kaydedilmemiş veri var. Yine de kapatılsın mı?
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setConfirmingClose(false)}
                    className="h-8 rounded-lg text-[13px] text-[#3A3A3C] hover:bg-[#F5F5F7]"
                  >
                    Vazgeç
                  </Button>
                  <Button
                    type="button"
                    data-testid={`${testIdPrefix}-discard`}
                    onClick={discardAndClose}
                    className="h-8 rounded-lg bg-[#111111] hover:bg-[#2C2C2E] text-white text-[13px]"
                  >
                    Kapat ve sil
                  </Button>
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-3 border-t border-[#F5F5F7]">
              <Button
                type="button"
                variant="ghost"
                data-testid={`${testIdPrefix}-new-row`}
                onClick={addRow}
                className="h-8 gap-1.5 rounded-lg text-[13px] text-[#3A3A3C] hover:bg-[#F5F5F7]"
              >
                <Plus className="w-4 h-4" /> Yeni Satır
              </Button>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  data-testid={`${testIdPrefix}-cancel`}
                  onClick={requestClose}
                  disabled={saving}
                  className="h-9 rounded-lg text-[13px] text-[#3A3A3C] hover:bg-[#F5F5F7]"
                >
                  Vazgeç
                </Button>
                <Button
                  type="button"
                  data-testid={`${testIdPrefix}-save`}
                  onClick={submit}
                  disabled={saving}
                  className="h-9 rounded-lg bg-[#111111] hover:bg-[#2C2C2E] text-white text-[13px] gap-1.5"
                >
                  {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                  {saving ? "Kaydediliyor…" : saveLabel}
                </Button>
              </div>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
});

InlineAddTable.displayName = "InlineAddTable";

const Cell = ({ id, column, value, onChange, invalid, listId, min }) => {
  const cls = cn(CELL_CLASS, invalid && CELL_ERROR_CLASS);

  if (column.type === "select") {
    if (isSearchable(column)) {
      return <SearchableSelect id={id} column={column} value={value} onChange={onChange} className={cls} invalid={invalid} />;
    }
    return (
      <Select value={value || ""} onValueChange={onChange}>
        <SelectTrigger id={id} aria-invalid={invalid} className={cn(cls, "[&>span]:truncate")}>
          <SelectValue placeholder={column.placeholder || "Seçin"} />
        </SelectTrigger>
        <SelectContent className="max-h-72">
          {(column.options || []).filter(Boolean).map((o) => (
            <SelectItem key={o} value={o}>
              {column.optionLabel ? column.optionLabel(o) : o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (column.type === "date") {
    return (
      <Input
        id={id}
        type="date"
        aria-invalid={invalid}
        min={min}
        max={column.max || MAX_DATE}
        value={value || ""}
        onChange={(e) => onChange(clampDate(e.target.value, column.max || MAX_DATE))}
        className={cn(cls, "tabular-nums")}
      />
    );
  }

  if (column.type === "money") {
    const decimals = column.decimals ?? 2;
    return (
      <Input
        id={id}
        type="text"
        inputMode="decimal"
        aria-invalid={invalid}
        placeholder={column.placeholder || formatMoney(0, decimals)}
        value={value ?? ""}
        onChange={(e) => onChange(sanitizeNumeric(e.target.value))}
        onBlur={(e) => {
          const raw = e.target.value.trim();
          onChange(raw ? formatMoney(parseMoney(raw), decimals) : "");
        }}
        className={cn(cls, "tabular-nums")}
      />
    );
  }

  return (
    <Input
      id={id}
      type="text"
      list={listId}
      aria-invalid={invalid}
      placeholder={column.placeholder}
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
      className={cls}
    />
  );
};

/** Uzun tanım listeleri için arama kutulu, yalnızca listeden seçim yapılan alan. */
const SearchableSelect = ({ id, column, value, onChange, className, invalid }) => {
  const [open, setOpen] = useState(false);
  const options = useMemo(() => (column.options || []).filter(Boolean), [column.options]);

  const pick = (option) => {
    onChange(option);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          id={id}
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-invalid={invalid}
          className={cn(className, "flex items-center justify-between gap-1 px-3 text-left")}
        >
          <span className={cn("truncate", !value && "text-[#A1A1A6]")}>{(value && column.optionLabel ? column.optionLabel(value) : value) || column.placeholder || "Seçin"}</span>
          <ChevronDown className="w-4 h-4 shrink-0 text-[#86868B]" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className={cn("max-w-[90vw] p-0 rounded-xl", column.optionLabel ? "w-[560px]" : "w-[300px]")}>
        <Command>
          <CommandInput placeholder={`${column.label} ara…`} />
          <CommandList>
            <CommandEmpty>Sonuç bulunamadı</CommandEmpty>
            <CommandGroup>
              {value && (
                <CommandItem value="__clear__" onSelect={() => pick("")} className="text-[#86868B]">
                  Seçimi temizle
                </CommandItem>
              )}
              {options.map((o) => (
                <CommandItem key={o} value={column.optionLabel ? `${column.optionLabel(o)} ${o}` : o} onSelect={() => pick(o)}>
                  <Check className={cn("w-4 h-4", value === o ? "opacity-100" : "opacity-0")} />
                  <span className={column.optionLabel ? "whitespace-normal" : "truncate"}>{column.optionLabel ? column.optionLabel(o) : o}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
};
