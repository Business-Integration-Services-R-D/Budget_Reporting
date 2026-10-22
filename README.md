# MARTI Denizcilik Finans — Yerel geliştirme

Gereksinimler: Node.js 20+, Python 3.12 ve localhost:27017 üzerinde MongoDB.

Backend kurulumu:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-local.txt
```

`backend/.env` içinde `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `CORS_ORIGINS`,
`FRONTEND_URL` ve mutlak `UPLOAD_DIR` yolu tanımlanmalıdır. Yerel kurulum
`budget_reporting_editing` veritabanını kullanır. `SEED_TRANSACTIONS=false`
sayesinde boş işlem tabloları yeniden örnek kayıtlarla doldurulmaz.
Önceki veritabanı `budget_reporting_local` korunur.

Backend'i bir terminalde başlatın:

```bash
cd backend
.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Arayüzü başka bir terminalde başlatın:

```bash
cd frontend
npm ci --legacy-peer-deps
npm start
```

`frontend/.env.local` içeriği:

```dotenv
REACT_APP_BACKEND_URL=http://localhost:8000
HOST=127.0.0.1
PORT=3000
BROWSER=none
REACT_APP_HIDE_NUMBERS=true
```

Uygulama: http://localhost:3000 — API dokümantasyonu: http://localhost:8000/docs

Yerel başlangıç hesabı: `admin@martidenizcilikfinans.com` / `Marti2026!`.
AI asistanı ve OCR için ayrıca özel `emergentintegrations` paketi ve
`EMERGENT_LLM_KEY`; e-posta gönderimi için `RESEND_API_KEY` gerekir.
`requirements-local.txt` ana uygulamayı bu isteğe bağlı AI paketi olmadan çalıştırır.

Yerel gizli görünüm tutarları, kurları ve kayıt sayılarını maskeler, grafikleri
gizler ve sayısal form alanlarını düzenlemeye kapatır. Veritabanındaki değerler
korunur. Rakamları yeniden göstermek için `REACT_APP_HIDE_NUMBERS=false` yapıp
arayüz sunucusunu yeniden başlatın.

Eski borç ve ödeme kayıtlarını özgün tutarlarıyla, yeni eklenen kayıtları koruyarak
geri getirmek için backend klasöründe `.venv/bin/python restore_local_transactions.py --apply`
çalıştırın. `--apply` olmadan yalnızca önizleme yapılır. Kaynak yedek:
`.local-backups/20261022-150738`. Bu klasörü silmeyin.

Ödemelerde **İlgili Borç / Alacak** alanı ile yeni veya mevcut hareket bir kayda
bağlanabilir. Firma ve gemi seçimden doldurulur; kısmi/tam ödeme, düzenleme,
bağlantı değişikliği ve silme borcun kalan USD tutarını ve durumunu günceller.
Bağlantı seçilmezse hareket bağımsız kalır. Fazla ödeme ve borç/tahsil türü
uyuşmazlığı reddedilir. “Ödendi” ve “Kısmi Ödeme” elle atanamaz; durumlar
bağlı ödeme ve tahsilat hareketlerinden hesaplanır.

**Ödeme ve Tahsilat** ekranında **Borç → Ödeme** veya **Alacak → Tahsilat**
seçilir. Kayıt yanındaki düğme, türü otomatik belirlenen formu açar.
Geçmiş hareketler kapalı başlayan **İşlem geçmişi** bölümündedir; mevcut
hareketi düzenlemek ve bağımsız hareket eklemek de bu bölümden yapılır.

Dashboard **Net Pozisyon** kartı gerçekleşen tüm tahsilatların USD toplamından
tüm ödemelerin USD toplamını çıkarır. Bağımsız hareketler de hesaba dahildir;
açık borç ve alacaklar kendi kartlarında kalan tutarlarıyla gösterilir.

İzole yerel MongoDB testleri: backend klasöründe
`.venv/bin/python -m unittest tests.test_payment_settlement -v`.
