import { PrivateChart as ResponsiveContainer } from "@/components/PrivateChart";
import { privateValue } from "@/lib/privacy";
import { useEffect, useState } from "react";
import { api, fmtUSD } from "@/lib/api";
import { Page, Card, EmptyState } from "@/components/Primitives";
import { FileBarChart2, Ship, Users, Calendar, DollarSign, Layers, Building2, Clock } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell, PieChart, Pie, Legend } from "recharts";

const REPORTS = [
  { id: "by-ship-detail", label: "Gemi Bazlı Borç", icon: Ship, desc: "Toplam · Ödenen · Açık" },
  { id: "aging", label: "Yaşlandırma", icon: Clock, desc: "0-30 / 31-60 / 61-90 / 90+ gün" },
  { id: "monthly-projection", label: "Aylık Projeksiyon", icon: Calendar, desc: "Gelecek 12 ay borç" },
  { id: "top-vendors", label: "Top 20 Tedarikçi", icon: Building2, desc: "En çok ödeme yapılan" },
  { id: "by-currency", label: "Döviz Pozisyon", icon: DollarSign, desc: "Para birimi bazında" },
];

export default function Reports() {
  const [selected, setSelected] = useState(REPORTS[0]);
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const { data } = await api.get(`/reports/${selected.id}`);
        setData(data);
      } finally { setLoading(false); }
    })();
  }, [selected]);

  return (
    <Page title="Raporlar" subtitle="Hazır rapor şablonları">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <Card className="lg:col-span-4 overflow-hidden">
          <div className="px-5 py-4 border-b border-[#E5E5EA]/50">
            <h3 className="text-base font-medium text-[#1D1D1F]">Rapor Şablonları</h3>
            <p className="text-xs text-[#86868B] mt-0.5">{REPORTS.length} hazır rapor</p>
          </div>
          <div className="divide-y divide-[#F5F5F7]">
            {REPORTS.map((r) => (
              <button
                key={r.id}
                data-testid={`report-${r.id}`}
                onClick={() => setSelected(r)}
                className={`w-full px-5 py-3.5 flex items-start gap-3 hover:bg-[#FAFAFA] text-left transition ${selected.id === r.id ? "bg-[#FAFAFA]" : ""}`}
              >
                <div className={`w-9 h-9 rounded-lg grid place-items-center shrink-0 ${selected.id === r.id ? "bg-[#111111] text-white" : "bg-[#F5F5F7] text-[#3A3A3C]"}`}>
                  <r.icon className="w-4 h-4" strokeWidth={1.5}/>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-[#1D1D1F]">{r.label}</div>
                  <div className="text-xs text-[#86868B] truncate">{r.desc}</div>
                </div>
              </button>
            ))}
          </div>
        </Card>

        <Card className="lg:col-span-8 overflow-hidden">
          <div className="px-4 sm:px-6 py-4 border-b border-[#E5E5EA]/50 flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold text-[#1D1D1F]">{selected.label}</h3>
              <p className="text-xs text-[#86868B] mt-0.5">{selected.desc}</p>
            </div>
          </div>
          <div className="p-6">
            {loading ? (
              <div className="space-y-3">{[...Array(6)].map((_, i) => <div key={i} className="skeleton h-10 w-full"/>)}</div>
            ) : (
              <ReportRenderer report={selected.id} data={data}/>
            )}
          </div>
        </Card>
      </div>
    </Page>
  );
}

const ReportRenderer = ({ report, data }) => {
  if (!data || (Array.isArray(data) && data.length === 0)) {
    return <EmptyState icon={FileBarChart2} title="Veri yok" message="Bu rapor için henüz veri yok."/>;
  }

  if (report === "by-ship-detail") {
    return (
      <div>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data.filter(r => r._id).slice(0, 10)}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E5E5EA" vertical={false}/>
            <XAxis dataKey="_id" tick={{ fontSize: 11, fill: "#86868B" }} axisLine={false} tickLine={false}/>
            <YAxis tick={{ fontSize: 11, fill: "#86868B" }} axisLine={false} tickLine={false} tickFormatter={(v) => `${(v/1000).toFixed(0)}k`}/>
            <Tooltip contentStyle={{ background: "white", border: "1px solid #E5E5EA", borderRadius: 12, fontSize: 12 }} formatter={(v) => fmtUSD(v)}/>
            <Legend wrapperStyle={{ fontSize: 12 }}/>
            <Bar dataKey="paid" fill="#1F8942" name="Ödenen" radius={[4,4,0,0]}/>
            <Bar dataKey="open" fill="#D92D20" name="Açık" radius={[4,4,0,0]}/>
          </BarChart>
        </ResponsiveContainer>
        <table className="w-full mt-6 text-sm">
          <thead className="bg-[#FAFAFA]">
            <tr className="text-left">
              <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Gemi</th>
              <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">Toplam Borç</th>
              <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">Ödenen</th>
              <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">Açık</th>
              <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">#</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r, i) => (
              <tr key={i} className="border-b border-[#F5F5F7]">
                <td className="px-4 py-2 font-medium">{r._id || "—"}</td>
                <td className="px-4 py-2 text-right tabular-nums">{fmtUSD(r.total_debt)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-[#1F8942]">{fmtUSD(r.paid)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-[#D92D20]">{fmtUSD(r.open)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{privateValue(r.count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (report === "aging") {
    const colors = ["#1F8942", "#B26205", "#D92D20", "#6E0E0A"];
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={data} dataKey="total" nameKey="bucket" cx="50%" cy="50%" outerRadius={90} innerRadius={50}>
              {data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]}/>)}
            </Pie>
            <Tooltip contentStyle={{ background: "white", border: "1px solid #E5E5EA", borderRadius: 12, fontSize: 12 }} formatter={(v) => fmtUSD(v)}/>
          </PieChart>
        </ResponsiveContainer>
        <div className="space-y-3">
          {data.map((r, i) => (
            <div key={i} className="flex items-center justify-between p-3 rounded-lg bg-[#FAFAFA]">
              <div className="flex items-center gap-2.5">
                <span className="w-3 h-3 rounded-full" style={{ background: colors[i % colors.length] }}/>
                <span className="text-sm font-medium text-[#1D1D1F]">{r.bucket} gün</span>
              </div>
              <div className="text-right">
                <div className="text-sm font-semibold tabular-nums">{fmtUSD(r.total)}</div>
                <div className="text-[10px] text-[#86868B]">{privateValue(r.count)} kayıt</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (report === "monthly-projection") {
    return (
      <ResponsiveContainer width="100%" height={360}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E5E5EA" vertical={false}/>
          <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#86868B" }} axisLine={false} tickLine={false}/>
          <YAxis tick={{ fontSize: 11, fill: "#86868B" }} axisLine={false} tickLine={false} tickFormatter={(v) => `${(v/1000).toFixed(0)}k`}/>
          <Tooltip contentStyle={{ background: "white", border: "1px solid #E5E5EA", borderRadius: 12, fontSize: 12 }} formatter={(v) => fmtUSD(v)}/>
          <Bar dataKey="total" fill="#111111" radius={[6,6,0,0]}/>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (report === "top-vendors") {
    return (
      <table className="w-full text-sm">
        <thead className="bg-[#FAFAFA]">
          <tr className="text-left">
            <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">#</th>
            <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Tedarikçi</th>
            <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">Toplam Ödenen</th>
            <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">İşlem</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i} className="border-b border-[#F5F5F7]">
              <td className="px-4 py-2 text-[#86868B]">{i + 1}</td>
              <td className="px-4 py-2 font-medium">{r.vendor}</td>
              <td className="px-4 py-2 text-right tabular-nums font-medium">{fmtUSD(r.total)}</td>
              <td className="px-4 py-2 text-right tabular-nums text-[#86868B]">{privateValue(r.count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  if (report === "by-currency") {
    return (
      <table className="w-full text-sm">
        <thead className="bg-[#FAFAFA]">
          <tr className="text-left">
            <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold">Para Birimi</th>
            <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">Borç</th>
            <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">Alacak</th>
            <th className="px-4 py-2.5 text-[11px] uppercase tracking-wider text-[#86868B] font-semibold text-right">Net</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i} className="border-b border-[#F5F5F7]">
              <td className="px-4 py-2 font-medium">{r.currency}</td>
              <td className="px-4 py-2 text-right tabular-nums text-[#D92D20]">{privateValue(r.borç?.toLocaleString("tr-TR", {maximumFractionDigits: 2}))}</td>
              <td className="px-4 py-2 text-right tabular-nums text-[#1F8942]">{privateValue(r.alacak?.toLocaleString("tr-TR", {maximumFractionDigits: 2}))}</td>
              <td className="px-4 py-2 text-right tabular-nums font-medium">{privateValue((r.alacak - r.borç).toLocaleString("tr-TR", {maximumFractionDigits: 2}))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  return <EmptyState icon={FileBarChart2} title="Rapor yükleniyor"/>;
};
