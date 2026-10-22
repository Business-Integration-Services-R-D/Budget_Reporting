import { privateValue } from "@/lib/privacy";
import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Page, Card } from "@/components/Primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Settings as SettingsIcon, User, Bell, RefreshCw, Loader2, Download } from "lucide-react";
import { toast } from "sonner";

export default function Settings() {
  const { user } = useAuth();
  const [name, setName] = useState(user?.name || "");
  const [newPwd, setNewPwd] = useState("");
  const [saving, setSaving] = useState(false);
  const [fxRefreshing, setFxRefreshing] = useState(false);
  const [fxStatus, setFxStatus] = useState(null);

  const [notif, setNotif] = useState({ email_reminders: true, daily_summary: false });

  useEffect(() => {
    (async () => {
      try { const { data } = await api.get("/fx/latest"); setFxStatus({ count: data.length, last: data[0]?.last_updated }); } catch {}
    })();
  }, []);

  const refreshFx = async () => {
    setFxRefreshing(true);
    try {
      const { data } = await api.post("/fx/refresh");
      if (data.ok) toast.success(`${data.updated} kur güncellendi (${data.date})`);
      else toast.error(data.error || "Güncellenemedi");
      const { data: latest } = await api.get("/fx/latest");
      setFxStatus({ count: latest.length, last: latest[0]?.last_updated });
    } catch (e) { toast.error(formatApiError(e)); }
    finally { setFxRefreshing(false); }
  };

  const [exporting, setExporting] = useState(false);
  const exportExcel = async () => {
    setExporting(true);
    try {
      const response = await api.get("/export/excel", { responseType: "blob" });
      const blob = response.data;
      const filename = `marti-finans-veri-${new Date().toISOString().slice(0,16).replace(/[:T]/g,"-")}.xlsx`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
      toast.success("Excel dosyası indirildi");
    } catch (e) {
      toast.error(formatApiError(e));
    } finally { setExporting(false); }
  };

  const saveProfile = async () => {
    setSaving(true);
    try {
      const body = { name };
      if (newPwd) body.new_password = newPwd;
      await api.put(`/users/${user.id}`, body);
      toast.success("Profil güncellendi");
      setNewPwd("");
    } catch (e) { toast.error(formatApiError(e)); }
    finally { setSaving(false); }
  };

  return (
    <Page title="Ayarlar" subtitle="Profil ve sistem ayarları">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-6">
          <div className="flex items-center gap-2 mb-5">
            <User className="w-5 h-5 text-[#1D1D1F]" strokeWidth={1.5}/>
            <h3 className="text-base font-semibold text-[#1D1D1F]">Profil</h3>
          </div>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-[11px] font-semibold uppercase tracking-wider text-[#86868B]">Email</Label>
              <Input value={user?.email || ""} disabled className="bg-[#F5F5F7] border-0 rounded-lg"/>
            </div>
            <div className="space-y-1.5">
              <Label className="text-[11px] font-semibold uppercase tracking-wider text-[#86868B]">Ad Soyad</Label>
              <Input data-testid="input-profile-name" value={name} onChange={(e) => setName(e.target.value)} className="bg-[#F5F5F7] border-0 rounded-lg"/>
            </div>
            <div className="space-y-1.5">
              <Label className="text-[11px] font-semibold uppercase tracking-wider text-[#86868B]">Yeni Şifre (opsiyonel)</Label>
              <Input data-testid="input-profile-password" type="password" value={newPwd} onChange={(e) => setNewPwd(e.target.value)} placeholder="•••••••" className="bg-[#F5F5F7] border-0 rounded-lg"/>
            </div>
            <Button data-testid="btn-save-profile" disabled={saving} onClick={saveProfile} className="bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-lg">Kaydet</Button>
          </div>
        </Card>

        <Card className="p-6">
          <div className="flex items-center gap-2 mb-5">
            <Bell className="w-5 h-5 text-[#1D1D1F]" strokeWidth={1.5}/>
            <h3 className="text-base font-semibold text-[#1D1D1F]">Bildirim Tercihleri</h3>
          </div>
          <div className="space-y-4">
            <Pref label="Vade hatırlatma emaileri" desc="7/3/1 gün önce ve vade günü"
              checked={notif.email_reminders} onChange={(v) => setNotif({...notif, email_reminders: v})}/>
            <Pref label="Günlük özet emaili" desc="Her sabah 09:00 — bugün ne ödenecek"
              checked={notif.daily_summary} onChange={(v) => setNotif({...notif, daily_summary: v})}/>
          </div>
        </Card>

        <Card className="p-6 lg:col-span-2">
          <div className="flex items-center gap-2 mb-5">
            <SettingsIcon className="w-5 h-5 text-[#1D1D1F]" strokeWidth={1.5}/>
            <h3 className="text-base font-semibold text-[#1D1D1F]">Sistem</h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="p-4">
              <div className="text-xs text-[#86868B] uppercase tracking-wider font-semibold mb-2">Veri</div>
              <div className="text-sm text-[#1D1D1F]">Tüm veriyi Excel olarak indir</div>
              <div className="mt-1 text-[10px] text-[#86868B]">Borçlar, ödemeler, cari hesaplar, master data — 14 sheet</div>
              <Button data-testid="btn-export-excel" onClick={exportExcel} disabled={exporting} className="mt-3 h-8 px-3 text-xs rounded-md gap-1.5 bg-[#111111] hover:bg-[#2C2C2E] text-white">
                {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin"/> : <Download className="w-3.5 h-3.5"/>}
                Excel'e Aktar
              </Button>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-[#86868B] uppercase tracking-wider font-semibold mb-2">Email</div>
              <div className="text-sm text-[#1D1D1F]">Resend ile bağlı</div>
              <div className="mt-3 text-xs text-[#86868B]">Otomatik hatırlatma email'leri aktif</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-[#86868B] uppercase tracking-wider font-semibold mb-2">Kur (TCMB)</div>
              <div className="text-sm text-[#1D1D1F]">{privateValue(fxStatus?.count || 0)} para birimi · Canlı</div>
              <div className="mt-1 text-[10px] text-[#86868B]">Her gün 15:30 otomatik güncellenir</div>
              <Button data-testid="btn-refresh-fx" onClick={refreshFx} disabled={fxRefreshing} className="mt-3 h-8 px-3 text-xs rounded-md gap-1.5 bg-[#111111] hover:bg-[#2C2C2E] text-white">
                {fxRefreshing ? <Loader2 className="w-3.5 h-3.5 animate-spin"/> : <RefreshCw className="w-3.5 h-3.5"/>}
                Şimdi Güncelle
              </Button>
            </Card>
          </div>
        </Card>
      </div>
    </Page>
  );
}

const Pref = ({ label, desc, checked, onChange }) => (
  <div className="flex items-center justify-between py-2.5 border-b border-[#F5F5F7] last:border-0">
    <div>
      <div className="text-sm font-medium text-[#1D1D1F]">{label}</div>
      <div className="text-xs text-[#86868B] mt-0.5">{desc}</div>
    </div>
    <Switch checked={checked} onCheckedChange={onChange}/>
  </div>
);
