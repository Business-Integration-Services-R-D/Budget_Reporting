import { PrivateChart as ResponsiveContainer } from "@/components/PrivateChart";
import { privateValue } from "@/lib/privacy";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtUSD, fmtDate } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Card, Page, StatusBadge, Skeleton } from "@/components/Primitives";
import {
  ArrowDownToLine, ArrowUpFromLine, TrendingUp, AlertCircle,
  CalendarClock, Calendar, Activity, Plus
} from "lucide-react";
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  Tooltip, XAxis, YAxis, CartesianGrid, Legend
} from "recharts";

const ChartColors = ["#111111", "#86868B", "#007AFF", "#1F8942", "#B26205", "#D92D20"];

export default function Dashboard() {
  const { user } = useAuth();
  const [kpi, setKpi] = useState(null);
  const [cashflow, setCashflow] = useState([]);
  const [byShip, setByShip] = useState([]);
  const [byCompany, setByCompany] = useState([]);
  const [byExpense, setByExpense] = useState([]);
  const [upcoming, setUpcoming] = useState([]);
  const [recent, setRecent] = useState([]);
  const [fx, setFx] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) return; // Auth context hidrate olmadan API çağırma
    (async () => {
      try {
        const [a, b, c, d, e, f, g, h] = await Promise.all([
          api.get("/dashboard/kpi"),
          api.get("/dashboard/cashflow?months=12"),
          api.get("/dashboard/by-ship"),
          api.get("/dashboard/by-company"),
          api.get("/dashboard/by-expense-type"),
          api.get("/dashboard/upcoming?days=30"),
          api.get("/dashboard/recent?limit=8"),
          api.get("/fx/latest"),
        ]);
        setKpi(a.data); setCashflow(b.data); setByShip(c.data);
        setByCompany(d.data); setByExpense(e.data); setUpcoming(f.data);
        setRecent(g.data); setFx(h.data.slice(0, 5));
      } finally { setLoading(false); }
    })();
  }, [user]);

  const kpis = [
    { label: "Açık Borç", value: kpi?.open_payable?.total, count: kpi?.open_payable?.count, icon: ArrowDownToLine, accent: "#D92D20" },
    { label: "Açık Alacak", value: kpi?.open_receivable?.total, count: kpi?.open_receivable?.count, icon: ArrowUpFromLine, accent: "#1F8942" },
    { label: "Net Nakit Hareketi", value: kpi?.net_position, count: null, icon: TrendingUp, accent: "#007AFF", isNet: true },
    { label: "Vadesi Geçmiş", value: kpi?.overdue?.total, count: kpi?.overdue?.count, icon: AlertCircle, accent: "#D92D20" },
    { label: "Önümüzdeki 7 Gün", value: kpi?.week_due?.total, count: kpi?.week_due?.count, icon: CalendarClock, accent: "#B26205", isNet: true, detail: `Tahsilat ${fmtUSD(kpi?.week_due?.receivable)} · Ödeme ${fmtUSD(kpi?.week_due?.payable)}` },
    { label: "Önümüzdeki 30 Gün", value: kpi?.month_due?.total, count: kpi?.month_due?.count, icon: Calendar, accent: "#86868B", isNet: true, detail: `Tahsilat ${fmtUSD(kpi?.month_due?.receivable)} · Ödeme ${fmtUSD(kpi?.month_due?.payable)}` },
  ];

  return (
    <Page
      title="Dashboard"
      subtitle="Tek bakışta finansal durum"
      actions={
        <div className="flex flex-wrap gap-2">
          <Link to="/payables" data-testid="qa-add-payable" className="h-9 px-3 sm:px-3.5 rounded-lg bg-[#111111] hover:bg-[#2C2C2E] text-white text-xs sm:text-sm font-medium inline-flex items-center gap-1.5 transition">
            <Plus className="w-4 h-4" /> Borç
          </Link>
          <Link to="/receivables" data-testid="qa-add-receivable" className="h-9 px-3 sm:px-3.5 rounded-lg bg-white hover:bg-[#F5F5F7] text-[#1D1D1F] border border-[#E5E5EA] text-xs sm:text-sm font-medium inline-flex items-center gap-1.5 transition">
            <Plus className="w-4 h-4" /> Alacak
          </Link>
          <Link to="/payments" data-testid="qa-add-payment" className="h-9 px-3 sm:px-3.5 rounded-lg bg-white hover:bg-[#F5F5F7] text-[#1D1D1F] border border-[#E5E5EA] text-xs sm:text-sm font-medium inline-flex items-center gap-1.5 transition">
            <Plus className="w-4 h-4" /> Ödeme
          </Link>
        </div>
      }
    >
      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 sm:gap-4 mb-6">
        {kpis.map((k, i) => (
          <Card key={i} className="p-4 sm:p-5" data-testid={`kpi-${k.label.toLowerCase().replace(/\s/g, "-")}`}>
            <div className="flex items-start justify-between mb-2 sm:mb-3">
              <span className="text-[10px] sm:text-[11px] uppercase tracking-wider font-semibold text-[#86868B]">{k.label}</span>
              <k.icon className="w-4 h-4 text-[#A1A1A6] shrink-0" strokeWidth={1.5} />
            </div>
            {loading ? (
              <Skeleton className="h-7 sm:h-8 w-20 sm:w-24" />
            ) : (
              <div className="tabular-nums">
                <div className={`text-lg sm:text-2xl font-semibold tracking-tight ${k.isNet && k.value < 0 ? "text-[#D92D20]" : k.isNet && k.value > 0 ? "text-[#1F8942]" : "text-[#1D1D1F]"}`}>
                  {fmtUSD(k.value, k.isNet)}
                </div>
                {k.detail ? <div className="mt-0.5 text-[9px] sm:text-[10px] text-[#86868B] leading-tight">{k.detail}</div>
                  : k.isNet && <div className="mt-0.5 text-[10px] sm:text-xs text-[#86868B]">Tahsilat − Ödeme</div>}
                {k.count !== null && (
                  <div className="mt-0.5 text-[10px] sm:text-xs text-[#86868B]">{privateValue(k.count || 0)} kayıt</div>
                )}
              </div>
            )}
          </Card>
        ))}
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <Card className="lg:col-span-2 p-4 sm:p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-base font-medium text-[#1D1D1F]">Nakit Akışı</h3>
              <p className="text-xs text-[#86868B] mt-0.5">Son 12 ay — Tediye vs Tahsilat (USD)</p>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={cashflow}>
              <defs>
                <linearGradient id="tediyeFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#111111" stopOpacity={0.15}/>
                  <stop offset="100%" stopColor="#111111" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="tahsilFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#1F8942" stopOpacity={0.15}/>
                  <stop offset="100%" stopColor="#1F8942" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E5EA" vertical={false}/>
              <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#86868B" }} axisLine={false} tickLine={false}/>
              <YAxis tick={{ fontSize: 11, fill: "#86868B" }} axisLine={false} tickLine={false}
                tickFormatter={(v) => `${(v/1000).toFixed(0)}k`}/>
              <Tooltip
                contentStyle={{ background: "white", border: "1px solid #E5E5EA", borderRadius: 12, fontSize: 12, boxShadow: "0 4px 24px rgba(0,0,0,0.08)" }}
                formatter={(v) => fmtUSD(v)}
              />
              <Area type="monotone" dataKey="TAHSİL" stroke="#1F8942" strokeWidth={2} fill="url(#tahsilFill)" />
              <Area type="monotone" dataKey="TEDİYE" stroke="#111111" strokeWidth={2} fill="url(#tediyeFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card className="p-4 sm:p-6">
          <h3 className="text-base font-medium text-[#1D1D1F] mb-1">Gemi Bazında Borç</h3>
          <p className="text-xs text-[#86868B] mb-4">Açık toplam (USD)</p>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={byShip.slice(0, 6)} dataKey="total" nameKey="name" cx="50%" cy="50%" innerRadius={50} outerRadius={90} paddingAngle={2}>
                {byShip.slice(0, 6).map((_, i) => <Cell key={i} fill={ChartColors[i % ChartColors.length]} />)}
              </Pie>
              <Tooltip
                contentStyle={{ background: "white", border: "1px solid #E5E5EA", borderRadius: 12, fontSize: 12, boxShadow: "0 4px 24px rgba(0,0,0,0.08)" }}
                formatter={(v) => fmtUSD(v)}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="mt-2 space-y-1">
            {byShip.slice(0, 4).map((s, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 truncate">
                  <span className="w-2 h-2 rounded-full" style={{ background: ChartColors[i % ChartColors.length] }}/>
                  <span className="truncate text-[#3A3A3C]">{s.name}</span>
                </div>
                <span className="font-medium text-[#1D1D1F] tabular-nums">{fmtUSD(s.total)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <Card className="p-4 sm:p-6">
          <h3 className="text-base font-medium text-[#1D1D1F] mb-1">Şirket Bazında Ödeme</h3>
          <p className="text-xs text-[#86868B] mb-4">Tüm zamanlar (USD)</p>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byCompany.slice(0, 7)} layout="vertical" margin={{ left: 60 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E5EA" horizontal={false}/>
              <XAxis type="number" tick={{ fontSize: 11, fill: "#86868B" }} axisLine={false} tickLine={false}
                tickFormatter={(v) => `${(v/1000).toFixed(0)}k`}/>
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "#3A3A3C" }} axisLine={false} tickLine={false} width={70}/>
              <Tooltip
                contentStyle={{ background: "white", border: "1px solid #E5E5EA", borderRadius: 12, fontSize: 12 }}
                formatter={(v) => fmtUSD(v)}
              />
              <Bar dataKey="total" fill="#111111" radius={[0, 6, 6, 0]} barSize={20}/>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card className="p-4 sm:p-6">
          <h3 className="text-base font-medium text-[#1D1D1F] mb-1">Masraf Türü Dağılımı</h3>
          <p className="text-xs text-[#86868B] mb-4">Toplam borç (USD)</p>
          <div className="space-y-2">
            {byExpense.slice(0, 7).map((e, i) => {
              const max = Math.max(...byExpense.map(x => x.total));
              const pct = max > 0 ? (e.total / max) * 100 : 0;
              return (
                <div key={i}>
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="truncate text-[#3A3A3C]">{e.name}</span>
                    <span className="font-medium text-[#1D1D1F] tabular-nums">{fmtUSD(e.total)}</span>
                  </div>
                  <div className="h-1.5 bg-[#F5F5F7] rounded-full overflow-hidden">
                    <div className="h-full bg-[#111111] rounded-full transition-all" style={{ width: `${pct}%` }}/>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        <Card className="p-4 sm:p-6">
          <h3 className="text-base font-medium text-[#1D1D1F] mb-1">TCMB Kurları</h3>
          <p className="text-xs text-[#86868B] mb-4">Güncel</p>
          <div className="space-y-2.5">
            {fx.map((f, i) => (
              <div key={i} className="flex items-center justify-between py-1.5 border-b border-[#F5F5F7] last:border-0">
                <span className="text-sm font-medium text-[#1D1D1F]">{f.code}</span>
                <span className="text-sm tabular-nums text-[#1D1D1F]">{privateValue((f.rate_to_tl || 0).toFixed(4))} ₺</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Bottom row: Upcoming + Recent */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="overflow-hidden">
          <div className="px-4 sm:px-6 py-4 border-b border-[#E5E5EA]/50 flex items-center justify-between">
            <div>
              <h3 className="text-base font-medium text-[#1D1D1F]">Vadesi Yaklaşan</h3>
              <p className="text-xs text-[#86868B] mt-0.5">Sonraki 30 gün · Borç ve alacak</p>
            </div>
            <CalendarClock className="w-5 h-5 text-[#A1A1A6]" strokeWidth={1.5}/>
          </div>
          <div className="divide-y divide-[#F5F5F7]">
            {upcoming.length === 0 && (
              <div className="px-4 sm:px-6 py-12 text-center text-sm text-[#86868B]">Yaklaşan borç veya alacak yok</div>
            )}
            {upcoming.slice(0, 8).map((p, i) => (
              <div key={i} className="px-4 sm:px-6 py-3 flex items-center justify-between hover:bg-[#FAFAFA] transition" data-testid={`upcoming-${i}`}>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-[#1D1D1F] truncate">{p.vendor || "—"}</div>
                  <div className="text-xs text-[#86868B] truncate">{p.description || p.ship || ""} · {fmtDate(p.due_date)}</div>
                </div>
                <div className="ml-3 text-right">
                  <div className={`text-sm font-semibold tabular-nums ${p.kind === "RECEIVABLE" ? "text-[#1F8942]" : "text-[#D92D20]"}`}>{p.kind === "RECEIVABLE" ? "+" : "−"}{fmtUSD(p.remaining_usd ?? p.usd_amount)}</div>
                  <div className="text-[10px] text-[#86868B] mb-1">{p.kind === "RECEIVABLE" ? "Tahsilat" : "Ödeme"}</div>
                  <StatusBadge value={p.status}/>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="overflow-hidden">
          <div className="px-4 sm:px-6 py-4 border-b border-[#E5E5EA]/50 flex items-center justify-between">
            <div>
              <h3 className="text-base font-medium text-[#1D1D1F]">Son Hareketler</h3>
              <p className="text-xs text-[#86868B] mt-0.5">Ödemeler & Tahsilatlar</p>
            </div>
            <Activity className="w-5 h-5 text-[#A1A1A6]" strokeWidth={1.5}/>
          </div>
          <div className="divide-y divide-[#F5F5F7]">
            {recent.length === 0 && (
              <div className="px-4 sm:px-6 py-12 text-center text-sm text-[#86868B]">Henüz hareket yok</div>
            )}
            {recent.map((p, i) => (
              <div key={i} className="px-4 sm:px-6 py-3 flex items-center justify-between hover:bg-[#FAFAFA] transition">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <StatusBadge value={p.type}/>
                    <span className="text-sm font-medium text-[#1D1D1F] truncate">{p.vendor || p.description || "—"}</span>
                  </div>
                  <div className="text-xs text-[#86868B] truncate mt-1">{p.payment_method || ""} · {fmtDate(p.date)}</div>
                </div>
                <div className="ml-3 text-sm font-semibold tabular-nums text-[#1D1D1F]">{fmtUSD(p.remaining_usd ?? p.usd_amount)}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </Page>
  );
}
