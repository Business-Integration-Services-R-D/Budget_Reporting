import { privateValue, privateText } from "@/lib/privacy";
import { useEffect, useState } from "react";
import { api, fmtDate } from "@/lib/api";
import { Page, Card, EmptyState } from "@/components/Primitives";
import { Button } from "@/components/ui/button";
import { BellRing, Check, CheckCheck, RefreshCw } from "lucide-react";
import { toast } from "sonner";

export default function Reminders() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/notifications");
      setItems(data);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const runCheck = async () => {
    setRunning(true);
    try {
      const { data } = await api.post("/reminders/check-due");
      toast.success(`${data.created} yeni hatırlatma oluşturuldu`);
      load();
    } catch (e) {
      toast.error("Hatırlatma oluşturulamadı");
    } finally { setRunning(false); }
  };

  const markRead = async (id) => {
    await api.post(`/notifications/${id}/read`);
    load();
  };

  const markAllRead = async () => {
    await api.post("/notifications/mark-all-read");
    load();
  };

  return (
    <Page
      title="Hatırlatmalar & Bildirimler"
      subtitle={`${privateValue(items.filter(i => !i.read).length)} okunmamış · ${privateValue(items.length)} toplam`}
      actions={
        <div className="flex flex-wrap gap-2">
          <Button data-testid="btn-check-due" onClick={runCheck} disabled={running} variant="outline" className="rounded-lg gap-1.5 text-xs sm:text-sm">
            <RefreshCw className={`w-4 h-4 ${running ? "animate-spin" : ""}`}/> Vadeleri Kontrol Et
          </Button>
          <Button data-testid="btn-mark-all-read" onClick={markAllRead} variant="outline" className="rounded-lg gap-1.5 text-xs sm:text-sm">
            <CheckCheck className="w-4 h-4"/> Hepsini Okundu İşaretle
          </Button>
        </div>
      }
    >
      <Card className="overflow-hidden">
        {loading ? (
          <div className="p-6 space-y-3">{[...Array(6)].map((_, i) => <div key={i} className="skeleton h-14 w-full"/>)}</div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={BellRing}
            title="Bildirim yok"
            message="Vadesi yaklaşan borç olduğunda burada hatırlatma göreceksiniz."
            action={<Button onClick={runCheck} className="bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-lg gap-1.5"><RefreshCw className="w-4 h-4"/>Şimdi Kontrol Et</Button>}
          />
        ) : (
          <div className="divide-y divide-[#F5F5F7]">
            {items.map((n) => (
              <div
                key={n.id}
                data-testid={`notif-${n.id}`}
                className={`px-6 py-4 flex items-start gap-3 transition ${!n.read ? "bg-[#F5F9FF]" : ""}`}
              >
                <div className={`w-9 h-9 rounded-lg grid place-items-center shrink-0 ${n.read ? "bg-[#F5F5F7] text-[#86868B]" : "bg-[#E6F2FF] text-[#0062CC]"}`}>
                  <BellRing className="w-4 h-4" strokeWidth={1.5}/>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-[#1D1D1F]">{privateText(n.title)}</div>
                      <div className="text-xs text-[#86868B] mt-0.5">{privateText(n.message)}</div>
                    </div>
                    <div className="text-[10px] text-[#86868B] whitespace-nowrap">{fmtDate(n.created_at)}</div>
                  </div>
                </div>
                {!n.read && (
                  <button
                    data-testid={`mark-read-${n.id}`}
                    onClick={() => markRead(n.id)}
                    className="p-1.5 rounded-md hover:bg-white text-[#86868B] hover:text-[#1F8942] transition shrink-0"
                  ><Check className="w-4 h-4"/></button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </Page>
  );
}
