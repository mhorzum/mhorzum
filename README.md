# Otomatik Tıklayıcı (Auto Clicker)

Windows için, ekranda **senin belirlediğin alanın içine** belirli sayıda ve
**rastgele aralıklarla** tıklama yapan masaüstü uygulaması. Chrome (veya başka
herhangi bir pencere) açıkken, seçtiğin bölgeye tıklamaları gönderir.

## Özellikler

- **Alan seçimi:** Fareyle sürükleyerek ekranda bir dikdörtgen seç (çoklu monitör desteklenir).
- **Toplam tıklama sayısı:** İstediğin sayıyı gir; `0` yazarsan sınırsız çalışır.
- **Rastgele süre aralığı:** Örneğin en kısa `10`, en uzun `90` saniye — her tıklamadan
  sonra bu aralıktan rastgele bir bekleme süresi seçilir.
- **Başlangıç gecikmesi:** Başlat'a bastıktan sonra Chrome'a geçmen için süre tanır.
- **Alan içinde rastgele nokta:** Her tıklama alanın farklı bir noktasına gider
  (kapatırsan hep alanın tam ortasına tıklar).
- **Fare tuşu seçimi:** Sol / sağ / orta tuş, isteğe bağlı çift tıklama.
- **İmleci geri döndürme:** Tıklamadan sonra fare eski konumuna geri gider.
- **Global kısayollar:** `F8` başlat/durdur, `ESC` acil durdurma — uygulama arka planda olsa bile çalışır.
- **Canlı durum:** Kalan süre geri sayımı, ilerleme çubuğu ve zaman damgalı kayıt listesi.
- Ayarlar otomatik kaydedilir (`%APPDATA%\AutoClicker\settings.json`), program tekrar açıldığında hazır gelir.

Tıklamalar Windows'un kendi `SendInput` API'si ile gönderilir; ek bir kütüphane gerekmez.

## Kurulum ve çalıştırma

### Seçenek 1 — Hazır .exe oluştur (önerilen)

1. [Python 3.10+](https://www.python.org/downloads/) kur (kurulumda
   **"Add python.exe to PATH"** kutusunu işaretle).
2. Bu klasördeki **`build.bat`** dosyasına çift tıkla.
3. İşlem bitince program hazır: **`dist\OtomatikTiklayici.exe`**

Bu `.exe` tek dosyadır; masaüstüne kopyalayıp çift tıklayarak çalıştırabilirsin,
Python kurulu olmayan bilgisayarlarda da açılır.

### Seçenek 2 — Kaynaktan çalıştır

```bat
run.bat
```

veya:

```bat
python main.py
```

### Seçenek 3 — GitHub üzerinden indir

Depoya push yapıldığında **Actions → "Windows exe oluştur"** iş akışı `.exe`
dosyasını otomatik derler; çalışmanın **Artifacts** bölümünden indirebilirsin.

## Kullanım

1. Tıklama yapılacak Chrome sayfasını aç ve ekranda görünür durumda bırak.
2. Uygulamada **"Alan Seç"** butonuna bas — ekran karararır, tıklanacak bölgeyi
   fareyle sürükleyerek seç. (Vazgeçmek için `ESC`.)
   Tüm ekranı kullanmak için **"Tüm Ekran"** butonu da var.
3. Ayarları gir:
   - **Toplam tıklama:** örn. `50` (sınırsız için `0`)
   - **En kısa bekleme:** örn. `10` saniye
   - **En uzun bekleme:** örn. `90` saniye
   - **Başlangıç gecikmesi:** örn. `3` saniye
4. **"Başlat"** (veya `F8`) — gecikme süresi içinde Chrome penceresine geç.
5. Durdurmak için `F8` veya `ESC`; ya da **"Durdur"** butonu.

> Tıklamalar gerçek fare tıklaması olduğu için imleç kısa süreliğine hedef
> noktaya gider. Bilgisayarı bu sırada başka bir iş için kullanacaksan
> "İmleci geri döndür" seçeneğini işaretlemen daha rahat olur.

## Sık karşılaşılan durumlar

| Durum | Çözüm |
|---|---|
| Tıklama Chrome yerine başka pencereye gidiyor | Alanı seçtikten sonra Chrome penceresini taşıma/boyutlandırma; alan ekran koordinatına sabittir. |
| İlk tıklama sadece pencereyi öne getiriyor | Normaldir — arka plandaki pencerede ilk tıklama odaklanma için gider. Başlangıç gecikmesinde Chrome'a geçersen bu yaşanmaz. |
| Yönetici olarak çalışan bir programa tıklamıyor | Uygulamayı da **"Yönetici olarak çalıştır"** ile aç. |
| Ekran ölçeklemesi (%125/%150) yüzünden kayma | Uygulama DPI uyumludur; yine de sorun olursa alanı yeniden seç. |
| Antivirüs `.exe`'yi uyarıyor | Otomatik tıklayıcılar için tipik yanlış alarmdır; dosya bu kaynak koddan derlenmiştir, istisna ekleyebilirsin. |

## Proje yapısı

```
autoclicker/
  winapi.py    # SendInput ile tıklama, imleç, ekran ölçüleri, kısayol tuşları
  clicker.py   # ayar modeli + arka planda çalışan tıklama motoru
  selector.py  # ekran üzerinde alan seçme katmanı
  gui.py       # Tkinter arayüzü
  settings.py  # ayarların kaydedilmesi/okunması
main.py                  # giriş noktası
OtomatikTiklayici.spec   # PyInstaller yapılandırması
build.bat / run.bat      # derleme ve çalıştırma betikleri
tests/                   # motor testleri (python -m unittest discover -s tests)
```

## Not

Uygulama kendi bilgisayarında tekrarlayan işleri otomatikleştirmen içindir.
Kullandığın sitelerin kullanım koşullarına uygun şekilde kullan.
