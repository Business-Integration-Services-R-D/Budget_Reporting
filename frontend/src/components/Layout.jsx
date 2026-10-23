import { HIDE_NUMBERS, privateValue } from "@/lib/privacy";
import { Link, NavLink, Outlet, useNavigate, useLocation } from "react-router-dom";
import {
  LayoutDashboard, ArrowDownToLine, ArrowUpFromLine, CreditCard, Wallet,
  Users, FileBarChart2, BellRing, Database, ShieldCheck, Settings,
  LogOut, Search, ChevronLeft, ChevronRight, Sparkles, Menu, X,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/payables", label: "Borçlar", icon: ArrowDownToLine },
  { to: "/receivables", label: "Alacaklar", icon: ArrowUpFromLine },
  { to: "/payments", label: "Ödeme ve Tahsilat", icon: CreditCard },
  { to: "/cash-bank", label: "Kasa & Banka", icon: Wallet },
  { to: "/current-accounts", label: "Cari Hesaplar", icon: Users },
  { to: "/reports", label: "Raporlar", icon: FileBarChart2 },
  { to: "/assistant", label: "AI Asistan", icon: Sparkles },
  { to: "/reminders", label: "Hatırlatmalar", icon: BellRing },
  { to: "/master-data", label: "Tanımlamalar", icon: Database },
];

const NAV_ADMIN = [
  { to: "/users", label: "Kullanıcılar", icon: ShieldCheck },
  { to: "/settings", label: "Ayarlar", icon: Settings },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [notifCount, setNotifCount] = useState(0);

  useEffect(() => {
    const fetchUnread = async () => {
      try {
        const { data } = await api.get("/notifications?unread_only=true");
        setNotifCount(data.length);
      } catch {}
    };
    fetchUnread();
    const t = setInterval(fetchUnread, 60000);
    return () => clearInterval(t);
  }, []);

  // Mobil drawer'ı route değişince kapat
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  // Body scroll lock — mobil drawer açıkken
  useEffect(() => {
    if (mobileOpen) document.body.style.overflow = "hidden";
    else document.body.style.overflow = "";
    return () => { document.body.style.overflow = ""; };
  }, [mobileOpen]);

  const initials = (user?.name || user?.email || "U").slice(0, 2).toUpperCase();

  const SidebarNav = ({ inDrawer = false }) => (
    <>
      <nav className="flex-1 px-2 py-4 space-y-0.5 overflow-y-auto">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            data-testid={`nav-${item.to.replace(/\//g, "") || "dashboard"}`}
            className={({ isActive }) =>
              `group flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all ${
                isActive
                  ? "bg-white text-[#1D1D1F] shadow-[0_1px_3px_rgba(0,0,0,0.05)] font-medium"
                  : "text-[#3A3A3C] hover:bg-white/60 font-normal"
              }`
            }
          >
            <item.icon className="w-[18px] h-[18px] shrink-0" strokeWidth={1.75} />
            {(inDrawer || !collapsed) && <span className="truncate">{item.label}</span>}
          </NavLink>
        ))}

        {user?.role === "admin" && (
          <>
            <div className={`mt-6 mb-2 px-3 text-[10px] uppercase tracking-wider text-[#86868B] font-semibold ${!inDrawer && collapsed ? "hidden" : ""}`}>
              Yönetim
            </div>
            {NAV_ADMIN.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                data-testid={`nav-${item.to.replace(/\//g, "")}`}
                className={({ isActive }) =>
                  `group flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all ${
                    isActive
                      ? "bg-white text-[#1D1D1F] shadow-[0_1px_3px_rgba(0,0,0,0.05)] font-medium"
                      : "text-[#3A3A3C] hover:bg-white/60"
                  }`
                }
              >
                <item.icon className="w-[18px] h-[18px] shrink-0" strokeWidth={1.75} />
                {(inDrawer || !collapsed) && <span className="truncate">{item.label}</span>}
              </NavLink>
            ))}
          </>
        )}
      </nav>

      <div className="p-3 border-t border-[#E5E5EA]/50">
        <button
          data-testid={inDrawer ? "btn-logout-mobile" : "btn-logout"}
          onClick={async () => { await logout(); navigate("/login"); }}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-[#3A3A3C] hover:bg-white/80 transition"
        >
          <LogOut className="w-[18px] h-[18px]" strokeWidth={1.75} />
          {(inDrawer || !collapsed) && <span>Çıkış</span>}
        </button>
      </div>
    </>
  );

  return (
    <div className="flex min-h-screen bg-[#FBFBFD]">
      {/* Desktop Sidebar — md ve üzeri */}
      <aside
        data-testid="sidebar"
        className={`${collapsed ? "w-16" : "w-64"} hidden md:flex shrink-0 bg-[#F5F5F7] border-r border-[#E5E5EA]/50 transition-all duration-300 flex-col`}
      >
        <div className={`h-14 flex items-center ${collapsed ? "justify-center" : "px-5 justify-between"} border-b border-[#E5E5EA]/50`}>
          {!collapsed && (
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-[#111111] grid place-items-center text-white text-xs font-semibold">M</div>
              <span className="text-sm font-semibold tracking-tight text-[#1D1D1F]">MARTI Finans</span>
            </div>
          )}
          <button
            data-testid="btn-toggle-sidebar"
            onClick={() => setCollapsed((c) => !c)}
            className="p-1.5 rounded-md hover:bg-white/80 text-[#86868B] hover:text-[#1D1D1F] transition"
          >
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>
        <SidebarNav />
      </aside>

      {/* Mobile Drawer */}
      {mobileOpen && (
        <div
          data-testid="mobile-drawer-overlay"
          onClick={() => setMobileOpen(false)}
          className="md:hidden fixed inset-0 z-40 bg-black/40 backdrop-blur-sm animate-fade-in-up"
        />
      )}
      <aside
        data-testid="mobile-sidebar"
        className={`md:hidden fixed inset-y-0 left-0 z-50 w-72 bg-[#F5F5F7] border-r border-[#E5E5EA] flex flex-col transition-transform duration-300 ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="h-14 flex items-center justify-between px-5 border-b border-[#E5E5EA]/50">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-[#111111] grid place-items-center text-white text-xs font-semibold">M</div>
            <span className="text-sm font-semibold tracking-tight text-[#1D1D1F]">MARTI Finans</span>
          </div>
          <button
            data-testid="btn-close-drawer"
            onClick={() => setMobileOpen(false)}
            className="p-1.5 rounded-md hover:bg-white/80 text-[#86868B] hover:text-[#1D1D1F] transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <SidebarNav inDrawer />
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Topbar */}
        <header className="sticky top-0 z-30 h-14 bg-[#FBFBFD]/80 backdrop-blur-xl border-b border-[#E5E5EA]/50 flex items-center px-3 sm:px-6 gap-2 sm:gap-4">
          {/* Mobile hamburger */}
          <button
            data-testid="btn-open-drawer"
            onClick={() => setMobileOpen(true)}
            className="md:hidden p-2 rounded-lg hover:bg-[#F5F5F7] text-[#1D1D1F] transition"
            aria-label="Menüyü aç"
          >
            <Menu className="w-5 h-5" strokeWidth={1.75} />
          </button>

          {/* Mobile logo (drawer kapalıyken görünür) */}
          <div className="md:hidden flex items-center gap-2 mr-auto">
            <div className="w-6 h-6 rounded-md bg-[#111111] grid place-items-center text-white text-[10px] font-semibold">M</div>
            <span className="text-sm font-semibold tracking-tight text-[#1D1D1F]">MARTI</span>
          </div>

          {/* Desktop search */}
          <div className="hidden md:block flex-1 max-w-md relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#86868B]" />
            <input
              data-testid="input-global-search"
              type="text"
              placeholder="Ara… (⌘K)"
              className="w-full h-9 pl-9 pr-3 bg-[#F5F5F7] border-0 rounded-lg text-sm placeholder:text-[#86868B] focus:bg-white focus:ring-2 focus:ring-[#007AFF]/20 transition"
            />
          </div>

          <button
            data-testid="btn-notifications"
            onClick={() => navigate("/reminders")}
            className="relative p-2 rounded-lg hover:bg-[#F5F5F7] transition shrink-0"
            aria-label="Bildirimler"
          >
            <BellRing className="w-5 h-5 text-[#3A3A3C]" strokeWidth={1.5} />
            {notifCount > 0 && (
              <span className="absolute top-1 right-1 min-w-[18px] h-[18px] px-1 grid place-items-center text-[10px] font-semibold bg-[#D92D20] text-white rounded-full">
                {privateValue(notifCount > 99 ? "99+" : notifCount)}
              </span>
            )}
          </button>

          <div className="flex items-center gap-2 sm:pl-3 sm:border-l border-[#E5E5EA]/50 shrink-0">
            <div className="w-8 h-8 rounded-full bg-[#111111] text-white grid place-items-center text-xs font-semibold">
              {initials}
            </div>
            <div className="hidden sm:block text-xs leading-tight">
              <div className="font-medium text-[#1D1D1F] max-w-[120px] truncate">{user?.name || "Kullanıcı"}</div>
              <div className="text-[#86868B]">{user?.role}</div>
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-auto p-4 sm:p-6 lg:p-8 animate-fade-in-up">
          {HIDE_NUMBERS && <p role="status" className="mb-4 text-xs text-[#86868B]">Gizli görünüm · Tutarlar ve miktarlar gizlendi. Veriler korunuyor.</p>}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
