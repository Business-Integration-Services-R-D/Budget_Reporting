# Yerel iş kuralı testleri

Backend sanal ortamı ve localhost:27017 üzerinde MongoDB gerekir.
Proje kökünden çalıştırın:

```sh
cd backend
.venv/bin/python -m unittest tests.test_payment_settlement tests.test_business_rules -v
```

Bu 31 test her test için ayrı `budget_business_test_<uuid>` veya
`budget_settlement_test_<uuid>` veritabanı açar ve sonunda temizler.
Uygulamanın veritabanına dokunmaz; dış servise veya LLM çağrısına ihtiyaç duymaz.

Kontroller: kısmi/tam ödeme, ters kayıt, fazla ödeme, eşzamanlı istek,
borç/alacak bağlantısı, özgün dövizde mahsup ve ayrı kur farkı,
onay ve taslak ayrımı, banka zorunluluğu/açılış bakiyesi,
gelecek vadeler, firma/banka ad değişiklikleri, rol yetkileri,
AI ile ekran kurallarının tutarlılığı ve eşli virman iptali.

Geçmiş kayıtlarda `posting_status` yoksa önceki nakit davranışı korunur.
Yeni `approved=false` hareketler taslak olur. İptal edilen hareketler silinmez.
Eski farklı dövizli banka hareketlerinde kayıtlı hesap tutarı yoksa bakiye
kurla tahmin edilir ve ekranda belirtilir. Geçmiş veriler topluca dönüştürülmez.

Diğer eski pytest dosyaları dış sunucu/LLM ve gerçek API üzerinde yazma
çağrıları içerebilir; bu yerel doğrulama komutuna dahil değildir.
