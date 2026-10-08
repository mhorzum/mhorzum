# Borsa Terminali

Ev bilgisayarında çalışan, kişisel kullanım için TradingView benzeri bir grafik, tarama ve alarm sistemi.

- **Piyasalar:** BIST hisseleri (tamamı) + S&P 500 + Nasdaq-100
- **Saklanan veri:** 4 saatlik ve günlük barlar, son **5 yıl**. Haftalık, aylık ve 3 aylık barlar günlük veriden otomatik üretilir.
- **Günlük güncelleme:** Her borsa kapandıktan sonra yeni barlar veritabanına eklenir.
- **Anlık fiyat:** Seans içinde **15 dk gecikmeli** fiyatlar grafik, izleme listesi ve fiyat alarmları için kullanılır. Bu fiyatlar geçmiş olarak saklanmaz.
- **Grafik:** Mum + hacim, 13 indikatör, yatay çizgi ve trend çizgisi, alarm seviyeleri ([lightweight-charts](https://github.com/tradingview/lightweight-charts))
- **İzleme listeleri:** Birden çok liste, sürükle-bırak ile sıralama, anlık fiyat ve değişim
- **Tarayıcı:** `rsi14 < 30 ve close > sma200` gibi ifadelerle tüm piyasayı tarama
- **Periyodik taramalar:** Kayıtlı taramalar gün sonunda veya cron zamanlamasıyla çalışır, yeni eşleşmeler bildirilir
- **Alarmlar:** Fiyat seviyesi alarmları (anlık) ve ifade alarmları (bar kapanışında); uygulama içinde, tarayıcıda ve Telegram'da bildirim
- **Kendi veritabanın:** PostgreSQL. Tüm tablolara doğrudan bağlanıp sorgu yazabilir, ayar yapabilirsin.

```
TradingView (15 dk gecikmeli, resmi olmayan API)
        │  borsapy + tradingview-screener
        ▼
┌─────────────── app (Python / FastAPI) ───────────────┐
│ ingest     : 5 yıllık geçmiş, günlük yeni bar, bölünme tespiti │
│ snapshot   : her sembol/periyot için indikatör özeti           │
│ screener   : güvenli ifade dili                               │
│ alerts     : fiyat + ifade alarmları                          │
│ scheduler  : gün sonu, gün ortası 4s, anlık fiyat, taramalar  │
│ web arayüz : lightweight-charts                               │
└───────────────────────────┬──────────────────────────┘
                            ▼
                PostgreSQL (bars_4h, bars_1d,
                bars_1w/1mo/3mo view'ları, ...)
```

## Kurulum (Windows / macOS / Linux)

1. [Docker Desktop](https://www.docker.com/products/docker-desktop/) ve [Git](https://git-scm.com/download/win) kur.
2. Kodu bir klasöre indir (ör. masaüstündeki `periview`). Klasörde terminal açıp:
   ```bash
   git clone -b claude/serene-keller-81bhk1 https://github.com/mhorzum/mhorzum.git .
   ```
   (Klasör boş olmalı.)
3. İsteğe bağlı: `.env.example` dosyasını `.env` adıyla kopyalayıp düzenle (Telegram, şifre vb.).
4. Başlat: Windows'ta **`guncelle.bat`** dosyasına çift tıkla (veya `docker compose up -d --build`).
5. Tarayıcıda **http://localhost:8000** adresini aç.

**Güncelleme:** `guncelle.bat` dosyasına çift tıkla. Son sürümü GitHub'dan çeker ve uygulamayı yeniden başlatır. Veritabanı ve `.env` korunur.

İlk açılışta sistem kendiliğinden:
1. Sembol listesini indirir (yaklaşık 600 BIST + 600 ABD hissesi),
2. Her sembol için 5 yıllık 4 saatlik ve günlük geçmişi indirir.

İlerleme sağ üstte `⟳ Geçmiş veri 120/1150` şeklinde görünür. Bu ilk yükleme internet hızına ve TradingView'ın yanıt süresine göre muhtemelen 30–90 dakika sürer. Bu sürede uygulamayı kullanabilirsin; yüklenen semboller hemen görünür.

Bilgisayar açıldığında sistem Docker Desktop ile birlikte otomatik başlar (`restart: unless-stopped`). Durdurmak için `docker compose down` kullan. Veriler `pgdata` volume'unda kalır.

### İnternetsiz deneme (demo verisi)

```bash
DATA_PROVIDER=demo docker compose up -d --build
```

Bu mod 40 sembol için sentetik veri üretir. Gerçek veriye geçmek için veritabanını sıfırla (`docker compose down -v`) ve `DATA_PROVIDER=tradingview` ile yeniden başlat.

## Zamanlanmış işler

| İş | Zaman | Ne yapar |
|---|---|---|
| Anlık fiyat | Seans içinde her 60 sn | 15 dk gecikmeli fiyatları çeker, fiyat alarmlarını kontrol eder |
| BIST gün ortası | Hafta içi 14:20 (İstanbul) | Kapanan ilk 4 saatlik barı ekler, 4s ifade alarmlarını kontrol eder |
| BIST gün sonu | Hafta içi 18:40 (İstanbul) | 4s + günlük barları ekler, indikatörleri günceller, alarmları ve gün sonu taramalarını çalıştırır |
| ABD gün ortası | Hafta içi 13:50 (New York) | Aynısı (ABD) |
| ABD gün sonu | Hafta içi 16:40 (New York) ≈ 23:40/00:40 TSİ | Aynısı (ABD) |
| Sembol listesi | Pazar 10:07 | Endeks değişikliklerini işler (çıkan semboller silinmez, pasife alınır) |
| Kayıtlı taramalar | Taramanın zamanlaması | `after_close` veya cron |

Günlük güncellemede son yaklaşık 12 gün yeniden çekilir. Böylece kaçırılan günler kendiliğinden tamamlanır. Bilgisayar gün sonu saatinde kapalıysa, uygulama açıldığında eksik güncellemeyi hemen yapar. Daha önce kaydedilmiş barların fiyatı değişmişse (bölünme/bedelsiz) sembolün tüm geçmişi yeniden indirilir.

İşleri elle de tetikleyebilirsin: sağ üstteki **⚙ Veri** menüsü veya komut satırı (aşağıda).

## Tarayıcı ifade dili

```text
rsi14 < 30 ve close > sma200
cross_up(sma50, sma200)                     # altın kesişim
close > prev(hh20) and rel_volume > 1.5     # 20 bar zirve kırılımı + hacim
st_dir == 1 and prev(st_dir) == -1          # SuperTrend al
close >= high_52w * 0.97                    # 52 hafta zirvesine %3 yakın
price > sma50                               # anlık (gecikmeli) fiyat ile
```

- **Bağlaçlar:** `and`/`ve`, `or`/`veya`, `not`, `< <= > >= == !=` (tek `=` da olur), `+ - * / %`
- **Fonksiyonlar:** `cross_up(a,b)`, `cross_down(a,b)`, `prev(x)` (önceki bar), `abs`, `min`, `max`
- **Alanlar:** `open high low close volume price change_pct perf_5 perf_20 sma20 sma50 sma100 sma200 ema9 ema20 ema50 ema200 rsi14 macd macd_signal macd_hist bb_upper bb_middle bb_lower bb_width atr14 atr_pct stoch_k stoch_d adx14 plus_di minus_di cci20 mfi14 obv vol_sma20 rel_volume supertrend st_dir hh20 ll20 hh55 ll55 high_52w low_52w bars`. Uygulamada **Alanlar** düğmesi açıklamaları gösterir.
- Her ifade seçilen periyotta (4S, G, H, A, 3A) ve son kapanmış bar üzerinde çalışır. BIST/ABD, XU030/XU100/SPX/NDX veya bir izleme listesiyle daraltılabilir.

İfadeler yalnızca izin verilen işlemlerle çalıştırılır; başka kod çalıştırılamaz.

## Alarmlar

- **Fiyat alarmı:** "THYAO 300'ü yukarı keserse". Seans içinde her anlık fiyat güncellemesinde kontrol edilir. Fiyat 15 dk gecikmeli olduğu için alarm da gecikmelidir.
- **İfade alarmı:** Bir sembol veya bütün bir izleme listesi için, ör. `cross_up(close, sma50)`. Bar kapanışında (günlük için gün sonunda, 4s için gün ortası ve gün sonunda) kontrol edilir. Aynı bar için iki kez tetiklenmez.
- **Bildirim kanalları:** Uygulamadaki *Bildirimler* sekmesi, tarayıcı bildirimi ("Tarayıcı bildirimlerini aç") ve Telegram (`.env` içinde `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`).

## Veritabanı

PostgreSQL'e `localhost:5432` üzerinden bağlanabilirsin (kullanıcı `borsa`, şifre `.env` içindeki `POSTGRES_PASSWORD`, varsayılan `borsa`). DBeaver ve pgAdmin gibi araçlar ile `docker compose exec db psql -U borsa` kullanılabilir.

| Tablo / view | İçerik |
|---|---|
| `symbols` | Semboller, borsa, sektör, endeks üyelikleri (`indexes`), `active` |
| `bars_4h` | 4 saatlik barlar (`ts` = barın UTC açılış zamanı) |
| `bars_1d` | Günlük barlar (`day` = borsanın yerel işlem günü) |
| `bars_1w`, `bars_1mo`, `bars_3mo` | Günlükten türetilen view'lar |
| `indicator_snapshots` | Her sembol/periyot için son ve önceki barın indikatör değerleri (JSON) |
| `live_quotes` | Son anlık (gecikmeli) fiyatlar |
| `watchlists`, `watchlist_items` | İzleme listeleri |
| `alerts`, `alert_events` | Alarmlar ve tetiklenme geçmişi |
| `scans`, `scan_results` | Kayıtlı taramalar ve her çalıştırmanın sonuçları |
| `drawings` | Grafik çizimleri |
| `job_runs` | Zamanlanmış işlerin geçmişi ve hataları |

Örnek sorgu: son 1 yılda en çok yükselen 10 BIST hissesi.
```sql
SELECT s.ticker, round((son.close / ilk.close - 1) * 100) AS getiri
FROM symbols s
JOIN LATERAL (SELECT close FROM bars_1d WHERE symbol_id = s.id ORDER BY day DESC LIMIT 1) son ON true
JOIN LATERAL (SELECT close FROM bars_1d WHERE symbol_id = s.id AND day >= current_date - 365 ORDER BY day LIMIT 1) ilk ON true
WHERE s.market = 'BIST' AND s.active
ORDER BY getiri DESC LIMIT 10;
```

Şema değişikliklerini `backend/app/migrations/` altına `002_...sql` gibi yeni dosyalar olarak ekle; uygulama açılışta bunları sırayla uygular.

**Yedekleme:** `docker compose exec db pg_dump -U borsa borsa > yedek.sql`

## Komut satırı

```bash
docker compose exec app python -m app.cli sync-universe          # sembol listesini güncelle
docker compose exec app python -m app.cli backfill               # eksik geçmişleri indir
docker compose exec app python -m app.cli backfill --market BIST --all   # BIST'i baştan indir
docker compose exec app python -m app.cli update --market US     # ABD son barlar
docker compose exec app python -m app.cli live                   # anlık fiyatları bir kez çek
docker compose exec app python -m app.cli scan "rsi14 < 30" --tf 1w --market BIST
```

## Ayarlar (`.env`)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `DATA_PROVIDER` | `tradingview` | `demo` = internetsiz sentetik veri |
| `HISTORY_YEARS` | `5` | Saklanacak geçmiş |
| `FETCH_WORKERS` | `3` | Paralel indirme sayısı |
| `LIVE_POLL_SECONDS` | `60` | Seans içi anlık fiyat yenileme aralığı |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | – | Telegram bildirimleri |
| `TV_SESSION`, `TV_SESSION_SIGN` | – | Kendi TradingView aboneliğin varsa gecikmesiz veri |
| `POSTGRES_PASSWORD`, `APP_PORT`, `DB_PORT` | `borsa`, `8000`, `5432` | |

## Geliştirme

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
# Testler bir PostgreSQL ister (varsayılan postgresql://postgres@127.0.0.1:5433/borsa_test)
cd backend && TEST_DATABASE_URL=postgresql://... ../.venv/bin/python -m pytest
# Uygulamayı yerelde çalıştırma
cd backend && DATABASE_URL=postgresql://... DATA_PROVIDER=demo ../.venv/bin/uvicorn app.main:app --reload
```

## Sınırlamalar ve notlar

- Veriler TradingView'ın **resmi olmayan** arayüzlerinden ([borsapy](https://github.com/saidsurucu/borsapy), [TradingView-Screener](https://github.com/shner-elmo/TradingView-Screener)) alınır. Yalnızca **kişisel kullanım** içindir. Verileri yeniden dağıtmak veya ticari amaçla kullanmak TradingView'ın kullanım koşullarına ve BIST veri lisansına aykırıdır. TradingView bu arayüzleri değiştirirse veri çekme bozulabilir. Bu durumda `job_runs` tablosunda ve sağ üstteki ⚠ işaretinde hata görünür.
- Giriş yapılmadan veriler 15 dk gecikmelidir.
- Fiyatlar bölünmelere göre düzeltilmiştir, temettüye göre düzeltilmemiştir (TradingView varsayılanı).
- Resmi tatiller takvimde tanımlı değildir. Tatil günlerinde işler çalışır ama yeni bar gelmediği için bir şey değişmez.
- Grafik kütüphanesi lightweight-charts Apache-2.0 lisanslıdır; grafikteki TradingView logosu lisansın istediği atıftır.
