# Altry

Android için ücretsiz, açık kaynak **video dublaj · ses klonlama · ses değiştirme · sıfırdan video üretme** aracı.
ElevenLabs benzeri bir stüdyo; ama ücretli hiçbir servise bağlı değil: yapay zekâ motoru senin
bilgisayarında ya da ücretsiz Google Colab'da çalışır.

## Neler yapar?

| Özellik | Ne olur |
|---|---|
| **Video dublajı** | Videodaki konuşmayı yazıya döker, seçtiğin dile çevirir ve **konuşmacının kendi sesiyle** (ya da kütüphanedeki bir sesle) yeniden seslendirir. Zamanlama korunur, arka plan sesi altta kalır, istersen altyazı eklenir. |
| **Ses değiştirme** | Videodaki/ses kaydındaki konuşmayı, sözleri ve zamanlamayı bozmadan seçtiğin sese dönüştürür. |
| **Ses klonlama** | Uygulamada 10–20 sn konuş, sesin kütüphaneye eklensin. Dosyadan ya da internetteki bir ses bağlantısından da eklenebilir. |
| **Metni seslendirme** | Yazdığını klonlanmış sesle söyletir; istersen bir videonun üzerine koyar. |
| **Sıfırdan video** | Metinden sahne sahne seslendirmeli, altyazılı video üretir (dikey / yatay / kare). Kendi görsellerini ve fon müziğini ekleyebilirsin. |
| **Hazır sesler** | Açık lisanslı örnek sesler tek dokunuşla kütüphaneye eklenir. |

23 dilde konuşur: Türkçe, İngilizce, Almanca, Fransızca, İspanyolca, İtalyanca, Portekizce, Rusça, Arapça, Japonca, Korece, Çince ve diğerleri.

## Nasıl çalışır?

```
Android uygulaması  ──HTTP──▶  Altry sunucusu (senin PC'n ya da Colab)
  android/                       server/
                                  ├─ faster-whisper          konuşma → yazı
                                  ├─ M2M100 / çevrimiçi çeviri yazı → hedef dil
                                  ├─ Chatterbox Multilingual  yazı → klonlanmış ses
                                  ├─ Chatterbox VC            ses → başka ses
                                  ├─ Demucs (isteğe bağlı)    konuşma / müzik ayırma
                                  └─ ffmpeg                   miks, altyazı, video
```

Bu modeller bir telefonda çalışamayacak kadar ağır; bu yüzden uygulama işi sunucuya gönderir,
ilerlemeyi gösterir ve sonucu telefona indirir.

## Kurulum

### 1. Sunucu

**Seçenek A — Google Colab (ücretsiz GPU, bilgisayar gerekmez)**
[`colab/altry_server.ipynb`](colab/altry_server.ipynb) dosyasını [Colab](https://colab.research.google.com)'da aç
(Dosya → Not defteri aç → GitHub), çalışma zamanını **T4 GPU** yap, iki hücreyi çalıştır.
Sonunda bir **sunucu adresi** ve **erişim anahtarı** verir.

**Seçenek B — Kendi bilgisayarın** (Python 3.10–3.12 ve [ffmpeg](https://ffmpeg.org/download.html) gerekir)

```bash
cd server
./run.sh          # Windows: run.bat
```

İlk çalıştırmada bağımlılıklar, ilk işlemde de modeller (~5 GB) iner. NVIDIA ekran kartı varsa otomatik
kullanılır; yoksa işlemciyle de çalışır ama yavaştır. Telefon ve bilgisayar aynı Wi-Fi'da olmalı.

**Seçenek C — Docker:** `docker build -t altry server && docker run -p 8000:8000 -v altry-data:/data altry`

### 2. Android uygulaması

- **Hazır APK:** GitHub'da *Actions → build → son çalıştırma → Artifacts → `altry-apk`*.
- **Kendin derle:** `cd android && ./gradlew assembleDebug` → `app/build/outputs/apk/debug/app-debug.apk`

Uygulamayı aç → **Ayarlar** → sunucu adresini (ör. `http://192.168.1.20:8000`) ve varsa erişim anahtarını yaz.

## Sunucu ayarları (ortam değişkenleri)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `ALTRY_TOKEN` | boş | Doluysa her istek `X-Altry-Token` başlığıyla bu anahtarı göndermek zorundadır. İnternete açıyorsan mutlaka ayarla. |
| `ALTRY_WHISPER` | `small` | Konuşma tanıma modeli: `tiny`, `base`, `small`, `medium`, `large-v3`. Büyüdükçe daha doğru ve daha yavaş. |
| `ALTRY_TRANSLATOR` | `auto` | `auto`: önce ücretsiz çevrimiçi çeviri, olmazsa çevrimdışı M2M100 modeli. `offline`: yalnızca çevrimdışı. `google`: yalnızca çevrimiçi. Daha doğru çevrimdışı çeviri için `ALTRY_TRANSLATION_MODEL=facebook/m2m100_1.2B`. |
| `ALTRY_SEPARATE` | `auto` | Demucs kuruluysa (`pip install demucs`) dublajda müzik/efektler temiz biçimde korunur. `0` kapatır. |
| `ALTRY_DATA` | `server/data` | Seslerin ve işlerin saklandığı klasör. |
| `ALTRY_MAX_MINUTES` / `ALTRY_MAX_UPLOAD_MB` | `30` / `500` | Dosya sınırları. |

API belgeleri sunucu açıkken `http://<adres>/api/docs` adresindedir.

## Geliştirme

```bash
cd server
pip install -r requirements-dev.txt
python -m pytest -q tests       # yapay zekâ modelleri yerine sahte motorlarla (ALTRY_FAKE=1) uçtan uca testler
```

## Sorumlu kullanım

Ses klonlama güçlü bir araçtır. Yalnızca **kendi sesini** ya da kopyalanmasına **açıkça izin veren** kişilerin
sesini kullan; uygulama ses eklerken bunu onaylamanı ister. Başkasını taklit ederek aldatmak, dolandırmak ya da
karalamak hem etik dışıdır hem de birçok ülkede suçtur. Chatterbox ile üretilen seslere, yapay zekâ ürünü
olduklarını gösteren duyulmayan bir filigran eklenir.

Hazır seslerin her biri kendi lisansına tabidir (bkz. `server/altry/catalog.json`); bazıları ticari kullanıma izin vermez.
