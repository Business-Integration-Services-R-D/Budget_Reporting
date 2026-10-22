import { privateValue } from "@/lib/privacy";
import { useEffect, useState } from "react";
import { api, fmtUSD, fmtDate } from "@/lib/api";
import { Page, Card, EmptyState } from "@/components/Primitives";
import { Input } from "@/components/ui/input";
import { Users, Search, X } from "lucide-react";

export default function CurrentAccounts() {
  const [accounts, setAccounts] = useState([]);
  const [filtered, setFiltered] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try { const { data } = await api.get("/current-accounts"); setAccounts(data); setFiltered(data); }
      finally { setLoading(false); }
    })();
  }, []);

  useEffect(() => {
    if (!search) { setFiltered(accounts); return; }
    setFiltered(accounts.filter(a => a.name?.toLowerCase().includes(search.toLowerCase())));
  }, [search, accounts]);

  const openAccount = async (a) => {
    setSelected(a);
    const { data } = await api.get(`/current-accounts/${encodeURIComponent(a.name)}`);
    setDetail(data);
  };

  return (
    <Page title="Cari Hesaplar" subtitle={`${privateValue(accounts.length)} cari · Toplam bakiye USD`}>
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <Card className="lg:col-span-5 overflow-hidden">
          <div className="px-5 py-4 border-b border-[#E5E5EA]/50">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#86868B]"/>
              <Input data-testid="input-search-ca" placeholder="Cari ara…" value={search} onChange={(e) => setSearch(e.target.value)}
                className="h-9 pl-9 bg-[#F5F5F7] border-0 rounded-lg"/>
            </div>
          </div>
          {loading ? (
            <div className="p-5 space-y-3">{[...Array(10)].map((_, i) => <div key={i} className="skeleton h-12 w-full"/>)}</div>
          ) : filtered.length === 0 ? (
            <EmptyState icon={Users} title="Cari hesap yok" message="Borç veya alacak girişi yapın."/>
          ) : (
            <div className="divide-y divide-[#F5F5F7] max-h-[75vh] overflow-y-auto">
              {filtered.map((a, i) => (
                <button
                  key={i}
                  data-testid={`ca-${i}`}
                  onClick={() => openAccount(a)}
                  className={`w-full px-5 py-3 flex items-center justify-between hover:bg-[#FAFAFA] text-left transition ${selected?.name === a.name ? "bg-[#FAFAFA]" : ""}`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-[#1D1D1F] truncate">{a.name}</div>
                    <div className="text-xs text-[#86868B]">{privateValue(a.count)} kayıt</div>
                  </div>
                  <div className="text-right">
                    <div className={`text-sm font-semibold tabular-nums ${a.balance > 0 ? "text-[#D92D20]" : "text-[#1F8942]"}`}>{fmtUSD(a.balance)}</div>
                    <div className="text-[10px] text-[#86868B]">{a.balance > 0 ? "borç" : "bakiye"}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Card>

        <Card className="lg:col-span-7 overflow-hidden">
          {!selected || !detail ? (
            <EmptyState icon={Users} title="Cari seçin" message="Bir cari hesabın detayını görüntülemek için soldan seçin."/>
          ) : (
            <>
              <div className="px-4 sm:px-6 py-4 border-b border-[#E5E5EA]/50 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <h3 className="text-base font-semibold text-[#1D1D1F] truncate">{detail.name}</h3>
                </div>
                <div className="flex gap-4 sm:gap-6 text-right shrink-0">
                  <div>
                    <div className="text-[10px] sm:text-[11px] uppercase tracking-wider text-[#86868B]">Borç</div>
                    <div className="text-sm font-semibold text-[#D92D20] tabular-nums">{fmtUSD(detail.summary.debt)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] sm:text-[11px] uppercase tracking-wider text-[#86868B]">Ödenen</div>
                    <div className="text-sm font-semibold text-[#1F8942] tabular-nums">{fmtUSD(detail.summary.paid)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] sm:text-[11px] uppercase tracking-wider text-[#86868B]">Bakiye</div>
                    <div className="text-sm font-semibold tabular-nums">{fmtUSD(detail.summary.balance)}</div>
                  </div>
                </div>
              </div>
              <div className="overflow-x-auto max-h-[60vh] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="bg-[#FAFAFA] sticky top-0">
                    <tr className="text-left">
                      <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Tarih</th>
                      <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">İşlem</th>
                      <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Açıklama</th>
                      <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">USD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.payables?.map((p, i) => (
                      <tr key={`b-${i}`} className="border-b border-[#F5F5F7]">
                        <td className="px-4 py-2.5 tabular-nums">{fmtDate(p.due_date)}</td>
                        <td className="px-4 py-2.5 text-[#D92D20] font-medium">BORÇ</td>
                        <td className="px-4 py-2.5 truncate max-w-md">{p.description || p.expense_type || "—"}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums">{fmtUSD(p.usd_amount)}</td>
                      </tr>
                    ))}
                    {detail.payments?.map((p, i) => (
                      <tr key={`p-${i}`} className="border-b border-[#F5F5F7]">
                        <td className="px-4 py-2.5 tabular-nums">{fmtDate(p.date)}</td>
                        <td className="px-4 py-2.5 text-[#1F8942] font-medium">{p.type}</td>
                        <td className="px-4 py-2.5 truncate max-w-md">{p.description || p.payment_method || "—"}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums">{fmtUSD(p.usd_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      </div>
    </Page>
  );
}
