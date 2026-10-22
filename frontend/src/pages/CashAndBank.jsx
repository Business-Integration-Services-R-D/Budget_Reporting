import { privateValue } from "@/lib/privacy";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtUSD, fmtDate } from "@/lib/api";
import { Page, Card, EmptyState, StatusBadge } from "@/components/Primitives";
import { Wallet, ArrowRight, ArrowDownToLine, ArrowUpFromLine } from "lucide-react";

export default function CashAndBank() {
  const [banks, setBanks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [tx, setTx] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      try { const { data } = await api.get("/bank-accounts"); setBanks(data); }
      finally { setLoading(false); }
    })();
  }, []);

  const openBank = async (b) => {
    setSelected(b);
    const { data } = await api.get(`/bank-accounts/${encodeURIComponent(b.name)}/transactions`);
    setTx(data);
  };

  return (
    <Page title="Kasa & Banka" subtitle={`${privateValue(banks.length)} hesap`}>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-1 overflow-hidden">
          <div className="px-4 sm:px-6 py-4 border-b border-[#E5E5EA]/50">
            <h3 className="text-base font-medium text-[#1D1D1F]">Hesaplar</h3>
            <p className="text-xs text-[#86868B] mt-0.5">Net hareket (Tahsil − Tediye)</p>
          </div>
          {loading ? (
            <div className="p-6 space-y-3">{[...Array(8)].map((_, i) => <div key={i} className="skeleton h-12 w-full"/>)}</div>
          ) : (
            <div className="divide-y divide-[#F5F5F7] max-h-[70vh] overflow-y-auto">
              {banks.map((b, i) => (
                <button
                  key={i}
                  data-testid={`bank-${b.name}`}
                  onClick={() => openBank(b)}
                  className={`w-full px-5 py-3 flex items-center justify-between hover:bg-[#FAFAFA] text-left transition ${selected?.name === b.name ? "bg-[#FAFAFA]" : ""}`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-[#1D1D1F] truncate">{b.name}</div>
                    <div className="text-xs text-[#86868B]">{b.type || "Banka"}</div>
                  </div>
                  <div className="text-right">
                    <div className={`text-sm font-semibold tabular-nums ${b.net >= 0 ? "text-[#1F8942]" : "text-[#D92D20]"}`}>{fmtUSD(b.net)}</div>
                    <div className="text-[10px] text-[#86868B]">net</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Card>

        <Card className="lg:col-span-2 overflow-hidden">
          {!selected ? (
            <EmptyState icon={Wallet} title="Hesap seçin" message="Soldan bir banka veya kasa hesabı seçerek hareketlerini görüntüleyin."/>
          ) : (
            <>
              <div className="px-4 sm:px-6 py-4 border-b border-[#E5E5EA]/50 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                  <h3 className="text-base font-medium text-[#1D1D1F]">{selected.name}</h3>
                  <p className="text-xs text-[#86868B] mt-0.5">{privateValue(tx.length)} hareket</p>
                </div>
                <div className="flex gap-4 sm:gap-6 text-right">
                  <div>
                    <div className="text-[10px] sm:text-[11px] uppercase tracking-wider text-[#86868B]">Giren</div>
                    <div className="text-sm font-semibold text-[#1F8942] tabular-nums">{fmtUSD(selected.in)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] sm:text-[11px] uppercase tracking-wider text-[#86868B]">Çıkan</div>
                    <div className="text-sm font-semibold text-[#D92D20] tabular-nums">{fmtUSD(selected.out)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] sm:text-[11px] uppercase tracking-wider text-[#86868B]">Net</div>
                    <div className="text-sm font-semibold tabular-nums">{fmtUSD(selected.net)}</div>
                  </div>
                </div>
              </div>
              <div className="overflow-x-auto max-h-[60vh] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="bg-[#FAFAFA] sticky top-0">
                    <tr className="text-left">
                      <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Tarih</th>
                      <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Tip</th>
                      <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Açıklama</th>
                      <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">Tutar</th>
                      <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">USD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tx.map((t, i) => (
                      <tr key={i} className="border-b border-[#F5F5F7] hover:bg-[#FAFAFA]">
                        <td className="px-4 py-2.5 tabular-nums">{fmtDate(t.date)}</td>
                        <td className="px-4 py-2.5"><StatusBadge value={t.type}/></td>
                        <td className="px-4 py-2.5">
                          <div className="font-medium truncate max-w-md">{t.vendor || t.description || "—"}</div>
                          <div className="text-xs text-[#86868B]">{t.ship || ""}</div>
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums">{privateValue(t.amount?.toLocaleString("tr-TR"))} <span className="text-[#86868B]">{t.currency}</span></td>
                        <td className="px-4 py-2.5 text-right tabular-nums font-medium">{fmtUSD(t.usd_amount)}</td>
                      </tr>
                    ))}
                    {tx.length === 0 && (
                      <tr><td colSpan={5} className="px-4 py-12 text-center text-sm text-[#86868B]">Bu hesapta hareket yok</td></tr>
                    )}
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
