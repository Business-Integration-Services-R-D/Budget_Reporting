import { privateText } from "@/lib/privacy";
import { useEffect, useRef, useState } from "react";
import { api, fmtDate, fmtUSD, formatApiError } from "@/lib/api";
import { Page, Card, EmptyState } from "@/components/Primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Sparkles, Send, Trash2, Plus, MessageSquare, Loader2, User as UserIcon, Bot, Check, X, Zap } from "lucide-react";
import { toast } from "sonner";

const SUGGESTIONS = [
  "Bu ay vadesi gelen toplam borç ne kadar?",
  "VICTORIA için VERGİ borcu ekle 50.000 USD vade 30 Mart 2026",
  "VICTORIA gemisinin hesap özetini PDF olarak emaile gönder",
  "YAPI KREDİ'den DENİZBANK'a 5000 USD virman yap",
  "Vadesi geçmiş borçların özetini emailime gönder",
  "Hangi gemi en yüksek açık borca sahip?",
];

const ACTION_LABELS = {
  create_payable: { label: "Yeni Borç Oluştur", icon: "+", color: "#D92D20" },
  create_payment: { label: "Ödeme/Tahsil Kaydet", icon: "💳", color: "#1F8942" },
  mark_payable_paid: { label: "Borcu Ödendi İşaretle", icon: "✓", color: "#1F8942" },
  send_summary_email: { label: "Özet Email Gönder", icon: "✉", color: "#0062CC" },
  update_payable: { label: "Borcu Güncelle", icon: "✎", color: "#B26205" },
  delete_payable: { label: "Borcu Sil", icon: "🗑", color: "#D92D20" },
  transfer_between_banks: { label: "Banka Virmanı", icon: "↔", color: "#0062CC" },
  generate_pdf_statement: { label: "PDF Hesap Özeti", icon: "📄", color: "#1F8942" },
};

export default function Assistant() {
  const [sessions, setSessions] = useState([]);
  const [currentSession, setCurrentSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => { loadSessions(); }, []);
  useEffect(() => { scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight); }, [messages]);

  const loadSessions = async () => {
    try { const { data } = await api.get("/ai/sessions"); setSessions(data); } catch {}
  };

  const openSession = async (sid) => {
    setCurrentSession(sid);
    setSessionsOpen(false);
    try {
      const { data } = await api.get(`/ai/sessions/${sid}/messages`);
      setMessages(data);
    } catch (e) { toast.error(formatApiError(e)); }
  };

  const newSession = () => { setCurrentSession(null); setMessages([]); setInput(""); setSessionsOpen(false); };

  const send = async (text = null) => {
    const msg = (text ?? input).trim();
    if (!msg || sending) return;
    setSending(true);
    setInput("");
    setMessages((m) => [...m, { role: "user", content: msg, _temp: true }]);
    try {
      const { data } = await api.post("/ai/chat", { session_id: currentSession, message: msg });
      setCurrentSession(data.session_id);
      const newAssistantMsg = {
        role: "assistant",
        content: data.response,
        message_type: data.type === "action" ? "action_proposal" : "text",
        action_id: data.action_id,
        action: data.action,
        params: data.params,
        created_at: new Date().toISOString(),
      };
      setMessages((m) => [
        ...m.filter(x => !x._temp),
        { role: "user", content: msg, created_at: new Date().toISOString() },
        newAssistantMsg,
      ]);
      loadSessions();
    } catch (e) {
      toast.error(formatApiError(e));
      setMessages((m) => m.filter(x => !x._temp));
    } finally { setSending(false); }
  };

  const executeAction = async (actionId, confirmed) => {
    try {
      const { data } = await api.post("/ai/execute-action", { action_id: actionId, confirmed });
      if (data.ok) {
        toast.success(confirmed ? "Aksiyon gerçekleştirildi" : "Aksiyon iptal edildi");
        // Mesaj listesine result ekle
        let resultContent = data.message || (confirmed ? "Aksiyon tamamlandı" : "Aksiyon iptal edildi");
        if (data.download_url) {
          // PDF / dosya download link'i — kullanıcı tıklayıp indirsin
          resultContent += `\n\n📥 [PDF'i indir](${data.download_url})`;
        }
        setMessages((m) => [...m, { role: "assistant", content: resultContent, message_type: "action_result", download_url: data.download_url, created_at: new Date().toISOString() }]);
        // Update status badge
        setMessages((m) => m.map(msg => msg.action_id === actionId ? {...msg, action_status: confirmed ? "completed" : "rejected"} : msg));
      } else {
        toast.error(data.error || "Aksiyon başarısız");
      }
    } catch (e) { toast.error(formatApiError(e)); }
  };

  const downloadFromUrl = (url) => {
    api.get(url, { responseType: "blob" })
      .then((response) => {
        const blob = response.data;
        const u = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = u;
        a.download = "hesap-ozeti.pdf";
        a.click();
        URL.revokeObjectURL(u);
      })
      .catch((e) => toast.error(formatApiError(e)));
  };

  const removeSession = async (sid) => {
    if (!window.confirm("Bu konuşma silinsin mi?")) return;
    await api.delete(`/ai/sessions/${sid}`);
    if (sid === currentSession) newSession();
    loadSessions();
  };

  const SessionsList = ({ inDrawer = false }) => (
    <>
      <div className="px-4 py-3 border-b border-[#E5E5EA]/50">
        <Button data-testid="btn-new-chat" onClick={newSession} className="w-full bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-lg gap-1.5 h-9">
          <Plus className="w-4 h-4"/> Yeni Konuşma
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto py-2">
        {sessions.length === 0 ? (
          <div className="px-4 py-6 text-center text-xs text-[#86868B]">Henüz konuşma yok</div>
        ) : (
          sessions.map((s) => (
            <div key={s.id} className={`group flex items-start gap-2 px-3 py-2 mx-2 rounded-lg cursor-pointer transition ${currentSession === s.id ? "bg-[#FAFAFA]" : "hover:bg-[#FAFAFA]"}`}>
              <button
                data-testid={`session-${s.id}`}
                onClick={() => openSession(s.id)}
                className="flex-1 min-w-0 text-left"
              >
                <div className="text-sm font-medium text-[#1D1D1F] truncate">{s.title || "Yeni Konuşma"}</div>
                <div className="text-[10px] text-[#86868B] truncate">{s.last_message}</div>
              </button>
              <button
                onClick={() => removeSession(s.id)}
                className="opacity-100 sm:opacity-0 sm:group-hover:opacity-100 p-1 rounded text-[#86868B] hover:text-[#D92D20] hover:bg-white"
              ><Trash2 className="w-3.5 h-3.5"/></button>
            </div>
          ))
        )}
      </div>
    </>
  );

  return (
    <Page title="AI Asistan" subtitle="Tüm finansal verinize hakim — Türkçe doğal dilde sorgu yapın">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 h-[calc(100vh-180px)] sm:h-[calc(100vh-200px)]">
        {/* Desktop Sessions sidebar */}
        <Card className="hidden lg:flex lg:col-span-3 flex-col overflow-hidden">
          <SessionsList/>
        </Card>

        {/* Mobile Sessions sheet */}
        <Sheet open={sessionsOpen} onOpenChange={setSessionsOpen}>
          <SheetContent side="left" className="w-full sm:max-w-sm p-0 flex flex-col">
            <SheetHeader className="px-4 pt-4">
              <SheetTitle>Konuşmalar</SheetTitle>
            </SheetHeader>
            <div className="mt-4 flex flex-col flex-1 min-h-0">
              <SessionsList inDrawer/>
            </div>
          </SheetContent>
        </Sheet>

        {/* Chat area */}
        <Card className="col-span-1 lg:col-span-9 flex flex-col overflow-hidden">
          {/* Header */}
          <div className="px-4 sm:px-6 py-4 border-b border-[#E5E5EA]/50 flex items-center gap-3">
            <button
              data-testid="btn-open-sessions"
              onClick={() => setSessionsOpen(true)}
              className="lg:hidden p-2 -ml-2 rounded-lg hover:bg-[#F5F5F7] text-[#1D1D1F] transition"
              aria-label="Konuşmalar"
            >
              <MessageSquare className="w-5 h-5" strokeWidth={1.5}/>
            </button>
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#111111] to-[#2C2C2E] grid place-items-center shrink-0">
              <Sparkles className="w-4 h-4 text-white" strokeWidth={1.5}/>
            </div>
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-[#1D1D1F]">Finans Asistanı</h3>
              <p className="text-xs text-[#86868B] truncate">Akıllı asistan · Gerçek verinizden cevap verir</p>
            </div>
          </div>

          {/* Messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 sm:px-6 py-4 sm:py-6 space-y-4 sm:space-y-5">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center max-w-xl mx-auto">
                <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl bg-gradient-to-br from-[#111111] to-[#2C2C2E] grid place-items-center mb-4">
                  <Sparkles className="w-5 h-5 sm:w-6 sm:h-6 text-white" strokeWidth={1.5}/>
                </div>
                <h2 className="text-xl sm:text-2xl font-semibold tracking-tight text-[#1D1D1F]">Nasıl yardımcı olabilirim?</h2>
                <p className="mt-2 text-xs sm:text-sm text-[#86868B]">Borçlar, ödemeler, geminizin finansal durumu hakkında sorabilirsiniz.</p>
                <div className="mt-6 sm:mt-8 grid grid-cols-1 md:grid-cols-2 gap-2 w-full">
                  {SUGGESTIONS.map((q, i) => (
                    <button
                      key={i}
                      data-testid={`suggestion-${i}`}
                      onClick={() => send(q)}
                      className="text-left text-xs sm:text-sm px-3 sm:px-4 py-2.5 sm:py-3 rounded-xl border border-[#E5E5EA] hover:border-[#1D1D1F]/30 hover:bg-[#FAFAFA] transition text-[#3A3A3C]"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m, i) => (
                <Message key={i} msg={m} onExecute={executeAction} onDownload={downloadFromUrl}/>
              ))
            )}
            {sending && (
              <div className="flex items-start gap-3 animate-fade-in-up">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#111111] to-[#2C2C2E] grid place-items-center shrink-0">
                  <Sparkles className="w-4 h-4 text-white" strokeWidth={1.5}/>
                </div>
                <div className="flex items-center gap-2 text-sm text-[#86868B] py-2">
                  <Loader2 className="w-4 h-4 animate-spin"/> Yazıyor…
                </div>
              </div>
            )}
          </div>

          {/* Input */}
          <div className="px-3 sm:px-6 py-3 sm:py-4 border-t border-[#E5E5EA]/50 bg-white">
            <div className="flex gap-2 items-end">
              <textarea
                data-testid="input-chat"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                rows={1}
                placeholder="Sorunuzu yazın…"
                className="flex-1 px-3 sm:px-4 py-2.5 bg-[#F5F5F7] border-0 rounded-xl text-sm placeholder:text-[#86868B] focus:bg-white focus:ring-2 focus:ring-[#007AFF]/20 resize-none"
                style={{ minHeight: 44, maxHeight: 160 }}
              />
              <Button
                data-testid="btn-send"
                onClick={() => send()}
                disabled={!input.trim() || sending}
                className="bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-xl h-11 px-4 shrink-0"
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin"/> : <Send className="w-4 h-4"/>}
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </Page>
  );
}

const Message = ({ msg, onExecute, onDownload }) => {
  const isUser = msg.role === "user";
  const isAction = msg.message_type === "action_proposal";

  if (isAction) {
    return <ActionCard msg={msg} onExecute={onExecute}/>;
  }

  return (
    <div className={`flex items-start gap-3 animate-fade-in-up ${isUser ? "flex-row-reverse" : ""}`}>
      <div className={`w-8 h-8 rounded-lg grid place-items-center shrink-0 ${isUser ? "bg-[#F5F5F7]" : "bg-gradient-to-br from-[#111111] to-[#2C2C2E]"}`}>
        {isUser ? <UserIcon className="w-4 h-4 text-[#1D1D1F]" strokeWidth={1.5}/> : <Sparkles className="w-4 h-4 text-white" strokeWidth={1.5}/>}
      </div>
      <div className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${isUser ? "bg-[#111111] text-white rounded-tr-md" : "bg-[#F5F5F7] text-[#1D1D1F] rounded-tl-md"}`}>
        <pre className="font-sans whitespace-pre-wrap break-words">{privateText(msg.content)}</pre>
        {msg.download_url && (
          <button
            data-testid="btn-download-pdf"
            onClick={() => onDownload?.(msg.download_url)}
            className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-[#E5E5EA] text-xs font-medium text-[#1D1D1F] hover:bg-[#FAFAFA] transition"
          >
            📥 PDF'i İndir
          </button>
        )}
      </div>
    </div>
  );
};

const ActionCard = ({ msg, onExecute }) => {
  const meta = ACTION_LABELS[msg.action] || { label: msg.action, icon: "⚡", color: "#0062CC" };
  const params = msg.params || {};
  const status = msg.action_status;

  return (
    <div className="flex items-start gap-3 animate-fade-in-up" data-testid={`action-card-${msg.action_id}`}>
      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#111111] to-[#2C2C2E] grid place-items-center shrink-0">
        <Zap className="w-4 h-4 text-white" strokeWidth={1.5}/>
      </div>
      <div className="max-w-[80%] flex-1">
        <div className="bg-white border border-[#E5E5EA] rounded-2xl rounded-tl-md shadow-card overflow-hidden">
          <div className="px-4 py-3 border-b border-[#F5F5F7] flex items-center gap-2">
            <div className="w-7 h-7 rounded-md grid place-items-center text-xs font-semibold" style={{ background: `${meta.color}15`, color: meta.color }}>
              {meta.icon}
            </div>
            <div className="flex-1">
              <div className="text-xs uppercase tracking-wider font-semibold text-[#86868B]">Aksiyon Önerisi</div>
              <div className="text-sm font-semibold text-[#1D1D1F]">{meta.label}</div>
            </div>
          </div>
          <div className="px-4 py-3 text-sm text-[#1D1D1F]">
            <div className="mb-3">{privateText(msg.content)}</div>
            {Object.keys(params).length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1.5 text-xs bg-[#FAFAFA] rounded-lg p-3">
                {Object.entries(params).filter(([k, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2">
                    <span className="text-[#86868B] capitalize">{k.replace(/_/g, " ")}:</span>
                    <span className="font-medium text-[#1D1D1F] text-right truncate">{privateText(String(v))}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          {!status && (
            <div className="px-4 py-3 bg-[#FAFAFA] border-t border-[#F5F5F7] flex gap-2">
              <Button
                data-testid={`btn-confirm-${msg.action_id}`}
                onClick={() => onExecute(msg.action_id, true)}
                className="flex-1 bg-[#111111] hover:bg-[#2C2C2E] text-white rounded-lg gap-1.5 h-9"
              >
                <Check className="w-4 h-4"/> Onayla ve Uygula
              </Button>
              <Button
                data-testid={`btn-reject-${msg.action_id}`}
                onClick={() => onExecute(msg.action_id, false)}
                variant="outline"
                className="rounded-lg gap-1.5 h-9"
              >
                <X className="w-4 h-4"/> İptal
              </Button>
            </div>
          )}
          {status === "completed" && (
            <div className="px-4 py-2.5 bg-[#E3F8E9] border-t border-[#B9EAC8] text-xs text-[#1F8942] font-medium">
              ✓ Aksiyon gerçekleştirildi
            </div>
          )}
          {status === "rejected" && (
            <div className="px-4 py-2.5 bg-[#F2F2F7] border-t border-[#E5E5EA] text-xs text-[#86868B]">
              İptal edildi
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
