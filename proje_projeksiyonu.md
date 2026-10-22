# Proje Projeksiyonu (Test Dosyaları Hariç)

Kaynak klasör: `/home/emrah/Genel/core`
Toplam dosya: **41**
Toplam `def` (fonksiyon): **173**
Toplam `class` (sınıf): **19**

Bu dosya, projedeki her bir Python dosyasının içinde bulunan `def` tanımı ve `class` işlemlerini dosya bazında listeler.

---

## `ag.py`

### Fonksiyonlar (`def`)

- `_okunabilir_yap(yol)`  — satır 61  
    Açıklama: Hem root'lu (sudo) hem emrah'lı süreçler yazabilsin — 666.

Gerekçe: sudo'suz başlatma veri kaybına yol açıyordu (root dosya
emrah tarafından append edilemiyordu). Dosya zaten salt-okunur
eğitim verisi; erişim paylaşımı kasıtlı.
- `boyut_kontrol(yol, azami_mb)`  — satır 74  
    Açıklama: Veri 20 MB dolar ise arşive taşı (journal disiplini).
- `paket_bul(exe)`  — satır 91  
    Açıklama: /usr/bin/foo → hangi paket? (dosya sistemi öğretmen) — önbellekli.

dpkg veritabanı bazen usr-merge öncesi yolu tutar:
  diskte /usr/lib/systemd/systemd ama kayıtlı /lib/systemd/systemd.
Bu yüzden varyantlar da denenir (kullan.py ile aynı öğretmenlik).
- `dizin_sinif(exe)`  — satır 118
- `ilk_etiket(dsinif, paket)`  — satır 130  
    Açıklama: Nesnel öğretmenin geçici hükmü — insan/Faz2 düzeltir.
- `_uzuv_modeli()`  — satır 143  
    Açıklama: Faz 2 modeli — dosya oynadığında yeniden yükle (mtime).
- `sinifla(kayitlar)`  — satır 159  
    Açıklama: Bilinmeyenleri Faz 2 modeliyle sınıfla → (sayim|None, riskli).

Model yoksa (None, []) — FAZ 1 veri toplamaya devam eder, hiçbir
şey kırılmaz. Zayıf oto-etiket (govde/guvenli) bozulmaz; yalnızca
"bilinmeyen"ler modele sorulur — model de bilmezse o sınıfta kalır.
- `_ps_tablo()`  — satır 184  
    Açıklama: Tüm süreçler (sudo ile tüm kullanıcılar).
- `_ss_tablo()`  — satır 208  
    Açıklama: ss -tunap → pid → [soket]. Sudo ile root süreçlerin de pid'i görünür.
- `cekim()`  — satır 231  
    Açıklama: Tek çekim: tüm süreçler + ağ durumu → satırlar + jurnal özeti.
- `main()`  — satır 344

---

## `atolye.py`

### Sınıflar / İşlemler (`class`)

#### `Atolye`  — satır 48

- `__init__(self, world_kok, journal, politika)`  — satır 70
- `_durum_yukle(self)`  — satır 109
- `_durum_kaydet(self)`  — satır 116
- `_kesif_yukle(self)`  — satır 122  — Sahne 2b eylem sayımları — bozuk/eksikse sıfırdan başla.
- `_kesif_kaydet(self)`  — satır 131
- `_beklenen_yukle(self)`  — satır 137  — Sahne 1 tahmin modeli: eylem → {say, ort} (beklenen Δ'si).

Şekilsiz/bozuk kayıt atılır — model yeniden öğrenilir, sürpriz
yalan söylemez. Kalıcıdır: yeniden açılışta öğrenilmiş tahmin
taşınır (ESKI_AD mantığı gibi).
- `_beklenen_kaydet(self)`  — satır 158
- `_safe(self, ad)`  — satır 166
- `saglik(self)`  — satır 179  — 0..1: iyi bakılmış (bozuk olmayan) nesne oranı.
- `durum_vek(self)`  — satır 186  — Dünya modelinin gördüğü durum vektörü (tahmin girdisi).
- `tikla(self, tik)`  — satır 206  — Her tik: bozulma uygula + dünya modelini tahmin et/sürpriz ölç.

Bozulma: BOZULMA tik boyunca bakılmayan nesne bozuk sayılır
(içeriği 'kaybolur'). Dünyayı statik olmaktan çıkarır — dikkat
bütçesi gerektirir (gerçek sonuç, elle yazılmadı).
- `sec_is(self)`  — satır 240  — Organın kendi politikası: dünya durumundan sıradaki işi seç.

Beyin "atolye" der; bu organ NE yapacağına kendi karar verir
(katalogla/konum deseni). İki katman:

1. İhtiyaç refleksleri (her kol aynı): bozuk → onar (araçla
   toplu: guc, yoksa bak); kotada birleştir (kur: içerik +
   malzeme korunur, araç doğar); yarım dolu altı → yarat.
   Bunlar homeostazi — keşif değil. Ama refleks dünya
   sağlığını REFLEKS_ESIK tur üst üste sağlayamadıysa (onarım
   arzı < decay talebi → sıfır-bozuk şartlı serbest bant hiç
   açılmıyor; canlıda 8.5 saatlik kilit) bir tur serbest
   banda bırakır: sabır bitti, karar yine sayımın.
2. Serbest bant (orta bant) → KEŞİF, politika koluna bağlı;
   adaylar önce UYGULANABİLİRLİK kapısından geçer (uygulanamaz
   iş hiç seçilmez → no-op sayıma düşmez, keşif kilitlenmez):
   - "sayim" (prod): en az denenmiş eylem — sayımlar (is_say)
     besler; "kur araç doğurur" bilgisi KODA YAZILMADI, kur
     sayımın düşüklüğüyle ilk kararlarda kendiliğinden denenir
     → keşif dünyadan (nadirlik) doğar. Eşitlikte rastgelelik
     yalnız bağ bozar, seçim üretmez.
   - "eski" (ölçüm kontrolü): rastgele orta band + icat dalı.
   - "yok" (ablasyon): deterministik 'tasi' — keşif kapalı.
- `_tasi_hedefleri(self)`  — satır 316  — tasi'nin bugünkü geçerli hedefleri: ham nesne + hedef ad boş.

Önek BİR KEZ eklenir (grup_x → grup_grup_x DEĞİL); üst üste
grup taşıma ve ad çakışması kapalı kapıdır — no-op hem keşif
şişmesine yol açmaz hem de adlar 32-char sınırında ezilmez.
- `_serbest_adaylar(self)`  — satır 335  — Uygulanabilir serbest işler — uygulanamaz iş SEÇİLMEZ.

Kapı aday SEÇİMİNDEDİR: eylem() no-op'a düşmez, sayımlar
"denenmiş iş" anlamını korur ve keşif geçersiz bir işe asla
takılmaz (en az denenmiş ∩ uygulanabilir = canlı döngü).
- `_serbest_sec(self)`  — satır 353  — Serbest bandın kararı — politika koluna göre (sec_is'ten
ayrıldı: kaçış da, normal keşif de aynı sayım kapısından geçer;
tüm kollar uygulanabilirlik adaylarından seçilir).
- `eylem(self, is_, icerik)`  — satır 380  — Sahne 1 tek kapısı: işi çalıştır, öz-ödülü sürprizden biç.

Merak = eylemin dünya modeline yaşattığı ÖZ-KAYNAKLI sürpriz
(self-caused prediction error): gerçek Δ − eylemin ÖĞRENİLMİŞ
BEKLENEN Δ'si (.beklenen.json). Sürpriz = beklenmeyen değişim:
tekrarlanabilir eylem (her yarat "+1 adet") sürpriz üretmez —
ödül tarlası kapalı. Pasif bozulma sürprizi bu kapıdan ödül
almaz. Enerjiye gitmez (merak ≠ kalori); doğrudan öğrenme
sinyaline eklenir. no-op (dünyaya dokunmayan erken dönüş)
sayıma girmez: sayımlar "gerçekten denenmiş iş" demektir;
beklentiye de işlemez, sürpriz/ödül üretmez (tek kapı dürüstlüğ).
- `yarat(self, icerik)`  — satır 474  — Yeni nesne yarat. İçerik: organizmanın son gözlemi (deneyimini
'yazması'). Kota doluysa reddet → kıtlık gerçek hissedilsin.
- `bak(self)`  — satır 501  — Bak (oku + tazele → bozulmayı önle). Bozuk varsa öncelik onlar:
onarım bir iştir, rastgele okuma değil. Onarım malzemeyi KORUR:
içerik tam yazılır (guc ile aynı tam tur — [:80] kesik yok) ve
yazım hatası eylemi çökertmez (guc'un try/except kapısı).
- `tasi(self)`  — satır 533  — Yeniden düzenle: bir nesneyi grup-literaline taşı (yapı kurma).

Önek BİR KEZ eklenir: hedef zaten grup_ ise üstüne tekrar
eklenmez (grup_grup_x yok — yapı yığılmaz, adlar 32-char
sınırında ezilmez). Ham hedef yoksa kapı kapalıdır (no-op →
sayıma girmez, keşif şişmez).
- `sil(self)`  — satır 563  — Nesne sil (kota aç). Bozuk/boş nesnelerden başla (verimlilik).
- `kur(self)`  — satır 581  — Kompozisyon: iki nesneyi birleştir → araç.

Malzeme ekonomisi (tablo değil, cebir): kuvvet = toplam boyut
(bayt/64, en az 1), seviye = en derin parça + 1 (araçtan araç
olur). İçerik birikir (parça içerikleri tek dosyada korunur).
Kota doluysa silmek yerine birleştir — kıtlık yaratıcı olur.
Malzeme dürüstlüğü: parça içerikleri TAM olarak korunur (kesme
yok); kuvvet = GERÇEK korunan bayt/64 — kaybolan malzeme
sayılmaz, "bedava kuvvet" doğmaz.
- `guc(self)`  — satır 631  — Aracı kullan: kuvvet kadar bozuk nesneyi TEK eylemde onar.

Araç yorulur (kuvvet −onarım sayısı); kuvveti biten araç tükenir
(silinir) — araç da bir kaynaktır, sonsuz değil. Asıl kazanç
enerji tasarrufu (N bak yerine 1 eylem), ödül değil: merak hâlâ
sürprizden, tavanlı.

---

## `body.py`

### Sınıflar / İşlemler (`class`)

#### `Body`  — satır 15

- `__init__(self, cfg, root, journal)`  — satır 20
- `_seed_scan(self)`  — satır 49  — Tohumları yükle: dünyadaki .bite'lar + kalıcı manifest (.seeds.json).

Yemek süreç dışındayken de tükenmiş olsa geri dönebilir —
manifest olmazsa tohumlar unutulurdu.
- `_save_seeds(self)`  — satır 75
- `tick(self, energy)`  — satır 83  — Büyüme döngüsü: tükenen yemekler tohumdan yeniden doğar
+ yaşam valfi (olgunluk ölçülürse dünya cömertleşir).

ACİL DURUM: dünyada hiç yemek yoksa (ve tohum varsa) bekleme
yok — ilk tikte doğar. Çorak dünya, çorak doğum ölüm demektir.
- `_valve_check(self)`  — satır 119
- `_regrow_every(self)`  — satır 140
- `_regrow_batch(self)`  — satır 145
- `go(self, room)`  — satır 152  — Niyetli hareket: seçilen odaya git ve gözle.
- `_weighted_room(self, exclude)`  — satır 166  — Eğilimli rastgele oda seçimi (room_weights).
- `_maybe_move_food(self)`  — satır 184  — Yemekler kayar: odalar eğilimli rastgele seçilir (öğrenilebilir
ama ezberlenemez). Tohum/önbellek/yer tutma hep güncellenir.
- `_rel(self, path)`  — satır 232
- `_safe(self, rel)`  — satır 238  — Dünya dışında okuma/yazma yok (sahne kilidi).
- `_note(self, novelty, obs, kind)`  — satır 244
- `scan(self)`  — satır 251
- `find_food(self)`  — satır 260
- `_recipe_useful(self, rel)`  — satır 276  — Tarif hâlâ yeni bir yetenek vadediyorsa yenebilir sayılır.
- `_kutu_resolve(self, rel)`  — satır 289  — Kutu içi yol çözümü; dünya dışına çıkış burada da KAPALI.
- `kutu_yolu(self, p)`  — satır 306  — Her biçimi kanonik 'kutu/...' yoluna çevir; kutu değilse None.

Mutlak yol (ls/find çıktıları), kanonik yol ve tek isim (ls
çıktısı) formlarını tek çatıda toplar.
- `gorev_ayarla(self, klasor)`  — satır 327  — Misyon: 'şu klasörü ara' — kutu ağacı dışına çıkamaz.
- `kutu_listesi(self)`  — satır 341  — Kutu envanteri — HER çağrıda canlı tarama.

Eskiden tek-tarayış önbelleği vardı; kutular süreç içinde
değişince (yeniden üretim/açım) bayat envanter laboratuvar
hatası üretiyordu. 20 dosyayı her seferinde taramak ucuz.
- `_odul_coz(text)`  — satır 357  — İçerikten ödül: ENERGY=42 metin veya {"energy": 42} JSON.
- `_kutu_yut(self, target, rel)`  — satır 371  — Kutu tadımı: ödül al, dosyayı tüket (tek lokma).
- `feasible(self, actions)`  — satır 400
- `rooms(self)`  — satır 409  — Anlık oda listesi (dünyanın kök çocukları).
- `wander(self)`  — satır 417  — Çevreyi gezmek: bir odaya bak ya da bir dosyanın tadına bak.
- `eat(self, rel)`  — satır 445  — Bir dosyayı yutmak: .bite enerji, .recipe yeni organ,
kutu dosyaları kural ödülünü verir.
- `_calistir(self, argv, cap, ayrik)`  — satır 519  — Beyaz liste içinde komut çalıştır → (ok, çıktı).

Hem konsol hem tezgâh bu kapıdan geçer: dışarıya yazma yok,
komut whitelist'e tabi, süre ve çıktı boyutu tavanlı.
cap=None → kota tavanı (konsol); tezgâh envanter için büyük
tavan ister, aksi halde büyük klasörler sessizce kırpılır.

`ayrik=True` → (ok, stdout, stderr). YAPILANDIRILMIŞ ÇIKTI
AYRIŞTIRAN çağıranlar (tezgâh `find` çıktısını satır satır
ayrıştırıyor) İŞLE bu biçimi kullanmalı: 05.10'da stderr stdout'a
karışıp "find: '/root': Permission denied" satırları klasör sanıldı
ve 27 sahte kayıt kataloglandı. Konsol için birleşik çıktı
(izleyebilirlik) doğru davranıştır.
- `console(self, argv)`  — satır 553  — Konsol organı: beyaz liste dışı komut çalışmaz.
- `console_menu(self)`  — satır 600  — Beynin kurabileceği izinli komut sözlüğü.
- `sense_self(self)`  — satır 635  — İç duyarlar: /proc canlı organizmanın aynasıdır.
- `has_nest(self)`  — satır 653
- `nest_ready(self)`  — satır 656
- `nest(self, text)`  — satır 660  — Yuva yapmak: dinlenme ister, eski yuvayı yeniler (çöp yok).
- `perform(self, action, path)`  — satır 686

---

## `brain.py`

### Sınıflar / İşlemler (`class`)

#### `Brain`  — satır 39  
    Açıklama: Özellik-bazlı Hebbian beyin.

Uyaran '|' ile parçalanır; her (özellik, eylem) bağlantısı ayrı
öğrenir, eylem skoru = özelliklerin TOPLAMI. Böylece "açlık=A → eat"
bir kez öğrenilir, her konumda geçerlidir (genelleme). Durum-tek-
ağırlık tablosu yerine ~165 bağlantı yeter — hepsi sık görülür.

- `__init__(self, seed, lr, momentum, epsilon)`  — satır 74
- `stimulus(self, drives, context, loc, last_food, gorev, sistem, son, deneme, ara, dunya, surpriz)`  — satır 98
- `_bilesen(stim)`  — satır 161  — (tekil jetonlar, bağlam çaprazları) — pay bütçesi için.

S2: kolon-jetonu (gorev:*, son:*, deneme:*, dunya:*, sistem:*,
ara:*, surpriz:*, sikilma:*) çiftleri etkileşimi koda YAZILMADAN
öğrenir (ör. "gorev:X × son:hata → şu komut"). Ayraç "×" olmalı:
brain.load, "|" içeren anahtarları (eski durum-ağırlık göçü)
atlar — çapraz kalıcılıkta kaybolmasın diye.
- `features(stim)`  — satır 178
- `_get(self, feat, action)`  — satır 182
- `decide(self, stim, feasible)`  — satır 186  — Keşif güvene bağlı: ε_eff = ε / (1 + marj).

Marj = en iyi − ikinci skor. Sıfırken (hiçbir şey bilinmiyor)
tam keşif; beyin emin oldukça keşif kendiliğinden kısılır —
eşik veya ek sayı yok, tek formül. 2026-10-12 ölçümü: sabit
%35 keşif, öğrenilmiş görevlerde başarıyı %70'te tavanlıyordu
(beyin biliyordu, keşif faturası ödüyordu). Bilgi erozyonu
olursa (doğru komut artık çalışmıyorsa) marj daralır ve keşif
kendiliğinden geri açılır.
- `score(self, stim, action)`  — satır 234  — Eylemin bu uyaran için toplam skoru (özellik ağırlıkları toplamı).
- `_yaz(self, key, pay)`  — satır 238  — Bağlantıyı güncelle: hafif sönüm + kırpma (S5 şişme koruması).
- `learn(self, stim, action, reward, r_merak)`  — satır 247  — Delta kuralı + S1 gecikmeli kredi + S2 çapraz pay bütçesi + S3 merak.

S3: merak (keşif/"bilmiyorum ama deneyeyim") ödülü için ayrı
öğrenme hızı: lr_merak = lr * 1.5. R_merak > 0 olduğunda organizma
sürpriz/keşifli eylemini kalıcılaştırır — kalıcı "merak" davranışı.
- `credit(self, stim, action, bonus)`  — satır 266  — Gecikmeli kredi: hedefi değiştirmeden eklemeli itme.

(learn() hedefe çeker; gecikmiş bonus ise anlık ödülün üstüne
biner, onu ezmemeli.) learn() ile aynı iki-bütçe düzeni (75/25).
- `hatira(self, journal_yolu, azami, kuyruk)`  — satır 280  — Aşama 4 — hatıra: uykuda kendi geçmişini yeniden yaşama.

learn satırları (stim, action, R) kaydından son pencereyi okur,
GÜNCEL ağırlıklarla yeniden oynar (deneyim tekrarı): yeni
deneyimlerin sürüklediği bağlantıları kendi geçmişine çeker.
Ödül uydurulmaz — jurnale o an kaydedilen R tekrarlanır; eski
(R'siz) learn satırları atlanır. Dönüş: oynanan örnek sayısı.
- `konsolide(self, esik)`  — satır 328  — Aşama 5 — konsolidasyon: uykuda zayıf bağlantı budama.

_yaz her dokunuşta küçük paylar biriktirir; tekrar tekrar
dokunulan ama hiç sonuç getirmeyen (ödülü ~0) bağlantılar
esik altında kalır ve tabloda ölü ağırlık olarak şişirir.
Budama nötrdür: _get eksik anahtar için 0.0 döndürdüğü için
|w| < esik olan bağlantının silinmesi skoru en fazla esik
kadar oynatır (eylem sıralamasını praktikte değiştirmez).
INSTINCTS (doğuştan refleksler) öğrenmeyle ezilmiş olsalar
bile budanmaz — yaşama yanlısı yaratılış koruması.
Dönüş: budanan bağlantı sayısı (uyku raporu için).
- `report(self, top)`  — satır 347  — Öğrenilmiş en güçlü bağlantılar (gözlem için).
- `save(self, path)`  — satır 357  — tmp + rename: yazma yarıda kesilse bile beyin bozulmaz.
- `load(self, path)`  — satır 369  — Doğuşta beyni hatırla; bozuk/eksik dosya doğuşu iptal etmez.

---

## `damak.py`

### Fonksiyonlar (`def`)

- `ozellikler(name, cfg, path)`  — satır 22  
    Açıklama: İsim → özellik anahtarları (kategori birleşimi + bucket'lar).

path verilirse **derinlik** özelliği de eklenir (kutular düzeni):
derin klasör = büyük ödül bilgisi böyle öğrenilir.

### Sınıflar / İşlemler (`class`)

#### `Damak`  — satır 50

- `__init__(self, lr, yumusatma)`  — satır 51
- `ogren(self, feats, odul)`  — satır 60
- `tahmin(self, feats)`  — satır 76
- `sec(self, isimler, cfg, epsilon)`  — satır 86  — Adaylar arasından en yüksek tahminli (keşif payı ile) seç.

Adaylar düz isim YA DA tam yol olabilir. Yol gelirse isim olarak
son parça kullanılır ve derinlik (d=) özelliği de katılır; böylece
seçim, öğrenmede (ogren) kullanılan özelliklerle birebir aynıdır.
(Eski sürüm tam yolu isim sanıyordu → 'karisik' kovası → hiçbir
öğrenilmiş özellik eşleşmiyor, tüm adaylar eşit çıkıyordu.)
Eşitlikte ilk eleman değil, rastgele biri seçilir.
- `save(self, path)`  — satır 112
- `load(self, path)`  — satır 131

---

## `ders.py`

### Fonksiyonlar (`def`)

- `_yol(yol)`  — satır 49
- `toplu(hedef, dogrusu, yol)`  — satır 53  
    Açıklama: Defterdeki AÇIK satırlarının tümüne aynı düzeltmeyi ekle.

İnsan toplu sözü: "şu hedefin doğrusu şudur" — işaretlenmemiş
her satıra |dogrusu=... ekler; oku() bir sonraki döngüde işler.
İşaretli satırlara dokunmaz (zaten öğrenilmiş/reddedilmiş).
→ (islenen_satir_sayisi)
- `_sikistir_satirlar(satirlar, bas)`  — satır 87  
    Açıklama: Ham deneme satırlarını (hedef, komut) başına en fazla `bas`
taneyle sınırla → (kalan_satirlar, arsivlenecekler).

Yalnızca HAM satırlar sıkıştırılır: |dogrusu= (insan düzeltmesi
bekleyen) ve |ok=1|işaretli satırlara asla dokunulmaz.
- `sikistir(yol, bas)`  — satır 110  
    Açıklama: Defter hijyeni: fazla ham örneği arsive taşı (silme, taşıma).

journal'daki "kullan" satırları tüm deneme geçmini kanıtladığı
için arşiv yalnızca disk alanını korur. → (tasinan, kalan_satir)
- `yaz(hedef, komut, ozet, yol)`  — satır 143  
    Açıklama: Yanlış denemeyi deftere düş (append).
- `_ayristir(satir)`  — satır 151  
    Açıklama: (kayit, dogrusu, islenmis) — işaretleme JSON bozmadan satır sonunda.
- `_gecerli(ad, beyaz)`  — satır 168  
    Açıklama: cmd:ön eki + beyaz liste (insan yazsa da güvenlik ihlal edilemez).
- `oku(mind, jour, yol, beyaz)`  — satır 178  
    Açıklama: İşaretlenmemiş düzeltmeleri beyne işle, satırları |ok=1 ile boşa.

→ (islenen_sayi, atlanan_sayi)

---

## `dizin.py`

### Fonksiyonlar (`def`)

- `boyut_kovasi(boyut)`  — satır 23
- `ozellikler(ad)`  — satır 30  
    Açıklama: Dosya adından çıkan basit, yorumlanabilir özellikler.
- `kaynak_koku(klasor)`  — satır 42  
    Açıklama: Sınıf = arama için ANLAMLI aile: '/etc' ve '/usr/share' gibi.

Veriye baktık: /etc altındaki her klasör ayrı sınıf olsaydı model
'hangi klasör' tahmin etmeye çalışır (işe yaramaz, %50). Oysa
arama ekonomisi için 'hangi AİLE' bilgisi yeter: /usr altında
ağaç derindir (2 bileşen), /etc sığdır (1 bileşen).
- `egit(dosyalar_jsonl, sinif_tipi, karistir)`  — satır 151  
    Açıklama: katalogdan eğit → (model, egitim satırları listesi).

### Sınıflar / İşlemler (`class`)

#### `Dizin`  — satır 58  
    Açıklama: Sınıf frekansı modeli (Laplace): ozellik → sinif sayacı.

- `__init__(self, siniflar, agirlik, oncelik)`  — satır 61
- `klonla(self, agirlik)`  — satır 69
- `ogren(self, feats, sinif)`  — satır 76
- `_log_olasilik(self, feats, sinif)`  — satır 82  — Sınıfın log olasılığı: özellik frekansı (Laplace) + hafif öncelik.

Ağırlık dengeyi kurar: yumuşak ağırlık nadir sınıfları eziyor
(kaynak görevinde top-1 %29), sert ağırlık boyut görevini
bozuyordu (%87 → %60). Tek sabit yerine görev başına seçilir
(egit_dizin.py taraması).
- `tahmin(self, feats)`  — satır 103  — En olası sınıf + sınıf skorları.
- `sirala(self, feats)`  — satır 109  — Sınıfları olasılık sırasıyla döndür (en olasıdan).
- `save(self, path)`  — satır 117
- `load(self, path)`  — satır 131

---

## `door.py`

### Fonksiyonlar (`def`)

- `send(host, port, message)`  — satır 75
- `watch(path)`  — satır 90  
    Açıklama: Günlüğü canlı izle (tail -f).

### Sınıflar / İşlemler (`class`)

#### `Door`  — satır 15

- `__init__(self, host, port, status_fn, queue, journal)`  — satır 16
- `start(self)`  — satır 26
- `_serve(self)`  — satır 42
- `stop(self)`  — satır 66

---

## `drives.py`

### Sınıflar / İşlemler (`class`)

#### `Drives`  — satır 8

- `__init__(self, cfg)`  — satır 9
- `alive(self)`  — satır 27
- `pain(self)`  — satır 30  — Acı yoğunluğu 0..1: eşiğin altına ne kadar derin indi.
- `in_danger(self)`  — satır 38
- `tick(self)`  — satır 41  — Kalp atışı: her tik metabolizma faturasıdır.
- `spend(self, cost)`  — satır 48
- `consume(self, gain, relief)`  — satır 51  — Yemek: enerji al, açlığı dindir.

Gerçekte alınan enerji ve gerçek azalan açlık döner — ödül
bu "gerçek" değerler üzerinden biçilir (tokken yemek boş).
- `spark(self, amount)`  — satır 65  — Küçük kıvılcım (ör. kapıdan gelen ilgi).
- `sikilan(self, novelty)`  — satır 71  — Sıkılma güncelle (Aşama 4): yenilik doyurur, rutin bunaltır.

novelty KESİRLİ olabilir (0..1): 1.0 tam yenilik (eski davranış
aynen), 0.3 gibi değerler kısmi doygunluk (ör. küçük merak
ödülü). Dönüş: 0..1 sıkılma — beyin keşif baskısını bundan alır.
- `bins(self)`  — satır 85
- `state(self)`  — satır 90

---

## `egit.py`

### Fonksiyonlar (`def`)

- `holdout_mu(name)`  — satır 39  
    Açıklama: Isim hold-out bolumunde mi? (kararli: yalnizca isme bagli)
- `isim_uret(rng, cfg)`  — satır 44
- `bolumlu_isim(rng, cfg, holdout, deneme)`  — satır 51  
    Açıklama: Istenen bolumden (egitim / hold-out) isim uret (red ornekleme).
- `egit(cfg, adet, seed, kaydet)`  — satır 61  
    Açıklama: Modeli egit. kaydet=False: diske yazma (test/ablasyon icin).

NOT (2026-10-18): save() zeka.kayit('damak.json') = GERCEK model
dosyasi. Testler kaydet=False vermezse her test kosusu 50000'luk
canli modeli kucuk egitimle cokertir (test_uyku_egit EgitTest,
500 ornek/37 kova ile yakalandi).
- `_tip(govde)`  — satır 83
- `degerlendir(cfg, d, adet, seed)`  — satır 87  
    Açıklama: Hold-out: egitimde HIC kullanilmamis isimlerde tahmin dogrulugu.

Rapor tekrarlanabilir: damak.sec() global random kullandigi icin
degerlendirme boyunca global durum sabit tohumlanir, sonra geri
yuklenir.
- `rapor_bas(d, dt, rapor, satirlar)`  — satır 184
- `main()`  — satır 205

---

## `egit_ag.py`

### Fonksiyonlar (`def`)

- `gunlugu_oku(yol, kuyruk)`  — satır 32  
    Açıklama: Jurnalin son penceresi (brain.hatira ile aynı okuma deseni).
- `rapor(kayitlar)`  — satır 53  
    Açıklama: Kapı bazlı deneme/kazanma + duraklama tablosu (AG_TARA + BENI_TARA).
- `tekrar_oynat(mind, kayitlar, epok)`  — satır 87  
    Açıklama: gorev:AG_TARA/gorev:BENI_TARA uyaranlı learn kayıtlarını kayıtlı R ile oynat.

Ödül uydurulmaz: jurnale o an ne yazıldıysa o tekrarlanır. AG_TARA
dışı learn satırları seçilmez (hedefli tekrar — ağ öğrenmesinin
diğer bağlantılarını bozmaz).
- `main()`  — satır 112

---

## `egit_dizin.py`

### Fonksiyonlar (`def`)

- `satirlari_oku(yol)`  — satır 26  
    Açıklama: Katalog satırları: önce SQLite (tek gerçek kaynak), yoksa JSONL.
- `degerlendir(d, test, etiket)`  — satır 63
- `faydalilik(d, test, etiket)`  — satır 73  
    Açıklama: top-1 / top-3: tahmin edilen kaynak gerçekte dosyayı içeriyor mu?
- `temel_cizgi(test, etiket)`  — satır 89  
    Açıklama: Baskın sınıfı hep seçen "sağır" modelin doğruluğu.

Neden şart: tek sınıflı bir katalogda model %100 "başarılı" görünür
ama hiçbir şey öğrenmemiştir (05.10'da risk modelinde yaşandı).
Gerçek doğruluk ancak bu çizginin ÜSTÜNDEYSE anlamlıdır.
- `main()`  — satır 103

---

## `egit_guvenlik.py`

### Fonksiyonlar (`def`)

- `zarar_uygula(E, tip, miktar, durum)`  — satır 31  
    Açıklama: Zarar kodunun etkisi. durum: süreli zarar kuyruğu.
- `fizik()`  — satır 46
- `mini_omur(E, H, yemek, tip, miktar, f, tik)`  — satır 56  
    Açıklama: Şoku UYGULA ve 'tik' boyunca yaşat. True = yaşadı.
- `senaryo_uret(rng, f, adet)`  — satır 82  
    Açıklama: (feats, etiket): etiket = simülasyon SONUCU (kural yok).
- `deneyim_yukle()`  — satır 97  
    Açıklama: Yaşarken verilen kararlar → simülasyonla etiketlenir → veriye
dönüşür.

Hata muhasebesi önemli:
  * aşırı cesaret = "uygula" dedi ama sim ölüm diyor  → HATA
  * erteleme    = "bekle" dedi, sim "yaşardı" diyor      → HATA DEĞİL
    (bilinçli erteleme; sadece fırsat kaçırması sayılır)
Süremsiz (damgasız) kayıtlar ayrı tutulur.
- `_marj_kova(feats)`  — satır 138  
    Açıklama: Bir özellik listesinden marj kova anahtarını çıkar (şemadan bağımsız).
- `rapor(d, veri_test, say)`  — satır 146
- `main()`  — satır 176

---

## `egit_olum.py`

### Fonksiyonlar (`def`)

- `gozlem_seti(adlar, ornek, rng, kayip)`  — satır 35  
    Açıklama: Verilen nedenlerden (ad, gozlem) çiftleri üret.
- `degerlendir(model, ciftler)`  — satır 44  
    Açıklama: (kategori-dogru, orani, strateji-dogru, orani, karisimlar).

Strateji: tahmin edilen kategoriden türetilir vs katalog etiketi.
- `baseline(ciftler, alani)`  — satır 68  
    Açıklama: Hold-out majority-baseline: `alani` (kategori_of / strateji_of).
- `loo_degerlendir(ornek, kayip, seed, agirlik)`  — satır 76  
    Açıklama: Leave-one-cause-out: her neden birer birer dışarıda bırakılır.

Tek rastgele bölme (4 neden) aşırı gürültülüdür — hold-out'un kategori
karışımı şansa bağlı. BURADA 20 kat vardır: her kat, 19 nedenden öğrenip
HİÇ GÖRÜLMEMİŞ tek nedeni teşhis eder; sonuçların ortalaması stabil
gerçek genelleme ölçümüdür.
- `main()`  — satır 121

---

## `egit_paket.py`

### Fonksiyonlar (`def`)

- `main()`  — satır 22

---

## `egit_risk.py`

### Fonksiyonlar (`def`)

- `satirlari_oku(sinir)`  — satır 23
- `degerlendir(model, test, dunya_koku)`  — satır 50
- `main()`  — satır 65

---

## `egit_uzuv.py`

### Fonksiyonlar (`def`)

- `satirlari_oku()`  — satır 25  
    Açıklama: Tüm uzuv verisini AKIŞKAN okur — ham satır listesi tutulmaz.

Eski biçim: 20 arşiv × 21MB (~440MB JSON) tek tek json.loads ile
`kayitlar` listesine yığılıyordu → ~2-3GB RSS → OOM kill (-9) ya da
300sn timeout (-1); model saatlerce tazelenemiyordu (canlı log:
uyku_bitti uzuv kod=-1/-9). Yeni biçim: her satır parse edilir
edilmez (comm,exe,kullanici,paket) anahtarıyla tekilleştirilir;
tekrar eden satır anında atılır. Tepe bellek ≈ benzersiz süreç
sayısı (binlerce küçük dict) — dört-ciglik bir fark.

Kaynak sırası: ESKİDEN YENİYE (arsiv/*, sonra canlı uzuv_veri.jsonl);
"ilk görülen kazanır" — chronology bozulmaz.
- `main()`  — satır 61

---

## `golge.py`

### Fonksiyonlar (`def`)

- `_atalar()`  — satır 130  
    Açıklama: Kendi s�re� aac1n1n �st s�re�leri (terminal/oturum)  korunur.
- `korunan_surecler()`  — satır 147  
    Açıklama: Canl1 korunan s�re�ler: [(pid, comm, cmdline)]. Salt okuma (/proc).
- `korunan_pid_kumesi(korunan)`  — satır 170
- `_tokenle(komut)`  — satır 175
- `_kalip_ve_bayrak(args)`  — satır 181
- `_yol_korunan(t)`  — satır 196
- `_birim_adi(u)`  — satır 201
- `_seg(toks, korunan, derinlik)`  — satır 208  
    Açıklama: Tek komutun (jeton listesi) s1n1f1: (sinif, neden).
- `_plan(komut, korunan)`  — satır 404  
    Açıklama: Komutu ayr1_t1r + s1n1fla. D�ner: sinif, neden, segs, calistirilabilir.
- `siniflandir(komut, korunan)`  — satır 465  
    Açıklama: D�ner: (sinif, neden). �ncelik: yasakli > yikici > okuma.
- `_calistir_boru(segs, zaman_asimi, stdin)`  — satır 474  
    Açıklama: Par�alar1 Popen ile bala. D�ner: (rc, stdout, stderr). Kabuk kullan1lmaz.
- `wilson_alt(k, n, z)`  — satır 613
- `_oku_jsonl(yol)`  — satır 623
- `_log_tum()`  — satır 636  
    Açıklama: Canlı log + arşivler (zaman sırası).

main.py golge_log.jsonl'yi boyut eşiğinde arsiv/ altına taşır;
incele/rapor yalnızca canlı dosyayı okursa tarihi görmez. Arşiv
adayları journal.arsivle desenindedir: arsiv/golge_log_*.jsonl.
- `cmd_incele(en_fazla)`  — satır 653
- `cmd_rapor(min_n, esik)`  — satır 682
- `cmd_test()`  — satır 720
- `main()`  — satır 831

### Sınıflar / İşlemler (`class`)

#### `Kapi`  — satır 555

- `__init__(self, mod, log, korunan, zaman_asimi)`  — satır 556
- `calistir(self, karar)`  — satır 564

---

## `golge_ek.py`

### Fonksiyonlar (`def`)

- `_curl(args)`  — satır 58
- `_nmap(args)`  — satır 106
- `ek_siniflandir(verb, args, tum)`  — satır 139  
    Açıklama: (sinif, neden) veya None (mevcut dallara birak).
- `_test()`  — satır 182

---

## `gorev.py`

### Sınıflar / İşlemler (`class`)

#### `Tezgah`  — satır 22

- `__init__(self, cfg, body, jour)`  — satır 23
- `reload_dizin(self)`  — satır 67  — Uyku eğitimi sonrası dizin modelini tazele (Z1 — bayat-ağırlık
koruması). load() yeniden girişlidir: iki kaynak da okunamazsa
eski model aynen kalır (dizin_yok False'a çekilmez).
- `konum_aktif(self)`  — satır 79
- `_katalog_sayisi(self)`  — satır 86  — Katalogdaki dosya satırı sayısı (dosya sayısı değil satır).
- `_katalog_adlari(self)`  — satır 90  — Kendi katalogundan dosya adları (kendi öğrendiği dünya).
- `nedir_bir(self, beyin)`  — satır 96  — Rastgele çalıştırılabilir aday seç → BEYNİNE sor → bilemezse
GERÇEK `dpkg -S` ile doğrula ve ÖĞREN (kendi kendine öğretim).

Ödül haritası: "biliyordu" ucuza gelir, "öğrendim" pahalıdır —
organizma merakla bilmediği şeylere yönelir, ekonomi kuran
doğrulamayı seçer.
- `konum_bir(self)`  — satır 160  — Bir dosyanın yerini tahmin et ve doğrula (1-3 alt süreç).

Model ilk 3 aileyi önerir; organizma SADECE oraları tarar.
Bulursa ödül kazanır → modelin bilgisi işe yaramıyorsa
denemeler hep ıskalıyor ve katalog işi daha cazip hale gelir.
- `_goc_yap(self)`  — satır 204  — Eski/akan JSONL katalogu SQLite'a taşı.

Her doğuşta çalışır: içe aktarım idempotenttir (PRIMARY KEY aynı
satırı iki kez almaz) ve ~0.5 sn sürer. Böylece çalışan eski
organizmanın JSONL'e yazdığı kalemler kaybolmaz.
- `_supheli_temizle(self)`  — satır 219  — Çöp satırları ("find: ... Permission denied" vb.) her doğuşta sil.

Dışarıdan yazma YAPILMAZ: çalışan organizmanın WAL'ı bozulur.
Temizliği yaşamın kendisi yapar.
- `_jsonl_aktar(self)`  — satır 236  — Denetim için JSONL dışa aktarımı (SQLite tek gerçek kaynak).
- `_katalogdan_oku(self)`  — satır 243  — Var olan envanterden biten klasörleri topla.
- `aktif(self, tik)`  — satır 249
- `hedef(self)`  — satır 260
- `ilerleme(self, tik)`  — satır 263
- `hedef_ulasildi(self)`  — satır 276  — Bu yaşamın hedefine ulaşıldı mı? (ceza ölçümü için)
- `bitti_mi(self)`  — satır 281  — Tezgâh eylemi sunulmaya devam etmeli mi?

DİKKAT: burada `hedef` KULLANILMAZ. `hedef` per-yaşam hedefidir ve
ceza ölçümünü durdurur; görevi kalıcı olarak kapatmaz. 23:33'te
gorev.json'daki hedef 600→20 düşürüldüğünde, 505 klasör kataloglanmış
bir organizmada `bitti_mi()` bir daha hiç False olmadı: görev
18 saat sessizce durdu, beyin boşta kalan `go:katalog` yürüyüşünde
döngüye girdi. Sunumu durduran tek şey GERÇEK tükenmedir
(`tamamlandi`: bütçe doldu ya da tavan derinlikte de yeni klasör
çıkmadı).
- `sure_kontrol(self, tik)`  — satır 297  — Süre doldu ve hedefe ulaşılmadıysa True → ceza doğar.
- `_haric_mi(self, yol)`  — satır 312  — Sanal/canlı dosya sistemleri ve gizli ölçüm yolları dışarıda.
- `_duvar_listesi(self, kok, sinir)`  — satır 321  — Duvar modu: kokun ALTINDAKİ tüm klasörler (derinlik sınırlı).

`find -maxdepth N -type d` tek alt süreçte yüzlerce klasörü verir;
her biri sonra tek tek işlenir (her kalem = gerçek CPU).

Derinlik `self.derinlik`'tir (kuyruk tükendiğinde DERİNLEŞİR),
`self.cfg["derinlik"]` sabit tavan değildir.
- `_erisilemezleri_isle(self, err)`  — satır 393  — find stderr'inden "Permission denied" yollarını topla.

Bunlar kataloglanamaz ama "olduğu" bilinir: katalog kendi kör
noktasını bilmelidir (0 dosya ≠ okunamadı).
- `_klasorleri_tara(self)`  — satır 422  — Kaynak köklerin altındaki YENİ klasörleri sıraya al.

Kaynaklar DÖNÜŞÜMLÜ karıştırılır: ilk kaynak kuyruğu doldurup
diğerlerini aç bırakmaz (kaynak açlığı).
- `_dosya_kayitlari(self, yol_listesi, zaman)`  — satır 514  — Dizin haritasının dosya katmanı: yol, klasör, ad, uzantı, boyut.

Bu tablo Faz 2'nin (katalogdan kendini eğiten model) veri
tabanıdır: "hangi dosya nerede" bilgisi burada birikir.
- `calistir_bir(self, tik)`  — satır 524  — Bir kalemlik iş: sıradaki klasörü oku, envantere yaz.

---

## `guvenlik.py`

### Fonksiyonlar (`def`)

- `marj_ozellik(m)`  — satır 38
- `features(E, H, sarsinti, yemek, ek)`  — satır 47  
    Açıklama: Durum → özellik anahtarları (bucket). Genişletilebilir.

NOT: 'marj' (E − şok) zaten enerji ve şoku BİRLİKTE taşır; ayrı 'e'/'s'
özellikleri koymak çapraz gürültü yapıp tehlikeli bölgede yanlış
karara yol açıyordu (E=101 & şok=120 durumu, küçük şoklu güvenli
durumlarla aynı 'e' kovasını paylaşıyordu). Bu yüzden sadeleştirildi.
- `veri_yaz(kayit, path)`  — satır 136  
    Açıklama: Yaşam kararı kaydı (eğitim verisine dönüşür) — append-only.

### Sınıflar / İşlemler (`class`)

#### `Guvenlik`  — satır 69  
    Açıklama: Delta öğrenmeli karar modeli: etiket 1=uygula, 0=bekle.

- `__init__(self, lr, yumusatma)`  — satır 72
- `ogren(self, feats, etiket)`  — satır 80
- `tahmin(self, feats)`  — satır 93
- `karar_ver(self, E, H, sarsinti, yemek, ek, esik)`  — satır 100  — → ('uygula'|'bekle', puan). Eşik varsayılan: ESIK (asimetrik).
- `save(self, path)`  — satır 108
- `load(self, path)`  — satır 119

---

## `journal.py`

### Fonksiyonlar (`def`)

- `_brief(data, limit)`  — satır 26
- `replay(path)`  — satır 31  
    Açıklama: Günlüğü baştan oynat: python3 journal.py replay [journal.jsonl]
- `arsivle(path)`  — satır 48  
    Açıklama: Günlüğü tarihli arşive taşı, yerine boş bırak (aynı disk → atomik).

Canlı süreç için güvenli: Journal.log dosyayı her çağrıda 'a' modunda
yeniden açar; taşımadan sonraki ilk yazı yeni günlüğü yaratır.

### Sınıflar / İşlemler (`class`)

#### `Journal`  — satır 11

- `__init__(self, path, quiet)`  — satır 12
- `log(self, kind, **data)`  — satır 16

---

## `kanit_dongu.py`

### Fonksiyonlar (`def`)

- `calistir()`  — satır 22
- `main()`  — satır 38

---

## `kanit_ogrenme.py`

### Fonksiyonlar (`def`)

- `jurnal_dosyalari()`  — satır 54  
    Açıklama: Canlı jurnal + en son jurnal arşivi (kronolojik sırada).

Jurnal 20MB'da main.py tarafından otomatik arşivlenir; tek başına
canlı dosya arşivlenmiş learn kayıtlarını görmez. Epoch'un son
parçası = en yeni arşiv + canlı dosya.
- `learn_kayitlari(dosyalar)`  — satır 66  
    Açıklama: Verilen jurnal dosyalarından learn satırlarını kronolojik okur
(salt okuma; dosya sırası = kronoloji).
- `pearson(xs, ys)`  — satır 86
- `r_ve_perm(b, pairs, perm, rng)`  — satır 102  
    Açıklama: skor↔R korelasyonu + permütasyon null'dan p değeri.
- `sabit_skor(b, pairs)`  — satır 116  
    Açıklama: Beyin tüm çiftlerde aynı skoru veriyorsa True (sabit fonksiyon).
- `replay(b, kayitlar, karistir, rng)`  — satır 124  
    Açıklama: Learn kayıtlarını sırayla beyne oynat (hatıra ile aynı kural).
- `grupla(pairs)`  — satır 137  
    Açıklama: uyaran → {eylem: [R...]} — ortalama R ile adil karşılaştırma.
- `ust1(b, pairs, tohum)`  — satır 145  
    Açıklama: Argmax gerçekten en yüksek ortalama R'li eylemi seçiyor mu?

Döner: (doğru, toplam, şans, politika_değeri). politika_değeri =
seçilen eylemlerin ortalama R'si. Beraberlik, sabit tohumlu
paylaşılan sırayla kırılır: her beyin aynı grup sırasını ve aynı
karışımı görür (adil karşılaştırma).
- `agirlik_tablosu(b, etiketler)`  — satır 177  
    Açıklama: (etiket, cmd:wc) bağlantı ağırlıkları — kuralın mekanizması.
- `main()`  — satır 182

---

## `katalog.py`

### Fonksiyonlar (`def`)

- `norm(yol)`  — satır 51  
    Açıklama: Yol normalizasyonu: aynı klasör/dosya TEK sayılsın.

`/etc`, `/etc/`, `/etc/.`, `//etc`, `/etc/./x` ve `/usr/lib/../lib/x`
→ hepsi kanonik tek biçime iner.
- `uzanti(ad)`  — satır 78
- `proje_kok()`  — satır 415  
    Açıklama: Proje kökü (bu dosyanın bulunduğu dizin).

DİKKAT: burada TAM BİR dirname yeterlidir. Bir kez daha çağrılırsa kök
bir üst dizine (Genel/) kayar, `organizma_yasiyor` hiçbir süreç
bulamaz ve sıfırlama kilidi sessizce düşer. 05.10'da böyle oldu:
çalışan organizmanın veritabanı arşivlenip yerine boş bırakıldı,
süreç arşivlenmiş inode'a yazmaya devam etti.
- `anlik_kopya(db_yolu, hedef, deneme)`  — satır 427  
    Açıklama: Canlı veritabanından TUTARLI anlık kopya al → kopya yolu.

Neden şart: canlı WAL veritabanını başka bir süreç doğrudan okuduğunda,
yazıcı checkpoint yapıp -wal'ı değiştirdiği anda okuyucu
"database disk image is malformed" hatası alabilir (05.10 19:20'de
yaşandı — sağlık aracı okurken organizmanın _jsonl_aktar'ı bu hatayı
gördü). Kopya, SQLite'ın kendi online-backup protokolüyle alınır:
kilitli sayfa kopyalama, tutarlı anlık görüntü, okuyucu-kırıcı değil.

Doğrudan dosya kopyası (shutil.copy) YETERLİ DEĞİLDİR: -wal içindeki
commit'ler kopyalanmaz veya kırılır.
- `organizma_yasiyor(kok)`  — satır 458  
    Açıklama: Bu projede çalışan `main.py` süreci var mı? (PID veya None)

Yazma yapan bir sürecin veritabanını silmek/taşımak, o sürecin
tanıtıcılarını sahipsiz bırakır (05.10'da yaşanan WAL kazası).
Bu yüzden sıfırlama çalışan bir organizmaya sessizce uygulanmaz.
- `sifirla(dizin, zorla, saat)`  — satır 493  
    Açıklama: Katalog deposunu arşivleyip BOŞ olarak yeniden kur.

Silmez, arşivler: `world/katalog/arsiv/<damga>/` altına katalog.db
(+ -wal/-shm) ve JSONL dışa aktarımları taşınır. Böylece "sıfırla"
geri alınabilir bir işlemdir.

Döner: {"arsiv": yol, "tasinan": [...], "pid": pid, "uyari": str}

### Sınıflar / İşlemler (`class`)

#### `Katalog`  — satır 83

- `__init__(self, yol, saat, salt_okunur)`  — satır 84  — `salt_okunur=True` ÇALIŞAN organizmanın veritabanını bozamaz.

ÖNEMLİ: yazma kipiyle açılan ikinci bir bağlantı, temiz kapandığında
`-wal`/`-shm` dosyalarını SİLER; çalışan sürecin açık tuttuğu
tanıtıcılar sahipsiz (unlinked) inode'a düşer ve o andan itibaren
o sürecin yazdıkları görünmez olur. Analiz/ölçüm araçları (eğitim,
rapor) bu yüzden daima salt okunur açmalı — ya da bir kopyayı.
- `kapat(self)`  — satır 113
- `klasor_yaz(self, yol, dosya, karakter, durum, goc)`  — satır 122  — Klasör özetini yaz → (yeni_mi, onceki_karakter).

Çakışmada üstüne yazılır; eski kayıt SİLİNMEZ. "Bu klasör sayıldı
mı" sorusu her zaman doğru yanıtlanır (sayaç artar).

`durum`: "ok" | "erisilemez". Erişilemeyen dizin de kaydedilir ama
"boş" gibi görünmez — 0 dosya ile "okunamadı" farklı bilgidir.

`goc=True` → GÖÇ modu: var olan satıra DOKUNMAZ (DO NOTHING).
Göç JSONL'i her doğuşta yeniden okur; o satırlar daha önce
tarandıysa `son` "göç zamanı" diye sahte güncellenir ve `sayac`
şişerdi. `son` "diskte en son ne zaman görüldü" anlamını korumalı.
- `erisilemezler(self)`  — satır 164
- `supheli_temizle(self)`  — satır 168  — Çöp satırları sil → silinen sayı.

05.10'da `find`'in stderr'i stdout'a karışıp
"find: '/root': Permission denied" gibi satırlar klasör olarak
kaydedilmişti (27 satır). Bunlar yol bile değil; her doğuşta
temizlenir. Dışarıdan yazma yapılmaz (çalışan organizmanın WAL'ı
bozulur) — işi YASAMANIN KENDİSİ yapar.
- `dosya_yaz(self, kayitlar, goc)`  — satır 188  — (yol, boyut[, mtime, mod]) listesi → yeni dosya sayısı.

`mod` verilirse yürütülebilirlik (x) ve shebang kaydedilir; böylece
"bu dosya çalıştırılabilir mi?" sorusu katalogdan yanıtlanır.

`goc=True` → var olan satıra dokunulmaz (`son`/`sayac` sahte
güncellenmez). Göç JSONL'i her doğuşta yeniden okur; aksi halde
tüm katalogun `son` değeri "göç zamanı" olurdu ve alan artık
"diskte en son ne zaman görüldü" anlamına gelmezdi.
- `_yurutulebilir(yol, boyut, mod)`  — satır 242  — (x, shebang) — mod bitleri ve ilk satır.

Shebang sadece yürütülebilir ve küçük dosyalarda okunur (I/O
maliyeti sınırlı kalsın diye).
- `yapilanlar(self)`  — satır 269  — Envanterlenmiş klasör yolları (kalıcı hafıza).
- `klasor_sayisi(self)`  — satır 273
- `dosya_sayisi(self)`  — satır 276
- `rastgele_calistirilabilir(self)`  — satır 279  — x=1 olan rastgele bir dosya → (yol, ad).

"nedir?" egzersizi bununla çalışır: organizma çalıştırılabilir bir
aday seçer, kendi beyinine sorar, bilemezse GERÇEK dpkg'ye danışır.
- `adlar(self, sinir)`  — satır 290  — Dosya adları (konum egzersizi bununla çalışır).
- `dosya_satirlari(self, sinir)`  — satır 297  — Eğitim için satırlar: (yol, ad, uzanti, boyut).
- `yurutulebilirler(self, sinir)`  — satır 304  — Çalıştırılabilir dosyalar: (yol, shebang) — Faz 3'ün hammaddesi.
- `yurutulebilir_sayisi(self)`  — satır 310
- `rastgele_klasor(self, haric)`  — satır 314  — Rastgele bir envanterlenmiş klasör (tazeleme için).
- `istatistik(self)`  — satır 325
- `ice_aktar(self, envanter_yolu, dosyalar_yolu)`  — satır 349  — Eski JSONL dosyalarını içe al (bir kerelik göç, tekrar çalışsa
da zararsız: PRIMARY KEY aynı satırı iki kez almaz).
- `jsonl_aktar(self, envanter_yolu, dosyalar_yolu)`  — satır 386  — SQLite → JSONL dışa aktarım (denetim/okunabilirlik için).

Yazma iki aşamalı: geçici dosya → os.replace. Yarım kalan aktarım
asla okunabilir bir katalog haline gelmez.

---

## `komut_tara.py`

*Bu dosyada en üst seviyede `def` veya `class` tanımı bulunamadı.*

---

## `kontrol_katalog.py`

### Fonksiyonlar (`def`)

- `yari(n)`  — satır 28
- `surec(kok_tam)`  — satır 33  
    Açıklama: Çalışan organizma var mı? → (pid, cpu_sn, cwd_dogrulanabilir)

pgrep'e güvenilmez: süreç `python main.py` olarak da
başlatılabiliyor (python3 değil) ve kalıp tutmuyordu — "yok" dedi,
hâlâ çalışıyordu. Bu yüzden /proc taranır: cmdline'da main.py olan
süreçler.

cwd_çakışması yoksa süreç elenir. cwd OKUNAMAZSA (root süreci)
süreç yine döner ama `cwd_dogrulanabilir=None` olur: doğrulanamayan
süreç "yok" sayılmaz.
- `_surec_bul(kok_tam)`  — satır 48
- `db_oku()`  — satır 91
- `journal_ozet(pencere_sn)`  — satır 140  
    Açıklama: Son N saniyede: eylem karışımı ve tezgâh sağlığı.
- `main()`  — satır 183

---

## `kullan.py`

### Fonksiyonlar (`def`)

- `ozet(cikti, n)`  — satır 132  
    Açıklama: Çıktının ilk anlamlı satırı (gözlem kısaltması).
- `_surec_say(ad)`  — satır 141  
    Açıklama: Bağımsız öğretmen: /proc'ta comm == ad kaç süreç? (ps DEĞİL.)
- `_dizin_say(dizin)`  — satır 160  
    Açıklama: Bağımsız öğretmen: dosya sayısı — find -P ile AYNI tanımla.

Sembolik bağlantılar sayılmaz ve takip edilmez (find `-type f` gibi);
aksi halde find çıktısıyla doğrulayıcı asla eşleşmez.

### Sınıflar / İşlemler (`class`)

#### `Kullan`  — satır 179  
    Açıklama: Komut kullanımı öğretmeni: hedef kurar, çıktıyı yargılar.

- `__init__(self, cfg, root)`  — satır 182
- `birak(self)`  — satır 216  — İnkâr hakkı (Aşama 4): aktif hedefi bedelsiz terk et.

Ceza/ödül burada DEĞİL beynde verilir (veto ödülü: erken bırakma
−1, geç bırakma +1 → beyin "ne zaman hayır diyeceğini" öğrenir).
Deneme sayacı da sıfırlanır ki yeni hedef temiz başlasın; zincir
tamponu (ara) da bırakılır — yarım iş taşınmaz.
- `don(self)`  — satır 232  — Periyodik bakım: hedefi tazele.
- `_hedef_kur(self)`  — satır 242
- `_dosya_listesi(self)`  — satır 276
- `_h_dosya_bul(self)`  — satır 299
- `_h_paket_sor(self)`  — satır 312
- `_h_dizin_liste(self)`  — satır 332
- `_h_dosya_oku(self)`  — satır 349
- `_h_metin_ara(self)`  — satır 406
- `eylemler(self)`  — satır 430  — Beynin seçebileceği eylem ailesi.

Maske artık zincire özel değil: her hedef tipi için YALNIZCA
haritada (gerçek argv’si olan) komutlar sunulur. Harita dışı bir
seçim no-op ("true") çalıştırıp deneme bütçesini israf ederdi —
690 bin canlı denemede ölü alan %40 çıktı (ör. PAKET_SOR’da 13
ölü komut × ~2000 deneme, tek yaşayan dpkg). Maske tek kaynaktan
(_harita) türetilir: harita genişleyince eylem uzayı da genişler.
- `_canli_adlar(self)`  — satır 449  — Canlı kullanıcı süreci adları (/proc; cmdline boş çekirdek
parçaları hariç — surec organıyla aynı dışlama).
- `_h_surec_sor(self)`  — satır 472  — 'X süreci çalışıyor mu?' — doğrulayıcı: /proc'un kendisi.
- `_h_surec_say(self)`  — satır 480  — ZİNCİR hedefi (Aşama 2): 'X kaç süreç?' — tek komut
sayıyı veremez: ara adım (ps/pgrep → pid listesi) + son adım
(wc, stdin = ara bellek). Doğrulayıcı bağımsız /proc sayımı.
- `_h_dosya_say(self)`  — satır 492  — ZİNCİR hedefi (Aşama 2): 'Şu dizinde kaç dosya?' —
doğrulayıcı bağımsız os.walk. Küçük dizin seçilir ki find
çıktısı ara belleğe (ARA_TAVAN) sığsın.
- `_doc_dizini(self)`  — satır 505  — /usr/share/doc alt dizinleri (tek yükleme, GUVENLI_KOKLER'de).
- `_h_dosya_olc(self)`  — satır 520  — ’Bu dosya kaç byte?’ — doğrulayıcı: bağımsız getsize.
stat / wc -c / du -sb üç farklı yol, tek gerçek (zemin gerçeği).
- `_h_sistem_sor(self)`  — satır 538  — 'Sistemin cpu/bellek/çekirdek durumu ne?' — üç konu, üç kapı.

Doğrulayıcı bağımsız kaynak (judge-time): os.cpu_count /
/proc/meminfo / platform.release — komut çıktısı değil kernel gerçeği.
- `_h_dosya_ozet(self)`  — satır 565  — 'Bu dosyanın özeti ne?' — md5sum / sha256sum (bütünlük).

Doğrulayıcı: hashlib dosyanın KENDİSİNİ judge-time okur.
Boyut sınırı: 5MB — hash 8s zaman aşımına sığmalı.
- `_h_dosya_ham(self)`  — satır 584  — 'İlk baytlar ne?' — hexdump / xxd (ham içerik okuma).

Doğrulayıcı: dosyanın ilk 8 baytı judge-time okunur; hex
gösterimi (hexdump '7f 45..' / xxd '7F45 4C46') çıktıda
bulunmalı — boşluk/atlamalar temizlenerek karşılaştırılır.
- `_paket_listesi(self)`  — satır 605  — Kurulu paket adları (dpkg-query; önbellekli; yoksa boş liste).
- `_h_paket_versiyon(self)`  — satır 624  — ’Kurulu X paketinin sürümü nedir?’ — doğrulayıcı: dpkg-query
kendisi. dpkg -s ile apt-cache policy aynı gerçeği söyler →
iki kapılı gerçek seçim (eski PAKET_SOR’da tek kapı vardı).
- `_servis_listesi(self)`  — satır 644  — Kurulu servis birimleri (kısa önbellekli; yoksa boş liste).
- `_servis_durumu(self, birim)`  — satır 669  — Zemin gerçeği: systemctl is-active (öğretmenin ta kendisi).
- `_h_servis_sor(self)`  — satır 681  — 'X servisi aktif mi?' — doğrulayıcı: systemctl is-active.
- `_disk_listesi(self)`  — satır 693  — Gerçek disk bağlama noktaları (/dev/sd|nvme|vd|mmcblk|mapper).
- `_h_disk_sor(self)`  — satır 711  — 'X diskinde durum ne?' — doğrulayıcı: df'nin kendi çıktısı.
- `_arayuz_listesi(self)`  — satır 719  — Ağ arayüzleri (ip -o link; başaramazsa salt geri dönüş).
- `_h_ag_sor(self)`  — satır 735  — 'X arayüzü ne durumda?' — doğrulayıcı: ip'nin kendi çıktısı.
- `_kapsam_damgasi(self)`  — satır 743  — Kapsam dosyası imzası: (mtime_ns, boyut); dosya yoksa None.
- `_kapsam_yukle(self)`  — satır 751  — ag_kapsam.json oku — VARSAYILAN RED (deny-by-default).

Dosya yok / bozuk / acik:false / izin_aglari boş → ağ taraması
kapalıdır: AG_TARA hedefi hiç üretilmez, kapı hiç açılmaz.
Yetki SADECE bu dosyadan gelir — başka kaynak yok, pazarlık yok.
- `_ag_kapali(self)`  — satır 800  — Kapsam reddediyorsa AG_TARA ne üretilir ne de kazanır.

Dosya canlı izlenir: idari red (acik:false / dosya silme) anında
geçerlidir — jeneratör, kapı ve yargı kilitlenir, restart gerekmez.
- `_ag_ip_izinli(self, ip)`  — satır 812  — ip allowlist'te mi? (hataya kapalı: ne pazarlık ne istisna.)
- `_ag_adaylar(self)`  — satır 825  — Kapsamdaki tarama adayları.

Döngü arayüzü ARP kanıtı üretemez → 127/8'de tek aday 127.0.0.1
(16M host'luk sweep anlamsız). 1024'ten büyük ağlar kapsamda
kalabilir ama tarama adayı yapılmaz — sweep bütçesi taşmaz.
- `_ag_komsu_satiri(self, ip)`  — satır 842  — Kernel ARP komşu satırı (kernel'den, komut kapılarından bağımsız).
- `_ag_gercek(self, ip)`  — satır 855  — Zemin gerçeği (nötr öğretmen): kapı komutlarından BAĞIMSIZ.

LAN: kernel ARP komşu tablosu — lladdr + REACHABLE/STALE/DELAY/
PROBE → canlı, INCOMPLETE/FAILED → ölü. Döngü: arayüzün kendi
durumu (ARP kanıtı yok). Kanıt yok → None: yargı False verir,
yani emin olunmadan kazanç yok. _dogrula JUDGE-TIME çağırır:
nmap/ping zaten ARP tablosunu tazeler → iddiaları anında teyit
edilir (hücum → kanıt döngüsü; ödül yine uydurulmaz).
- `_ben_tarama_acik(self)`  — satır 889  — BENI_TARA kapısı: master anahtar (acik) + bayrak (ben_tarama).

VARSAYILAN RED: ben_tarama yoksa/false ise kendini tarama hiç
üretilmez. Ayrıca 127.0.0.1 allowlist teyidi _harita ve
_h_beni_tara'da ayrı ayrı yapılır (savunma derinliği).
- `_ben_dinleme(self)`  — satır 903  — Kernel socket zemin gerçeği: dinleyen TCP port kümesi | None.

/proc/net/tcp + tcp6, durum 0A = LISTEN — kapı komutlarından
bağımsız (nmap/ss/curl ne derse desin GERÇEK budur; AG'deki
ARP doktriniyle aynı). Hiçbir dosya okunamazsa None: yargı
asla True veremez — kanıtsız kazanç yok.
- `_ben_http_port(self)`  — satır 929  — curl kapısının portu — iddia değil idari bilgi (ag_kapsam).
- `_ss_dinleme(cikti)`  — satır 937  — ss çıktısından dinleyen port kümesi (yerel adres:port).

'state listening' filtresiyle satır = iddia; port alınamazsa
satır yok sayılır (boş küme eşitliği yakalar).
- `_h_ag_tara(self)`  — satır 952  — AG_TARA — kapsam içindeki bir host ('bu host canlı mı?').

Aday seçimi: allowlist ∩ soğuma yok ∩ AZ DENENMİŞ (count-based
keşif — elle yazılmış dal yok). komsu_var: 'ip neigh' kapısı
yalnızca komşu satırı VARKEN açılır (DOSYA_OKU örnek kapısı
gibi) — kanıtsız kapı hiç sorulmaz. Gerçek gerçeklik hedefe
gömülmez; _dogrula anında kernel'den okur.
- `_h_beni_tara(self)`  — satır 985  — BENI_TARA — kendini tarama (Katman 1: port/servis keşfi).

Hedef hep 127.0.0.1; KEŞİF alanı port aralığıdır: least-tried +
soğuma ile aralıklar sırayla gezilir — aynı sayım mekanizması,
elle yazılmış dal yok. Zemin gerçeği _ben_dinleme() (/proc);
kapılar nmap -sV / ss / curl. ben_tarama kapalıysa hiç üretilmez.
- `uygula(self, eylem)`  — satır 1018
- `_harita(self, h)`  — satır 1111  — Hedef tipi → gerçek argv haritası (tek doğruluk kaynağı).

eylemler() maskeyi bu haritadan, uygula() argv’yi buradan alır.
Ölçüm (2026-10-14, 690 bin canlı deneme) sonrası ölü girişler
silindi: haritada yalnızca doğrulanabilir komutlar var (ör.
DISK_SOR’da df dışında 13 komut hiç kazanamadı → sunulmuyor).
- `_argv_kur(self, komut)`  — satır 1298
- `_dogrula(self, cikti, argv)`  — satır 1304  — Çıktı hedefi karşılıyor mu? (kural tablosu yok: dosya sistemi
ve dpkg'nin kendi çıktısı yargılar.)
- `_kos(self, argv, sure)`  — satır 1604
- `rapor(self)`  — satır 1629

---

## `kutu_uretici.py`

### Fonksiyonlar (`def`)

- `load_cfg(path)`  — satır 20
- `features(name, cfg)`  — satır 27
- `_eslesir(feat, kural)`  — satır 40
- `odul_hesapla(name, cfg)`  — satır 57  
    Açıklama: İsim → ödül: sıralı kurallar, ilk eşleşen; yoksa varsayılan.
- `derinlik_bul(rel, cfg)`  — satır 67  
    Açıklama: 'kutular/k02/ax/dosya_emr' → derinlik 2 (klasör katmanı).
- `kutu_tam_deger(rel, cfg)`  — satır 75  
    Açıklama: Kutunun GERÇEK değeri (laboratuvar hesabı — organizma görmez):
isim kuralı ödülü × (1 + derinlik).
- `_govde(rng, uzunluk, tip)`  — satır 84
- `icerik_yaz(path, odul, rng)`  — satır 89
- `kutu_uret(cfg, sessiz)`  — satır 99  
    Açıklama: 20 kutu (dosya) — rastgele derinliklerde klasörlerde.

Değer = isim kuralı ödülü × (1 + derinlik): derin klasör = büyük ödül.
Eski 5000'lik tek-kutu dünyası da temizlenir.

---

## `main.py`

### Fonksiyonlar (`def`)

- `load_config(path)`  — satır 37
- `uzuv_riskli(yol, simdi)`  — satır 52  
    Açıklama: FAZ 2 gözlemi: taze uzuv_durum.json 'tehlikeli' ≥ 1 ise True.

ag 3 dakikada bir yazar; 15 dakikadan bayat dosya sayılmaz —
ag durursa eski risk tokenı beyini yanlış bağlama sokmasın.
Hiç dosya yoksa False (Faz 2 henüz eğitilmedi → yaşam sürer).
- `main()`  — satır 70

---

## `olcum.py`

### Fonksiyonlar (`def`)

- `olcum(path)`  — satır 9

---

## `olcum_asama1.py`

*Bu dosyada en üst seviyede `def` veya `class` tanımı bulunamadı.*

---

## `olcum_zincir.py`

### Fonksiyonlar (`def`)

- `_jurnal_dosyalari()`  — satır 75  
    Açıklama: Canlı jurnal + arsiv jurnalleri (zaman sirasinda).
- `_kullan_kayitlari(son)`  — satır 82  
    Açıklama: kullan kayitlarini (zaman sirasinda) oku. son: son N kayit.
- `_oturumlar(kayitlar)`  — satır 106  
    Açıklama: Zincir oturumlarini yeniden kur: deneme==1 yeni oturum baslatir.

Donus: [(tip, [(deneme, komut_adi, dogru, odul), ...]), ...]
- `olcum(kayitlar)`  — satır 127  
    Açıklama: Tum zincir kayitlarindan olcum sozlugu uret.
- `rapor_bas(s, kaynak)`  — satır 173  
    Açıklama: Olçum sozlugunu okunabilir rapor olarak bas.
- `_taban_pencere(taban)`  — satır 196  
    Açıklama: Taban sozlugunde karsilastirma penceresi (kayit sayisi) varsa dondur.

--taban ile yazilan olcum sozlugunde "toplam_kayit" pencereyi tasir;
eski sabit TABAN blogunda "kayit_sayisi" vardir (ikisini de kabul et).
- `_taban_tip(taban, t)`  — satır 211  
    Açıklama: Taban tip metriklerini al — iki kabul et.

--taban dosyasi olcum sozlugudur, metrikler "tip" altindadir; eski
sabit TABAN blogu duzdur ("DOSYA_SAY" dogrudan ustte). Eski kod yalnizca
duz formu aradigi icin dosya tabaninda TUM tip karsilastirmalari
sessizce atlanir, arac her kosulda "belirgin fark yok" basardi
(2026-10-18: DOSYA_SAY basarisi tabana gore dustu, denetim gormedi).
- `taban_karsilastir(s, taban)`  — satır 226  
    Açıklama: Mevcut olcum ile tabani karsilastir, delta bas.

Donus: belirgin fark (|delta| > 0.02) var mi — test/regresyon icin.
- `main()`  — satır 271

---

## `olum.py`

### Fonksiyonlar (`def`)

- `zincir(ad)`  — satır 252  
    Açıklama: Ölüm nedeninin nedensellik zinciri: [öncül1, ..., ölüm].

Bağlantı burası: bir ölümü yalnız başına değil, onu getiren ara
durumlarla birlikte verir (CPU_THROTTLE → ZAMAN_ASIMI gibi). Zincirin
kontrol edilebilir bir düğümden geçmesi, kaçınma hamlesinin oradan
yapılacağını gösterir.
- `onlem(ad)`  — satır 275  
    Açıklama: Ölümün önlemi (varsa): organizmanın "buna bağımlı olmayayım" hamlesi.
- `mekanizma(ad)`  — satır 280  
    Açıklama: Ölümün fizik/yazılım mekanizması (nasıl öldürdüğü).
- `kategori_of(ad)`  — satır 285
- `strateji_of(ad)`  — satır 289  
    Açıklama: Nedenin stratejisi (katalog etiketi). Yoksa kategoriden türetilir.
- `strateji_kategori(kategori)`  — satır 297  
    Açıklama: Kategori türüne göre strateji (doktrin haritası).
- `ozellikler(gozlem)`  — satır 302  
    Açıklama: Gözlemlenebilir sinyaller → özellik listesi (risk.py sözleşmesi).

`gozlem` ölüm anında GÖRÜLEN sözlük: sinyal/kaynak/kim/siddet/belirti/
onbelirti. Eksik alanlar atlanır (gerçek teşhiste log her sinyali vermez).
`iz` BİLEREK alınmaz — her neden için benzersizdir, ezber crutch'u olur.
- `gozlem_uret(ad, rng, kayip)`  — satır 317  
    Açıklama: Katalog kaydından GÜRÜLTÜLÜ gözlem üret (eğitim verisi).

Gerçek teşhis gibi: her sinyal her zaman görülmez — `kayip` olasılıkla
bir gözlemlenebilir alan düşer. Böylece model eksik kanıtla da sebebi
çıkarmayı öğrenir (sadece ezber değil).
- `math_log(x)`  — satır 419

### Sınıflar / İşlemler (`class`)

#### `Olum`  — satır 334  
    Açıklama: Özellik → kategori frekansı modeli (Laplace). risk.py ile aynı aile.

Tek öğrenilen başlık KATEGORİDİR (4 sınıf): bu ölüm fiziki / yazilimsal /
donanimsal / dis. STRATEJI (kacin/azalt/sinirla) bağımsız olarak
öğrenilmez — tanınan kategoriden doktrin haritasıyla TÜRETİLİR
(strateji_kategori). Çünkü önlenebilirlik ölüm sinyalinin bir özelliği
değil, sebebin türüne bağlı bir karardır.

- `__init__(self, kategoriler, agirlik, oncelik)`  — satır 344
- `ogren(self, feats, kategori)`  — satır 352
- `_log(self, feats, kategori)`  — satır 358
- `kategori_skor(self, feats)`  — satır 369
- `kategori_tahmin(self, feats)`  — satır 372
- `tani(self, gozlem)`  — satır 376  — Ölüm gözlemi → (kategori, strateji, kategori-skorları).

Organizmanın asıl kullanacağı kapı: sinyallerden sebep + o sebebe
göre strateji. Strateji kategoriden türetilir (strateji_kategori);
zincir(ad) ile kontrol edilebilir öncül varsa kaçınma oradan yapılır.
- `save(self, path)`  — satır 389
- `load(self, path)`  — satır 400

---

## `paket.py`

### Fonksiyonlar (`def`)

- `_alanli(yol)`  — satır 33
- `durum_oku(yol)`  — satır 37  
    Açıklama: dpkg status → {paket: {bolum, aciklama, oncelik}}.
- `komut_dosyalari(kok)`  — satır 67  
    Açıklama: Komut alanındaki dosyalar → [(dosya_yolu, paket)] (.list).
- `komut_adi(yol)`  — satır 87
- `ozellikler(ad)`  — satır 91  
    Açıklama: Komut adı → özellikler (dizin/risk ailesi + kelime parçalama).

### Sınıflar / İşlemler (`class`)

#### `Paket`  — satır 107  
    Açıklama: Dosya adı → paket frekans modeli (Laplace; risk/dizin ailesi).

- `__init__(self, agirlik, oncelik)`  — satır 110
- `ogren(self, feats, paket)`  — satır 120
- `_log(self, feats, paket)`  — satır 126
- `skorlar(self, feats)`  — satır 138
- `tahmin(self, feats)`  — satır 141
- `sirala(self, feats, n)`  — satır 147
- `bilgi_ekle(self, ad, paket, bolum, aciklama)`  — satır 154
- `nedir(self, ad)`  — satır 159  — Komut adı → (kaynak, bilgi). Kaynak: 'kesin' | 'tahmin' | None.

Önce kesin dpkg haritası; yoksa öğrenilen modelin tahmini —
kaynak açıkça 'tahmin' (karıştırma yok, dürüstlük şart).
- `save(self, path)`  — satır 178
- `load(self, path)`  — satır 191

---

## `risk.py`

### Fonksiyonlar (`def`)

- `gercek_sinif(yol, x, dunya_koku)`  — satır 38  
    Açıklama: Kurallardan türetilen sınıf (eğitim etiketi).
- `norm(yol)`  — satır 53
- `ozellikler(yol, x, shebang)`  — satır 62  
    Açıklama: Dosya → özellik listesi (dizin modeliyle aynı sözleşme).
- `math_log(x)`  — satır 163

### Sınıflar / İşlemler (`class`)

#### `Risk`  — satır 86  
    Açıklama: Özellik → sınıf frekansı modeli (Laplace yumuşatma).

- `__init__(self, siniflar, agirlik, oncelik)`  — satır 89
- `ogren(self, feats, sinif)`  — satır 97
- `_log(self, feats, sinif)`  — satır 103
- `skorlar(self, feats)`  — satır 114
- `tahmin(self, feats)`  — satır 117
- `sirala(self, feats)`  — satır 121
- `karar(self, yol, x, shebang)`  — satır 125  — Tahmin + izin kararı → (sinif, izin_bool, puan).
- `save(self, path)`  — satır 133
- `load(self, path)`  — satır 144

---

## `surec.py`

### Sınıflar / İşlemler (`class`)

#### `Surec`  — satır 21

- `__init__(self, cfg)`  — satır 22
- `tara(self)`  — satır 34  — /proc'dan tarama: kullanıcı süreçleri (comm + cmdline).

Çekirdek iş parçacıkları (cmdline boş, örn. kworker/*) izlenmez:
dinamiktirler, "kendim" diye sahte eksik alarmları üretirler.
- `ornekle(self)`  — satır 60  — Bir örnek al, frekansları güncelle, anomaliyi bul.
- `isle(self, gorunen)`  — satır 68  — (test edilebilir çekirdek) verilen kümeyle öğren + anomali bul.
- `save(self)`  — satır 103
- `load(self)`  — satır 113

---

## `talep.py`

### Fonksiyonlar (`def`)

- `_which(komut)`  — satır 61
- `_dpkg_kurulu(paket)`  — satır 65
- `_apt_aday(paket)`  — satır 74
- `tara()`  — satır 84
- `kaydet(veri)`  — satır 121  
    Açıklama: zeka/talep.json (atomik).
- `raporla(veri)`  — satır 130  
    Açıklama: talepler.md — insanın okuyup onaylayacağı rapor.
- `main()`  — satır 204

---

## `uyku.py`

### Fonksiyonlar (`def`)

- `_ad_duzelt(ad)`  — satır 84
- `_rapor_satiri(cikti)`  — satır 88  
    Açıklama: egit_* stdout'undan tek dogruluk satiri (Z2 - olcum kor noktasi):
uyku egitiminin METRIGI journal'a girer; kod/sure degil, dogruluk
tarihsel olur (dogru X/Y | top-1/top-3 | MAE). Bulunamazsa None.
Mock/test stdout'u (str disi) guvenle ele alinir.

### Sınıflar / İşlemler (`class`)

#### `Uyku`  — satır 107

- `__init__(self, cfg)`  — satır 108
- `_damga(self, ad)`  — satır 124  — Kaynak degisiklik damgasi: veri kaynagi ne zaman oynadi.
- `_veri_sayisi(ad)`  — satır 149  — Deneyim birikimi (artis = ogrenme).

guvenlik/uzuv: satir sayisi. hatira: jurnal BAYT boyu (stat,
ucuz; 20MB'lik dosyayi her kontrolde satir satir saymaz).
- `karar(self, now, zorla)`  — satır 172  — Siradaki uyku - en acil olan. None = su an gerekmez.
- `uyu(self, karar, beyn)`  — satır 216  — Tek uykuda tek egitim (senkron; tikler durur - nefes tutma).

hatira ve konsolide hatlari surec-icidir: beyin bellekte yasar;
hatira journal learn kayitlarini (stim, action, R) guncel
agirliklarla yeniden oynar (Asama 4 - deneyim tekrari), konsolide
ise esik altindaki zayif baglantilari budar (Asama 5). Diger
hatlar subprocess'tir.

Donus: {"ad","kod","sure"[, "ornek"]}. kod==0 basari; -1 hata/
zaman asimi; -2 atlandi (hatira/konsolide icin beyin verilmedi).
Basari disinda son basarili durum KORUNUR ve geri cekilme baslar.
- `save(self)`  — satır 287
- `load(self)`  — satır 294

---

## `uzuv.py`

### Fonksiyonlar (`def`)

- `ozellikler(k)`  — satır 39  
    Açıklama: Süreç kaydı → özellik listesi (risk.py ile aynı sözleşme).
- `defter_oku(yol)`  — satır 60  
    Açıklama: İnsan etiket defteri → {(comm, exe): sinif}; exe '*' = tümü.
- `etiket(kayit, defter)`  — satır 81  
    Açıklama: İnsan defteri > zayıf oto-etiket (öğretmen hiyerarşisi).
- `son_cekim(yol)`  — satır 108  
    Açıklama: Veri dosyasının son çekimindeki (sid) satırlar.

### Sınıflar / İşlemler (`class`)

#### `Uzuv`  — satır 92  
    Açıklama: Risk ailesinin uzuv sürümü — tek fark: uzuv.json kalıcılığı.

- `__init__(self, siniflar, agirlik, oncelik)`  — satır 95
- `save(self, path)`  — satır 99
- `load(self, path)`  — satır 103

---

## `zeka.py`

### Fonksiyonlar (`def`)

- `yol(ad)`  — satır 22  
    Açıklama: Model dosyası yolu: zeka/ varsa orası, yoksa eski kök konumu.
- `kayit(ad)`  — satır 33  
    Açıklama: Kayıt hedefi HEP zeka/ (yoksa oluştur).
- `goc(yalnizca_yeni)`  — satır 39  
    Açıklama: Doğuşta çağrılır: eski kök konumdaki taze dosyaları zeka/'ya al.

Geçiş dönemi için: taşınmadan önce doğan canlı süreçler kodun eski
sürümüyle çalışır ve kök dizine yazar (brain.json, damak.json,
guvenlik_veri.jsonl). Göç yoksa bu yazmalar sessizce kaybolur.

- json modelleri: kökteki dosya zeka/'dakinden TAZEYSE onu alır
  (yalnizca_yeni=False → her koşulda alır, yedekleyerek)
- jsonl (guvenlik_veri): kayıp satırlar eklenir (yinelenen satır yok)
Döner: taşınan dosya adları listesi.

---

## Özet

- Dosya sayısı: 41
- Toplam fonksiyon (`def`): 173
- Toplam sınıf (`class`): 19
