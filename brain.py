"""CORE brain — öğrenen beyin.

Hebbian/koşullanma tarzı basit bir öğrenme: her (uyaran, eylem) çiftinin
bağlantısı, eylemin enerjiye yansıyan sonucuna göre güçlenir ya da zayıflar.
"Şeker kokusu + bu hareket = doydum" → bağlantı sertleşir.

Öğrenme kuralı: hata-güdümlü delta (damak/guvenlik ile aynı aile) +
Faz 1 genişlemeleri:
  · S2 bağlam çaprazları: _bilesen() kolon-jetonu çiftlerini ("×" ile)
    ekler — etkileşim koda yazılmadan öğrenilir. Kaydedilen günlük
    stim'ine EKLENMEZ (eski kayıtlarla uyumlu); pay 75/25 bütçeyle
    dağıtılır ki tekil jetonların öğrenme hızı düşmesin.
  · S4 ince girdi: L/M/H-A/O/T kovalarına ek olarak onluk e:/h: kovaları.
  · S5 hijyen: dokunulan bağlantı sönümlenir ve ±AGIRLIK_TAVAN'a kırpılır
    (ör. 12.7'ye şişen eat ağırlığı); hatıra son pencere + |R|>=3 şok
    olaylarını yeniden oynatır.
  · (S1 geriye-akış izi DENENDİ ve ablasyonla ELENDİ — aynı veri
    görüntüsünde iki hedefte de kayıp: anlık R'de A r 0.900→0.698,
    getiri-to-go'da 0.435→0.376; karıştırma kontrolü üstünlüğü
    P(C≥A)=0.048→0.286'ya düştü. Geriye akış bu veride yalnız gürültü
    ekledi; ertelenmiş krediyi gıdadaki credit() taşımaya devam eder.)
Beyin bedenin bir parçasıdır: 10 tikte bir ve kapanışta atomik olarak
brain.json'a yazılır (tmp + rename); doğuşta oradan yüklenir.
"""
import json
import os
import random
from collections import deque
from pathlib import Path

ACTIONS = ("wander", "eat", "console", "sense_self", "nest", "rest")

# eski (iz kuralı) brain.json -> delta kuralı göçü: 1 / (1.5 * 5 özellik)
LEGACY_OLCEK = 1.0 / 7.5

# ---------- Faz 1 ayarları (S5) ----------
AGIRLIK_TAVAN = 15.0    # ağırlık kırpma sınırı (şişme koruması)

# Bağlam ÇAPRAZI ayracı: "gorev:X × son:hata" gibi birleşik özellikler.
# Çaprazlar kombinatoryal olarak üretilir (N jeton → N(N-1)/2 çift), bu
# yüzden otomatik KANIT toplarlar ve kanıt tablosunu gürültüyle doldurur.
CAPRAZ_AYRAC = "×"


class Brain:
    """Özellik-bazlı Hebbian beyin.

    Uyaran '|' ile parçalanır; her (özellik, eylem) bağlantısı ayrı
    öğrenir, eylem skoru = özelliklerin TOPLAMI. Böylece "açlık=A → eat"
    bir kez öğrenilir, her konumda geçerlidir (genelleme). Durum-tek-
    ağırlık tablosu yerine ~165 bağlantı yeter — hepsi sık görülür.
    """

    # Doğuştan refleksler: canlı aç ve acılı doğar; öğrenme bunları
    # zamanla ezip yenileyebilir (kayıt varsa kaydedilen değer kazanır).
    # Soğuk doğum lotosuna karşı yaşama yanlısı yaratılış.
    INSTINCTS = {("L", "eat"): 1.5,     # acı → derhal ye
                 ("A", "eat"): 0.8,     # açlık → ye
                 ("O", "eat"): 0.5,
                 ("A", "wander"): 0.2}  # açlık → biraz daha fazla ara

    # Aşama 4 — aile jetonu: görev tiplerini öğrenme paylaşımı için gruplar.
    # SAY ailesi: DOSYA_SAY ve SUREC_SAY aynı zincir desenini paylaşır
    # (veri-üreten ilk adım → wc). Aile jetonu, wc-ilk kaçınmasının bir
    # görevden diğerine aktarılmasını sağlar (gorev:<tip> tekil kalır —
    # geriye uyumluluk). Diğer ailler: aynı komut öncüllünü paylaşan görevler.
    AILE = {
        "DOSYA_SAY": "SAY", "SUREC_SAY": "SAY",
        "DOSYA_BUL": "DOSYA", "DOSYA_OKU": "DOSYA",
        "DOSYA_OLC": "DOSYA", "METIN_ARA": "DOSYA",
        "DOSYA_OZET": "DOSYA", "DOSYA_HAM": "DOSYA",
        "DIZIN_LISTE": "DIZIN",
        "SUREC_SOR": "SUREC",
        "PAKET_SOR": "PAKET", "PAKET_VERSIYON": "PAKET",
        "AG_SOR": "AG", "AG_TARA": "AG", "BENI_TARA": "AG",
        "DISK_SOR": "SISTEM", "SERVIS_SOR": "SISTEM",
        "SISTEM_SOR": "SISTEM",
    }

    def __init__(self, seed=None, lr=0.12, momentum=0.92, epsilon=0.35):
        # Yerel RNG: global random.seed() diğer modülleri bozuyordu
        # (ust_beyn.py'deki aynı karar — "global np.random.seed() diğer
        # modülleri bozuyordu"). İki Brain örneği artık birbirinden
        # BAĞIMSIZ akış üretir: aynı seed verilse bile biri diğerini
        # etkilemez. KÖK NEDEN: global tohum, her Brain kurulduğunda
        # tüm modüllerin rastgelelik zincirini yeniden başlatıyordu —
        # bu yüzden "aynı seed => aynı karar dizisi" tutmuyordu.
        self.rng = random.Random(seed)
        self.lr_base = lr
        self.lr = lr
        self.momentum = momentum
        self.epsilon_base = epsilon
        self.epsilon = epsilon
        # Meta-öğrenme çarpanları (meta_ogrenme.py tarafından yazılır,
        # update_dynamic_params ile temel lr/ε üzerine çarpılır)
        self.meta_lr_carpan = 1.0
        self.meta_eps_carpan = 1.0
        self.w = dict(self.INSTINCTS)  # (özellik, eylem) -> bağlantı gücü
        # son decide() keşifle mi yoksa kestirimle mi yapıldı?
        # (ders defteri: yalnızca kestirim hatası gerçek bilgi boşluğudur)
        self.son_kesif = False
        # sıkılma (Aşama 4): main her tikte drives.sikilma'yı buraya taşır;
        # decide() keşif baskısını bundan alır
        self.sikilma = 0.0

        # Credit/decorrelation system: stores bonus for (stim, action) pairs
        self.credits = dict()  # (stim_tuple, action) -> accumulated bonus
        self.credit_max = 1.0
        self.credit_decay = 0.99  # fades each tick

        # Aşama 6 — keşif tabanı & tam havuz payı (canlı kör nokta çözümü):
        # eps marjla düşer ama asla EPS_TABAN'ın altına inmez (keşif hiç
        # tamamen kapanmaz). KESIF_TAM: keşfin bu oranı TAM havuzdan
        # (negatif skorlu eylemler dahil) seçilir — aksi halde bir kez
        # negatife çöken eylem (birikmiş deneme bedeli) keşif havuzuna
        # (score>=0 filtresi) giremez, yeniden denenemez ve skoru asla
        # düzelmez: kalıcı kör nokta. Ölçüm (2026-10-19): havuz {rest}'e
        # inince 5.5 saat sıfır görev denemesi.
        self.EPS_TABAN = 0.05
        self.KESIF_TAM = 0.25
        # ---------- Yeni: Episodik bellek (kısa vadeli hatıra) ----------
        # Son N (stim, action, reward) etkileşimi; decide'de benzer uyaran
        # için hızlı "hatırlama" boostu sağlar.
        self.episodic = deque(maxlen=64)
        # ---------- Yeni: Working memory (decay'li kısa bellek) ----------
        # Son M tikteki (stim, action) çiftleri; her tikte decay uygulanır.
        # Aynı stimuli tekrar eden eylemler için hafif teşvik.
        self.working_memory = {}  # (stim, action) -> strength
        self.working_decay = 0.95  # her tikte %5 zayıflar
        self.working_max = 32      # en çok 32 giriş tutulur
        # (özellik, eylem) çiftinin kullanım sayısı — alışkanlık/otomatikleştirme
        self.usage = {}
        # DONDURULMUŞ sayaçlar (KÖK NEDEN 3, 2026-10-22): usage sayacı
        # USAGE_DONDURMA'yı aşan girdilerin fazlası buraya taşınır.
        # Amaç: kanıt (usage>=2) SONSUZA DEK korunurken tablo şişmez.
        self.usage_tasma = {}
        # ---------- Yeni: Yapıslé plastisite (nöron büyüme/silme) ----------
        # Sık kullanılan (stim, action) çiftlerine göre sanal nöron ekleme
        self.neuron_id_counter = 0
        # Her sanal nöron: {(stim, action): weight}
        self.neurons = dict()  # neuron_id -> { (stim, action): weight }
        # Büyüme eşiği: usage'si bu seviyeye ulaştığında nöron açılır
        self.NEUROON_BUYUME_ESI = 50
        # Açılan nöronları koruma (tavanlamaya maruz kalmaz)
        self.korumali_neuronlar = set()
        # Maksimum nöron sayısı: bellek koruması
        self.MAX_NEUROON = 50
        # ---------- Yeni: Dinamik lr/epsilon ayarı ----------
        self.lr_min = 0.02
        self.lr_max = 0.25
        self.eps_min = 0.02
        self.eps_max = 0.60
        # ---------- Sağlık sinyali eğitimi (AraBeyn entegrasyonu) ----------
        # (durum_dict, puan, sinif_str) kayıtları; eşleşen durumdan
        # ortalama puan ve en sık sınıf hesaplanarak sağlık üret.
        self.saglik_egitim = []

    # ---------- Yeni: Dinamik hiperparametre ayarı ----------
    def update_dynamic_params(self, drives):
        """Enerji, acı ve sıkılmaya göre lr ve epsilon'ı dinamik ayarla.

        - Düşük enerji / acı (yaşama tehlikesi): epsilon düşer (daha az keşif,
          daha çok riflenen eylem), lr düşer (kararlı kal).
        - Yüksek enerji, düşük sıkılma: epsilon rises (daha çok keşfet).
        - Yüksek sıkılma: epsilon forced up (rutin kırılmalı).
        """
        # Enerji oranı: 0 (kritik) .. 1 (dolu)
        e_cap = max(1.0, float(getattr(drives, "energy_cap", 150)))
        e_ratio = max(0.0, min(1.0, float(getattr(drives, "energy", 50)) / e_cap))
        # Acı yoğunluğu 0..1 (Drives.pain).
        # Not: Drives.pain bir METODdur; ama bazı sürücülerde (test
        # sahteleri) düz sayı olabilir. İkisi de desteklenir — yoksa
        # düşük enerji yolunda TypeError patlar ve öğrenme durur.
        _pain = getattr(drives, "pain", 0.0)
        pain = float(_pain() if callable(_pain) else _pain)
        pain = max(0.0, min(1.0, pain))
        sik = max(0.0, min(1.0, float(getattr(drives, "sikilma", 0.0))))

        # lr: acıda düşük (kararlılık), iyi ortamda normal
        lr_target = self.lr_base * (0.5 + 0.5 * e_ratio) * (1.0 - 0.5 * pain)
        self.lr = max(self.lr_min, min(self.lr_max, lr_target))

        # epsilon: acıda çok düşük (hayatta kalma > keşif), sıkıldığında yüksel
        eps_target = self.epsilon_base * (1.0 + 0.5 * sik) * (1.0 - 0.7 * pain)
        self.epsilon = max(self.eps_min, min(self.eps_max, eps_target))
        self.lr = max(self.lr_min, min(self.lr_max, self.lr * getattr(self, "meta_lr_carpan", 1.0)))
        self.epsilon = max(self.eps_min, min(self.eps_max, self.epsilon * getattr(self, "meta_eps_carpan", 1.0)))
    # ---------- Yeni: Episodik bellek ----------
    def episodic_push(self, stim, action, reward):
        """Son etkileşimi episodik belleğe ekle (kısa vadeli hatıra)."""
        self.episodic.append((stim, action, float(reward)))

    def episodic_recall(self, stim):
        """Benzer yakın geçmişteki (stim, action) çiftini bul ve ação boost döndür.

        Benlik = paylaşılan '|' ayrıcılı jeton oranı. En benzer kayıtın
        eylemini döndürür; yoksa None.
        """
        if not self.episodic:
            return None
        cur = set(stim.split("|"))
        best = None
        best_sim = 0.0
        for (s, a, r) in self.episodic:
            prev = set(s.split("|"))
            if not cur or not prev:
                continue
            inter = len(cur & prev)
            uni = len(cur | prev)
            sim = inter / max(1, uni)
            # Sadece güçlü eşleşme ve pozitif/nötr ödül olanları dikkat al
            if sim > 0.6 and r > -2.0:
                if sim > best_sim:
                    best_sim = sim
                    best = a
        return best

    # Kullanım tablosunun tavanı. KÖK NEDEN: usage, karşılaşılan her
    # (özellik, eylem) çiftini SİNIRSIZ tutuyordu; özellik uzayı
    # büyüdükçe (e:0..e:31, h:1..h:31 ve bunların "×" çaprazları)
    # tablo sonsuza dek şişiyordu — stres ölçümünde 300 tikte 296
    # girdi. Sınır, işlem sayısıyla değil TABLO BOYUTUYLA ilgili:
    # en zayıf kanıt (az kullanılan, eski) girdiler geriye doğru atılır.
    USAGE_TAVAN = 120
    # KANIT TABLOSU TAVANI (2026-10-22, KÖK NEDEN 3 DÜZELTMESİ):
    # Kanıtlı girdiler (usage >= PRUNE_USAGE_MIN) tavanı aşabilir —
    # onlar KESİLMEZ, çünkü kanıt budamanın tek yaşam kaynağı.
    #
    # ANCAK: "sert üst sınır" kanıt silerse ortaya çıkan döngüsel tuzak:
    #   kanıt silinir → bağlantı kanıtsızlaşır → budama siler → daha çok
    #   gürültü birikir → tablo daha da büyür → daha çok kanıt silinir.
    #   Ölçülen canlı beyin: usage 600'e (sert sınır) dayandı ve kanıt
    #   girdileri atıldı (kayıp 22).
    #
    # DOĞRU ÇÖZÜM: kanıt girdileri SINIRSIZ BÜYÜMEZ, ama silinmez de.
    #   1) Bir girdi kanıt eşiğine ulaşınca (usage >= PRUNE_USAGE_MIN)
    #      sayacı "dondurulur": kanıtın kendisi korunur, fazlası (yüzlerce
    #      tekrar) ayrı bir SAYIM tablosunda tutulur → tablo şişmez.
    #   2) Sert sınır aşılırsa en zayıf kanıt geriye doğru atılır (kanıt
    #      tamamı birden değil, kademeli azalır).
    # Kalıcı kanıt = anahtarların kendisi; güç = dondurulmuş sayaçlar.
    USAGE_TAVAN_KALAN = 600
    # Bir kanıtlı girdinin sayacı bu değeri aşınca "dondurulur": eşik
    # üstü sayaç (kanıt miktarı) ayrı tabloya taşınır, ana tablo şişmez.
    USAGE_DONDURMA = 50

    def record_usage(self, stim, action):
        """(özellik, eylem) çiftinin kullanım sayısını artır (alışkanlık).

        ÇAPRAZ ÖZELLİKLER KANIT TOPLAMAZ (2026-10-22, KÖK NEDEN 4).
        Çaprazlar kombinatoryal olarak üretilir (N bağlam jetonu →
        N(N-1)/2 çift), yani "bu ikili gerçekten birlikte önemli" olmasa
        bile her etkileşim onlara otomatik kanıt yazar. Ölçülen canlı
        beyin: 6.923 kullanım girdisinin 5.732'si (%82,8) çaprazdı; çapraz
        bağlantılar 8.427 linkin 6.374'ü (%75,7) idi. Kanıt, budamanın
        tek yaşam kaynağı olduğu için bu gürültü, tabloda şişkinlik
        yapmadan "kanıtlı" görünen ölü bağlantıları koruyordu.

        Çapraz bağlantıların AĞIRLIKLARI korunur (skor/ karar davranışı
        değişmez); yalnız otomatik KANIT üretimi engellenir. Böylece
        gerçekten işe yaramayan çaprazlar kanıtsızlaşır ve konsolidasyonda
        budanabilir.
        """
        yeni = []
        for f in self.features(stim):
            if self._capraz_mi(f):
                continue          # çapraz → otomatik kanıt yok
            key = (f, action)
            self.usage[key] = self.usage.get(key, 0) + 1
            yeni.append(key)
        # Sayaç dondurulur: kanıt korunur, tablo şişmez (KÖK NEDEN 3).
        self._usage_dondur()
        self._usage_tavanla(korumali=yeni)

    def _kanitli_mi(self, key):
        """Bu anahtar kanıtlı mı? (budama/tavan ortak kuralı)

        KÖK NEDEN 3 (2026-10-22): kanıt iki yerde birden yaşar:
        · `usage` — sayaç (PRUNE_USAGE_MIN üstü = kanıtlı),
        · `usage_tasma` — dondurulmuş faz (sayaç taşınca da kanıt kalır).
        TAVAN (yumuşak + sert) ve BUDAMA aynı soruyu sorar; cevabı
        TEK bir yerden almak için burada toplandı. Ayrı yollar, biri
        unutulduğunda kanıt sessizce ölüyordu.

        BAĞLANTI ŞARTI: kanıt, bir bağlantının üzerindeki kanıttır.
        Bağlantısı silinmiş bir girdinin kanıtı hiçbir işe yaramaz —
        sadece tabloyu şişirir. Bu yüzden kanıt "bağlantısı varsa"
        anlamına gelir; bağlantısız kanıt gürültü sayılır.
        """
        if key not in self.w:
            return False           # bağlantısız kanıt = gürültü
        if self.usage.get(key, 0) >= self.PRUNE_USAGE_MIN:
            return True
        return key in self.usage_tasma

    def _capraz_kullanim_temizle(self):
        """Çapraz özelliklerin KANITINI temizle (KÖK NEDEN 4).

        `record_usage()` artık çaprazlara kanıt yazmaz; ama eski
        beyin.json dosyalarında birikmiş çapraz kanıt zaten vardır ve
        yüklenirken "kanıtlı" görünür → budama onları silemez → tablo
        şişkin kalır. Ölçülen canlı beyin: kullanımın %82,8'i çaprazdı.

        Bu temizlik YALNIZ kanıt tablosunu etkiler; bağlantı AĞIRLIKLARI
        korunur → skor ve karar davranışı değişmez. Kanıtsızlaşan çapraz
        bağlantılar daha sonra konsolidasyonda budanabilir.

        Dönüş: silinen kanıt girdisi sayısı.
        """
        silinen = 0
        for tablo in (self.usage, self.usage_tasma):
            for k in [k for k in tablo if self._capraz_mi(k[0])]:
                del tablo[k]
                silinen += 1
        return silinen

    def _usage_dondur(self):
        """Kanıt sayaclarını DONDUR: eşiği aşan fazlalar ayrı tabloya.

        KÖK NEDEN 3 (2026-10-22): kanıtlı girdiler tavanı aşabiliyor ama
        silinmemeliydi. "Sert üst sınır" ile kanıt silmek döngüsel tuzak
        yarattı (kanıt→bağlantı→budama→gürültü→daha fazla kanıt→kanıt
        silinmesi). Doğrusu: kanıtın KENDİSİ (anahtar + eşik üstü
        sayaç) sonsuza dek korunur; sadece TEKRAR SAYISI taşan kısım
        ayrı bir tabloda tutulur → ana tablo şişmez, kanıt kaybolmaz.
        """
        tasma = self.USAGE_DONDURMA
        dondur = {}
        for k, v in self.usage.items():
            if v > tasma:
                dondur[k] = v - tasma
                self.usage[k] = tasma
        if dondur:
            self.usage_tasma.update(dondur)
        return dondur

    def _usage_tavanla(self, korumali=()):
        """usage tablosunu USAGE_TAVAN'ın altına indir.

        Silme sırası DETERMİNİSTİKTİR: önce en az kullanılan (en zayıf
        kanıt), eşitlikte eklenme sırası EN ESKİ olan silinir. Böylece
        güçlü alışkanlıklar (çok kullanılan çiftler) korunur, gürültü
        atılır. Python dict ekleme sırasını korur (3.7+); sıralama
        anahtarı (sayı, eklenme sırası) aynı seed => aynı sonucu verir.

        `korumali`: o an eklenen çiftler (yeni kanıt) atılmaz — aksi
        halde "count=1" yeni girdi tabloya girer girmez en zayıf sanılıp
        silinirdi ve yeni alışkanlık hiçbir zaman birikemezdi.

        KÖK NEDEN 2 DÜZELTMESİ (2026-10-22): koruma yalnız "o an eklenen"
        çiftlere uygulanıyordu. Sonuç: her yeni `usage=1` girdi tabloya
        girer girmez KORUNURKEN, `usage >= PRUNE_USAGE_MIN` olan KANITLI
        girdiler gürültü tarafından tablodan ATILIYORDU. Ölçülen canlı
        beyinde kanıtlı girdi sayısı 108 → 51'e düştü: tablo gürültüyle
        dolar, kanıt yerinden edilir, kanıtsızlaşan bağlantı budamada
        silinir. Yani kanıt kaybı iki katmanlıydı:
          1) budamada kanıt yok sayılıyordu (KÖK NEDEN 1, düzeltildi),
          2) tavan kanıtın kendisini siliyordu (KÖK NEDEN 2, burada).
        Artık KANITLI girdiler de korunur: tavan GÜRÜLTÜYÜ keser,
        KANITI kesmez. Sert üst sınır (USAGE_TAVAN_KALAN) aşılırsa en
        zayıf kanıt geriye doğru atılır — dosya boyutu sınırlı kalır,
        kanıtın TAMAMI birden silinmez.
        """
        tavan = self.USAGE_TAVAN
        koru = set(korumali)
        sira = {k: i for i, k in enumerate(self.usage)}
        # Kanıtlı girdiler korunur (KÖK NEDEN 3): kanıt budamanın tek
        # yaşam kaynağı. Ortak kural: _kanitli_mi().
        koru |= {k for k in self.usage if self._kanitli_mi(k)}
        zayif = sorted((kv for kv in self.usage.items() if kv[0] not in koru),
                       key=lambda kv: (kv[1], sira[kv[0]]))
        silinen = 0
        for k, _ in zayif:
            if len(self.usage) <= tavan:
                break
            del self.usage[k]
            # Bağlantı da silinir (KÖK NEDEN 3): usage girdisi silinip
            # bağlantı bırakılırsa bağlantı "kanıtsız" kalır ve sonraki
            # budamada ölür — yani kanıt dolaylı olarak kaybolurdu.
            self.w.pop(k, None)
            silinen += 1
        # Bağlantısız kalan girdiler (kanıt değil, gürültü) temizlenir:
        # kanıt bir bağlantının üzerindedir; bağlantısız kayıt sadece
        # dosyayı şişirir (KÖK NEDEN 3). Temizlik TAVAN kontrolünden
        # BAĞIMSIZ çalışır: tablo tavanda bile bağlantısız kayıt tutmaz.
        _copuk = [k for k in list(self.usage) if k not in self.w]
        for k in _copuk:
            del self.usage[k]
            silinen += 1
        _copuk_t = [k for k in list(self.usage_tasma) if k not in self.w]
        for k in _copuk_t:
            del self.usage_tasma[k]
            silinen += 1
        # Sert üst sınır aşıldıysa: kanıtın TAMAMI silinmez, en zayıf
        # kanıt geriye doğru atılır (dosya boyutu sınırlı kalır).
        #
        # KÖK NEDEN 3 DÜZELTMESİ (2026-10-22): burada `del self.usage[k]`
        # yapılıyor ama `w[k]` BAĞLANTISI birakiliyordu → bağlantı
        # kanıtsızlaşıyor, sonraki budamada SİLİNİYORDU (kanıt kaybı).
        # Düzeltme: bağlantı da birlikte silinir; böylece "kanıtsız bağlantı"
        # diye bir durum kalmaz. Sıralama ÖNCE kanıtsızlar, sonra en zayıf
        # kanıtlar (büyükten küçüğe) — en güçlü kanıt en son korunur.
        sert = self.USAGE_TAVAN_KALAN
        if len(self.usage) > sert:
            sirali = sorted(self.usage.items(),
                            key=lambda kv: (kv[1], sira[kv[0]]),
                            reverse=False)
            for k, _ in sirali:
                if len(self.usage) <= sert:
                    break
                if k in korumali:
                    continue
                # Sert tavan da KANITLARI korur: kanıt, budamanın tek
                # yaşam kaynağı. Yumuşak tavanla aynı kural (KÖK NEDEN 3):
                # tavan GÜRÜLTÜYÜ keser, KANITI kesmez.
                if self._kanitli_mi(k):
                    continue
                del self.usage[k]
                # Bağlantı da silinir: kanıtsız bağlantı bırakmak
                # budamada ölü ağırlık demekti (kanıt kaybının kaynağı).
                self.w.pop(k, None)
                self.usage_tasma.pop(k, None)
                silinen += 1
        return silinen

    def familiarity_boost(self, stim, action):
        """Sık kullanılan çiftler için küçük kalıcı boost (otomatikleştirme).

        Kullanım sayısına logaritmik olarak bağlıdır: ilk birkaç kullanım
        sonrası daralan bir artış.
        """
        import math
        total = 0
        for f in self.features(stim):
            total += self.usage.get((f, action), 0)
            # Dondurulmuş sayaçlar da kanıt gücüdür (KÖK NEDEN 3):
            # dondurma sayacı kesildiği için "güç" kaybolmasın.
            total += self.usage_tasma.get((f, action), 0)
        if total <= 0:
            return 0.0
        return min(0.5, 0.05 * math.log1p(total))

    # ---------- Working memory (Aşama 3) ----------

    @staticmethod
    def _saglik_key(durum):
        """Durumdan eşleşme keyi üret (komut + dogru; surpriz opsiyonel)."""
        return (durum.get('komut'), durum.get('dogru'))

    def ogren_saglik(self, durum, puan, sinif_str):
        """Sağlık eğitimini kaydet: durum → (puan, sınıf_str).

        Args:
            durum: {'komut': str, 'dogru': bool, 'surpriz': int, ...} gibi
                   bir durum sözlüğü.
            puan:  sağlık puanı (ör. 140 = mükemmel, 15 = ölüm tehlikesi).
            sinif_str: SINIFLAR'dan biri ("Mükemmel", "Ölüm Tehlikesi", ...).
        """
        self.saglik_egitim.append((dict(durum), float(puan), sinif_str))

    def uretsaglik_sinyeli(self, durum):
        """Sağlık sinyalini üret: eğitimli durumdan puan + sınıf,
        eğitim yoksa nötr (75, Normal).

        Args:
            durum: dict ise komut/dogru/surpriz tabanlı eşleşme yapılır;
                   drives nesnesi ise energy/hunger'dan nötr puan hesaplanır.

        Returns:
            (puan, sinif_idx): (float, int) — sağlık puanı ve sınıf indeksi.
        """
        if isinstance(durum, dict):
            key = self._saglik_key(durum)
            eslesen = [e for e in self.saglik_egitim
                        if self._saglik_key(e[0]) == key]
            if eslesen:
                puan = sum(e[1] for e in eslesen) / len(eslesen)
                sinif_str = max(
                    set(e[2] for e in eslesen),
                    key=lambda s: sum(1 for e in eslesen if e[2] == s),
                )
                idx = SINIFLAR.index(sinif_str)
                return (round(puan, 2), idx)
            # eğitim yok → nötr
            return (75.0, SINIFLAR.index("Normal"))
        # drives nesnesi: enerji/hunger'dan nötr puan
        energy = getattr(durum, 'energy', 50.0)
        hunger = getattr(durum, 'hunger', 5.0)
        puan = round((energy * 0.7 + (10 - hunger) * 0.3), 2) \
            if hasattr(durum, 'energy') else 75.0
        sinif_idx = min(len(SINIFLAR) - 1, max(0, int((energy - 50) / 15)))
        return (puan, sinif_idx)

    def working_remember(self, stim, action, strength=1.0):
        """Son (stim, action) denemesini çalışma belleğine yazar.

        decide() bu çiftlere küçük bir teşvik boostu verir; aynı uyaranla
        zincir içi tekrar deneme etkileşimi bu şekilde kalıcı kalır.
        working_max'i geçildiğinde en zayıf giriş silinir.
        """
        key = (stim, action)
        self.working_memory[key] = max(
            float(strength), self.working_memory.get(key, 0.0))
        if len(self.working_memory) > self.working_max:
            worst = min(self.working_memory, key=self.working_memory.get)
            del self.working_memory[worst]

    def working_sindir(self):
        """Her tikte bir çağrılır: çalışma belleğini yavaşça sındırır.

        Eski denemeler zamanla etkisini yitirir; sadece yakın geçmişteki
        (stim, action) çiftleri decide() boostunda kalır.
        """
        if not self.working_memory:
            return
        d = self.working_decay
        silinen = [k for k, v in self.working_memory.items()
                   if v * d < 0.01]
        for k in silinen:
            del self.working_memory[k]
        for k in self.working_memory:
            self.working_memory[k] *= d

    def stimulus(self, drives, context, loc="", last_food="-", gorev=None,
                 sistem=None, son=None, deneme=None, ara=None,
                 dunya=None, surpriz=None, makine=None):
        eb, hb = drives.bins()
        # S4 ince girdi: 3'er kovalı L/M/H × A/O/T yanında onluk kovalar —
        # açlık/enerji ayrıntısı ham sayıya yaklaşır (klasör/lokasyon
        # jetonları gibi okunur, eski harf jetonları korunur)
        e_ince = "e:%d" % min(15, max(0, int(drives.energy // 10)))
        h_ince = "h:%d" % min(10, max(0, int(drives.hunger // 10)))
        parcalar = [eb, hb, e_ince, h_ince, loc[:6] or "kok",
                    last_food[:6] or "-", context[:10]]
        # gorev tokenı (kullan organı): beyne "şu an ne yapman isteniyor"
        # bilgisini taşır; böylece (gorev:DOSYA_BUL, cmd:find) bağlantısı
        # öğrenilebilir. Eski kayıtlarla uyum: parametre yoksa format aynı.
        if gorev:
            parcalar.append(gorev)
            # Aşama 4 — aile jetonu: gorev:<tip> yanına gorev_aile:<fam>
            # eklenir. gorev:<tip> ağırlıkları KORUNUR (geriye uyumluluk);
            # aile jetonu aynı aileden görevler arası öğrenme paylaşımını
            # sağlar (ör. SAY ailesinde wc-ilk kaçınması DOSYA_SAY'den
            # SUREC_SAY'a aktarılır). _bilesen ":" içeren bu jetonu da
            # çapraza katar, ek kod gerekmez.
            tip = gorev.split(":", 1)[1] if ":" in gorev else gorev
            aile = self.AILE.get(tip)
            if aile:
                parcalar.append("gorev_aile:" + aile)
        # sistem tokenı (bağışıklık): habitat sağlığı — eksik süreç varsa
        # beyin "kötü ortam" bağlamını görür ve eylemlerini ona göre seçer
        if sistem:
            parcalar.append(sistem)
        # çalışma belleği (Aşama 3): bir önceki komut denemesinin sonucu
        # ve sıradaki denemenin sırası → koşullu kurtarma öğrenimi
        # (ör. son:hata → bu kez başka komut dene; deneme:3+ → kestirim).
        # Token yalnızca verilmişse yazılır; eski brain.json ile uyum.
        if son:
            parcalar.append("son:" + son)
        if deneme:
            n = min(int(deneme), 3)
            parcalar.append("deneme:%d+" % n if n >= 3 else "deneme:%d" % n)
        # ara bellek (Aşama 2): zincirin sonraki adımı hazır mı?
        # (wc/head dosyasız seçilirse stdin = kullan.ara tamponu)
        if ara is not None:
            parcalar.append("ara:var" if ara else "ara:yok")
        # sıkılma (Aşama 4): sıkılma artık kademe (Aşama 6) — tek EŞİK
        # (Y/N) sinyali taşımıyordu (hep1.00 → hep "Y" → sabit bağlam).
        # Üç bant: yok (<0.33) / orta (sikilma:1) / yüksek (sikilma:2).
        # Eski "sikilma:Y" jetonu bilgi taşımıyordu — kademelerle beyin
        # "biraz sıkıldım" ile "çok sıkıldım"ı ayırt eder.
        _sk = getattr(drives, "sikilma", 0.0)
        if _sk >= 0.66:
            parcalar.append("sikilma:2")
        elif _sk >= 0.33:
            parcalar.append("sikilma:1")
        # atölye (Sahne 0/1): dünya sağlığı ve taze sürpriz — beyin
        # "dünyam bozuldu / dünya değişti" bağlamını görür ve merak
        # eylemlerini ona göre seçer (sistem:RISK deseni)
        if dunya:
            parcalar.append(dunya)
        if surpriz:
            parcalar.append(surpriz)
        return "|".join(parcalar)

    @staticmethod
    def _bilesen(stim):
        """(tekil jetonlar, bağlam çaprazları) — pay bütçesi için.

        S2: kolon-jetonu (gorev:*, son:*, deneme:*, dunya:*, sistem:*,
        ara:*, surpriz:*, sikilma:*) çiftleri etkileşimi koda YAZILMADAN
        öğrenir (ör. "gorev:X × son:hata → şu komut"). Ayraç "×" olmalı:
        brain.load, "|" içeren anahtarları (eski durum-ağırlık göçü)
        atlar — çapraz kalıcılıkta kaybolmasın diye.
        """
        p = stim.split("|")
        baglam = [x for x in p if ":" in x]
        carpraz = [baglam[i] + CAPRAZ_AYRAC + baglam[j]
                   for i in range(len(baglam))
                   for j in range(i + 1, len(baglam))]
        return p, carpraz

    @staticmethod
    def _capraz_mi(ozellik):
        """Bu özellik bir bağlam ÇAPRAZI mı? ("a×b" biçiminde mi?)

        Çaprazlar kombinatoryal olarak üretilir: N bağlam jetonu → N(N-1)/2
        çift. Bu yüzden her etkileşim, gerçekten "bu ikili birlikte
        önemli" olmasa bile, otomatik olarak kanıt üretir.
        """
        return CAPRAZ_AYRAC in ozellik

    @staticmethod
    def features(stim):
        p, carpraz = Brain._bilesen(stim)
        return p + carpraz

    def _get(self, feat, action):
        # tarafsız başlangıç: her eylem 0'dan, eşitlikte rastgele
        return self.w.get((feat, action), 0.0)

    def decide(self, stim, feasible):
        """Keşif güvene bağlı: ε_eff = ε / (1 + marj).

        Marj = en iyi − ikinci skor. Sıfırken (hiçbir şey bilinmiyor)
        tam keşif; beyin emin oldukça keşif kendiliğinden kısılır —
        eşik veya ek sayı yok, tek formül. 2026-10-12 ölçümü: sabit
        %35 keşif, öğrenilmiş görevlerde başarıyı %70'te tavanlıyordu
        (beyin biliyordu, keşif faturası ödüyordu). Bilgi erozyonu
        olursa (doğru komut artık çalışmıyorsa) marj daralır ve keşif
        kendiliğinden geri açılır.

        Yeni (bu sürüm):
        - ε ve lr main'den update_dynamic_params(drives) ile güncellenmiş
          halde kullanılır (enerji/acı/sıkılma duyarlı).
        - Episodik bellek: yakın geçmişte benzer uyaranla izlenen eyleme
          küçük bir "hatırlama" boostu eklenir.
        - Alışkanlık boostu: sık kullanılan (özellik, eylem) çiftlerine
          logaritmik familiarity artışı.
        """
        if not feasible:
            self.son_kesif = True
            return "rest"
        feats = self.features(stim)

        # Episodik hatıra: yakın geçmişte benzer stim ile hangi eylem izlendi?
        recalled = self.episodic_recall(stim)

        scores = []
        for a in feasible:
            base = sum(self._get(f, a) for f in feats)
            boost = 0.0
            # 1) Episodik hatıra boostu (kısa vadeli bağlamsal bellek)
            if recalled is not None and a == recalled:
                boost += 0.25
            # 2) Working memory boost (yakın geçmişte denenen eylemler)
            wm_key = (stim, a)
            if wm_key in self.working_memory:
                boost += 0.15 * self.working_memory[wm_key]
            # 3) Alışkanlık / otomatikleştirme boostu (sık kullanılan çiftler)
            boost += self.familiarity_boost(stim, a)
            scores.append((base + boost, a))
        sirali = sorted((s for s, _ in scores), reverse=True)
        marj = sirali[0] - sirali[1] if len(sirali) > 1 else 0.0
        # Keşif tabanı: marj her ne kadar olursa olsun keşif asla
        # EPS_TABAN'ın altına inmez — bilgi çok olsa bile yeniden
        # deneme kanı hiç kapanmaz (kör nokta üretmez).
        eps = max(self.EPS_TABAN, self.epsilon / (1.0 + max(0.0, marj)))
        # sıkılma (Aşama 4): rutin doygunluk keşif baskısını yükseltir;
        # yenilik buldukça söner → kendi kendini dengeleyen merak
        eps = min(0.95, eps + 0.3 * max(0.0, self.sikilma))
        self.son_kesif = self.rng.random() < eps
        if self.son_kesif:
            # Aşama 1 — akıllı keşif havuzu: keşif artık rastgele değil,
            # öğrenilmiş cezalardan arındırılmış adaylar içinden yapılır.
            # score>=0 havuzu bilinen doğru yolları korur (wc-ilk patolojisi
            # düşer: wc, ara:yok bağlamında negatif skorla havuzdan elenir).
            # Havuz BOŞsa (her eylem negatif — hiçbir şey bilinmiyorsa ya da
            # tüm adaylar cezalıysa) tam keşfe düşülür: klasik rastgele seçim.
            havuz = [a for s, a in scores if s >= 0.0]
            if not havuz:
                havuz = feasible
            # Aşama 6 — TAM havuz payı (kör nokta kaçışı): keşfin KESIF_TAM
            # oranı score filtresiz TAM havuzdan seçilir. Negatife çökmüş
            # ama aslında işe yarayan bir kapı (ör. cmd:*) ancak yeniden
            # denenirse skoru düzelir — filtre tek başına kalıcı kör nokta
            # üretir (havuz {rest}'e inince 5.5 saat sıfır görev).
            if havuz is not feasible and self.rng.random() < self.KESIF_TAM:
                havuz = feasible
            return self.rng.choice(havuz)
        cands = [a for s, a in scores if s == sirali[0]]
        return self.rng.choice(cands)

    def score(self, stim, action):
        """Eylemin bu uyaran için toplam skoru (özellik ağırlıkları toplamı)."""
        return sum(self._get(f, action) for f in self.features(stim))

    def _yaz(self, key, pay):
        """Bağlantıyı güncelle: hafif sönüm + kırpma (S5 şişme koruması)."""
        yeni = self.w.get(key, 0.0) * 0.999 + pay
        if yeni > AGIRLIK_TAVAN:
            yeni = AGIRLIK_TAVAN
        elif yeni < -AGIRLIK_TAVAN:
            yeni = -AGIRLIK_TAVAN
        self.w[key] = yeni

    def learn(self, stim, action, reward, r_merak=0.0):
        """Delta kuralı + S1 gecikmeli kredi + S2 çapraz pay bütçesi + S3 merak.

        S3: merak (keşif/"bilmiyorum ama deneyeyim") ödülü için ayrı
        öğrenme hızı: lr_merak = lr * 1.5. R_merak > 0 olduğunda organizma
        sürpriz/keşifli eylemini kalıcılaştırır — kalıcı "merak" davranışı.

        Yeni (bu sürüm):
        - Etkileşim episodik belleğe kaydedilir (kısa vadeli hatıra).
        - (özellik, eylem) kullanım sayısı artırılır (alışkanlık boostu).
        """
        reward = max(-20.0, min(40.0, reward))
        # Episodik bellek ve kullanım kaydı (yeni)
        self.episodic_push(stim, action, reward)
        self.record_usage(stim, action)
        p, carpraz = self._bilesen(stim)
        err = reward - self.score(stim, action)
        lr_efektif = self.lr * 1.5 if r_merak > 0 else self.lr
        # --- S2 pay bütçesi: çapraz yoksa bütçe tümü tekil gider ---
        pay_t = lr_efektif * err * (0.75 if carpraz else 1.0) / max(1, len(p))
        pay_c = lr_efektif * err * 0.25 / max(1, len(carpraz))
        for f in p:
            self._yaz((f, action), pay_t)
        for f in carpraz:
            self._yaz((f, action), pay_c)

    def credit(self, stim, action, bonus):
        """Gecikmeli kredi: hedefi değiştirmeden eklemeli itme.

        (learn() hedefe çeker; gecikmiş bonus ise anlık ödülün üstüne
        biner, onu ezmemeli.) learn() ile aynı iki-bütçe düzeni (75/25).

        KULLANIM KAYDI (yeni): credit() de bağlantı yazar, o yüzden
        o bağlantıları "denenmiş" saymalı. Daha önce credit() yalnız
        ağırlık yazıyordu: ortaya çıkan bağlantıların kullanım sayacı
        0 kalıyordu → konsolidasyon onları "kanıtsız" sayıp silebiliyor
        (düzeltilmiş budama) → her tikte yeniden yazılıyordu → tablo
        şişik kalıyordu. Ölçülen: canlı tabloda 5558 bağlantının
        2086'sı kullanım=0 idi; bunların büyük kısmı credit() yoluydu.
        """
        self.record_usage(stim, action)
        p, carpraz = self._bilesen(stim)
        share_t = self.lr * bonus * 0.75 / max(1, len(p))
        share_c = self.lr * bonus * 0.25 / max(1, len(carpraz))
        for f in p:
            self._yaz((f, action), share_t)
        for f in carpraz:
            self._yaz((f, action), share_c)

    def hatira(self, journal_yolu, azami=400, kuyruk=2_000_000):
        """Aşama 4 — hatıra: uykuda kendi geçmişini yeniden yaşama.

        learn satırları (stim, action, R) kaydından son pencereyi okur,
        GÜNCEL ağırlıklarla yeniden oynar (deneyim tekrarı): yeni
        deneyimlerin sürüklediği bağlantıları kendi geçmişine çeker.
        Ödül uydurulmaz — jurnale o an kaydedilen R tekrarlanır; eski
        (R'siz) learn satırları atlanır. Dönüş: oynanan örnek sayısı.
        """
        try:
            with open(journal_yolu, "rb") as f:
                f.seek(0, 2)
                boy = f.tell()
                f.seek(max(0, boy - kuyruk))
                ham = f.read().decode("utf-8", "replace")
        except OSError:
            return 0
        ornekler = []
        for satir in ham.splitlines():
            if '"kind": "learn"' not in satir or '"R":' not in satir:
                continue
            try:
                j = json.loads(satir)
            except ValueError:
                continue
            if ("stim" in j and "action" in j
                    and isinstance(j.get("R"), (int, float))):
                ornekler.append((j["stim"], j["action"], float(j["R"])))
        # S5 stratifikasyon: zamanınsal son pencere + pencere dışındaki
        # şok dersler (|R| >= 3) — güçlü ders bayatlaşıp kaybolmasın;
        # toplam azami+azami/2 ile sınırlı, fazlaysa en küçük şoklar atılır
        son_bas = max(0, len(ornekler) - azami)
        secim = [(i, o) for i, o in enumerate(ornekler)
                 if i >= son_bas or abs(o[2]) >= 3.0]
        tavan = azami + azami // 2
        if len(secim) > tavan:
            sok = sorted((x for x in secim if x[0] < son_bas),
                         key=lambda x: abs(x[1][2]))
            fazla = len(secim) - tavan
            atlanan = set(i for i, _o in sok[:fazla])
            secim = [x for x in secim
                     if x[0] >= son_bas or x[0] not in atlanan]
        n_oynanan = 0
        for _i, (stim, act, r) in secim:
            self.learn(stim, act, r)
            n_oynanan += 1
        return n_oynanan

    # Kullanım verisi olmayan bağlantı: ya hiç denenmemiş ya da
    # credit()/learn() yoluyla üretilip sayacı işletilmemiş. Kullanım
    # sayacı 0 olan bağlantı "ölü" sayılır — kanıtı olmayan güç, öğrenme
    # değil gürültüdür.
    # Tek seferlik öğrenme (usage == 1) de zayıf kanıttır: bir deneme
    # sonucu, kararlı bir alışkanlığı göstermez.
    PRUNE_USAGE_MIN = 2       # bu kadar kez kullanılmadan korunmaz
    # PRUNE_USAGE_KEEP: "eşiğe hiç bakılmaz" eşiği. Kodda ayrı bir
    # dal olarak KULLANILMAZ (PRUNE_USAGE_MIN zaten her şeyi koruyor);
    # belgelenmiş ama uygulanmayan bir sabit olduğu için not düşüldü.
    PRUNE_USAGE_KEEP = 10

    def _budama_adayi(self, esik):
        """Budamaya aday bağlantıları (kullanım + ağırlık ölçütü).

        Korunur:
          · INSTINCTS (doğuştan refleksler) — her koşulda.
          · usage >= PRUNE_USAGE_MIN (>=2) — TEK BAŞINA yeter: kanıtlı
            bağlantı ağırlığı zayıf olsa bile korunur (2026-10-22
            düzeltmesi, `konsolide(koru_ust=...)` dalı da aynı kuralı
            uygular → iki budama yolu tutarlı).

        Aday (silinebilir):
          · usage == 0 (kullanılmamış/kanıtsız) — ağırlığı ne olursa
            olsun silinir. Ölçülen: 5558 bağlantının 2086'sı bu grupta
            ve hepsi |w| >= 0.02 → eski budama onları HİÇBİR ZAMAN
            silemiyordu (tablo küçülmüyordu).
          · usage < PRUNE_USAGE_MIN VE |w| < esik (zayıf + az kanıt).
          · usage >= PRUNE_USAGE_MIN VE |w| < esik (zayıf ama kanıtlı)
            → KORUNUR (kod: u >= PRUNE_USAGE_MIN → continue). 2026-10-22
            düzeltmesi: bu dal önceden "usage>=2 ama zayıf → aday"
            diye belgelenmişti, kod ise zaten koruyordu; docstring
            gerçeği yansıtmıyordu. `koru_ust` dalı da artık aynı
            kuralı uygular → iki budama yolu TUTARLI.
        """
        aday = []
        for k, v in self.w.items():
            if k in self.INSTINCTS:
                continue
            u = self.usage.get(k, 0)
            # Dondurulmuş sayaç da kanıttır : sayac
            # dondurulduğu için `usage` sıfıra düşmez kanıt kaybolmaz.
            if self._kanitli_mi(k):
                continue                       # kanıt geçmişi var: her zaman koru
            if u == 0:
                if abs(v) >= esik:
                    continue                   # kanıtsız ama güçlü: koru
                aday.append(k)                 # kanıtsız ve zayıf: sil
                continue
            # 0 < u < PRUNE_USAGE_MIN
            if abs(v) >= esik:
                continue                       # az kullanım ama güçlü: koru
            aday.append(k)                      # az kullanım ve zayıf: sil
        return aday

    def konsolide(self, esik=0.02, koru_ust=None):
        """Aşama 5 — konsolidasyon: uykuda zayıf bağlantı budama.

        _yaz her dokunuşta küçük paylar biriktirir; tekrar tekrar
        dokunulan ama hiç sonuç getirmeyen (ödülü ~0) bağlantılar
        esik altında kalır ve tabloda ölü ağırlık olarak şişirir.
        Budama nötrdür: _get eksik anahtar için 0.0 döndürdüğü için
        |w| < esik olan bağlantının silinmesi skoru en fazla esik
        kadar oynatır (eylem sıralamasını praktikte değiştirmez).
        INSTINCTS (doğuştan refleksler) öğrenmeyle ezilmiş olsalar
        bile budanmaz — yaşama yanlısı yaratılış koruması.
        Dönüş: budanan bağlantı sayısı (uyku raporu için).

        `koru_ust`: budama sonrası KORUNACAK bağlantı tabanı.
        Budama "ölü" ağırlıkları hedefler; tablonun TAMAMINI silmek
        (ölçülen: 1937 → 131 bağlantı) tüm öğrenmeyi yok eder ve
        sistemi körleştirir. Koruma tabanı, en güçlü bağlantıların
        her zaman hayatta kalmasını garanti eder.

        USAGE KANITI (2026-10-22 düzeltmesi): `koru_ust` dalı da
        `_budama_adayi()` ile AYNI kuralı uygular — usage >=
        PRUNE_USAGE_MIN (>=2) olan bağlantılar kanıtlı sayılır ve
        BUDANMAZ, ağırlıkları eşiğin altına düşmüş olsa bile.
        Önceden bu dal yalnız ağırlığa bakıyordu; canlı beyinde
        usage>=2 kanıtlı 119 bağlantının 84'ü decay sonrası zayıf
        olduğu için siliniyordu (decay → eşik altı → konsolide →
        bağlantı yok). Aynı budamanın iki yolu (koru_ust=None ve
        koru_ust=300) artık TUTARLI sonuç verir.

        UYGULAMA: silinecek miktar, ZAYIF bağlantılar arasından
        en zayıflar seçilerek hesaplanır; ama TOPLAM tablo
        `koru_ust` tabanının ALTINA düşürülmez. Yani `koru_ust`
        "zayıf bağlantı tabanı" değil, "Tablo tabanı"dır:
        güçlü bağlantılar zaten korunur, kalan pay zayıflardan
        doldurulur.

        Örnek (ölçülen): 1937 bağlantı, 37'si güçlü →
        koru_ust=300 → en zayıf 1637'si silinir, 300 kalır.

        KULLANIM FARKINDARLILIĞI (yeni):
        Budama artık YALNIZ ağırlığa bakmaz; kullanım kanıtını da
        sorar. Eski kural "|w| < esik" idi; ölçülen tabloda 5558
        bağlantının 2086'sı kullanım=0 ve |w| >= 0.02 olduğu için
        ESKİ KURAL BUNLARI HİÇ SİLEMEZDİ → budama 49 bağlantıyla
        sınırlı kalıyor, tablo küçülmüyor, "sifirla" her seferinde
        boşuna +0.15 alıyordu (ödül hacking döngüsü). Artık
        kullanım=0 olan bağlantılar ağırlığı ne olursa olsun adaydır.
        """
        silinen = 0
        if koru_ust is not None:
            # 1. Aşama: zayıf bağlantıları (|w| < esik) sil, ama
            # toplam tablo koru_ust'a inince DUR.
            #
            # KÖK NEDEN DÜZELTMESİ (2026-10-22): bu dal önceden
            # YALNIZ ağırlığa bakıyordu; "usage" kanıtını yok sayıyordu.
            # Oysa `_budama_adayi()` (koru_ust=None dalı) usage>=2 olan
            # bağlantıları KORUYORDU → aynı budama iki farklı sonuç
            # veriyordu. Canlı beyin kanıtı: usage>=2 kanıtlı 119
            # bağlantının 84'ü decay ile eşiğin altına düşmüştü ve
            # HEP SİLİNİYORDU. zincir: decay → eşik altı → konsolide →
            # bağlantı yok. Artık usage>=PRUNE_USAGE_MIN olan bağlantı
            # kanıtı olduğu için budamada KORUNUR (silinmez).
            zayif_aday = [k for k in self.w
                          if k not in self.INSTINCTS
                          and abs(self.w[k]) < esik
                          and self.usage.get(k, 0) < self.PRUNE_USAGE_MIN
                          and not self._kanitli_mi(k)]
            # En zayıflar önce.
            zayif_aday.sort(key=lambda k: abs(self.w[k]))
            for k in zayif_aday:
                if len(self.w) <= int(koru_ust):
                    break
                del self.w[k]
                self.usage.pop(k, None)
                self.usage_tasma.pop(k, None)
                silinen += 1

            # 2. Aşama: zayıf bitti ama hala fazla varsa, GÜÇLÜLERİ
            # SILME. koru_ust hedef boyuttur; güçlüleri bozarak inmez.
            # (Test 24b: 5000 → 300'a inmeye çalış ama 4939 güçlü
            #  bağlantıyı koru, 300'ın altına düşme.)
            #
            # BİLİNÇLİ AYRIM: usage=0 ama |w| >= esik olan bağlantılar
            # (ölçülen: 3986 adet) bu yolda KALIR, uyku yolunda
            # (_budama_adayi) silinir. Kanıt KAYBı değildir — kanıtlı
            # bağlantılar zaten korunuyor; sadece tablo bir süre şişkin
            # kalır ve koru_ust tabanı dolana kadar küçülmez. Kanıt
            # kaybını önlemek (asıl düzeltme) ile tablo şişkinliğini
            # çözmek ayrı işler; ikincisi bu düzeltmenin kapsamı dışında.
        else:
            # Eski davranış: sadece esik'e göre budama.
            aday = self._budama_adayi(esik)
            for k in aday:
                del self.w[k]
                self.usage.pop(k, None)
                self.usage_tasma.pop(k, None)
                silinen += 1
        return silinen

    def report(self, top=6):
        """Öğrenilmiş en güçlü bağlantılar (gözlem için)."""
        ranked = sorted(self.w.items(), key=lambda kv: -kv[1])[:top]
        return [
            {"stim": k[0], "action": k[1], "w": round(v, 2)}
            for k, v in ranked
        ]

    # ---------- kalıcı hafıza (atomik JSON) ----------

    def save(self, path):
        """tmp + rename: yazma yarıda kesilse bile beyin bozulmaz."""
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        # Ağırlıklar TAM hassasiyetle yazılır (round YOK): JSON round-trip
        # birebir olmalı. KÖK NEDEN: round(w, 6) kaydı 6 ondalığa
        # kırpıyordu → load() sonrası w orijinalle FARKLI oluyordu
        # ("save→load→save" sabit nokta değildi). Python'ın float repr'i
        # zaten tam round-trip garantisi verir; dosya boyutu farkı ihmal
        # edilebilir (beyin zaten JSON'da saklanıyordu).
        data = {"links": [[s, a, w] for (s, a), w in self.w.items()],
                "allowed": sorted(getattr(self, "allowed_extra", set())),
                # --- kalıcı öğrenme belleği (yeni) ---
                # episodic: son etkileşimler (stim, eylem, ödül) — açılışta
                # "hatırlama" boostu ve alışkanlık öğrenmesi kaybolmasın.
                # usage: (özellik, eylem) kullanım sayıları — alışkanlık
                # boostu kalıcı olsun (her açılışta sıfırlanıyordu!).
                "episodic": [[s, a, r] for (s, a, r) in self.episodic],
                "usage": [[f, a, n] for (f, a), n in self.usage.items()],
                # Dondurulmuş sayaçlar (KÖK NEDEN 3): kanıt gücünün tablo
                # şişmeden korunması.
                "usage_tasma": [[f, a, n] for (f, a), n
                                in self.usage_tasma.items()],
                "saglik_egitim": [[d, p, s] for (d, p, s) in self.saglik_egitim],
                "kural": "delta1"}
        tmp.write_text(json.dumps(data, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(path))

    def load(self, path):
        """Doğuşta beyni hatırla; bozuk/eksik dosya doğuşu iptal etmez."""
        path = Path(path)
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return 0
        links = data.get("links", [])
        # 'kural' etiketi yoksa kayıt eski iz-kuralıyla yazılmış: orada
        # kararlı ağırlık ≈ 1.5·ödül (lr/(1-momentum)) ve uyaranın 5
        # özelliğinin HEPSİ bunu taşırdı. Delta kuralında toplam ≈ ödül
        # olduğundan, ağırlıklar 1/(1.5·5) ile ölçeklenir.
        legacy = data.get("kural") != "delta1"
        olcek = LEGACY_OLCEK if legacy else 1.0
        for s, a, w in links:
            # eski durum-tek-ağırlık kayıtları ('|' içerir) artık geçersiz;
            # özellik-bazlı beyin yalnızca tek parça özellik anahtarları tutar
            if "|" in s:
                continue
            self.w[(s, a)] = float(w) * olcek
        # kazanılan yetenekler (ör. sort kası) da beyninle taşınır
        self.allowed_extra = set(data.get("allowed", []))
        # --- kalıcı öğrenme belleği (yeni) ---
        # episodic: (stim, eylem, ödül) — hatırlama boostu kaybolmasın.
        # ÖNCE temizlenir: aynı Brain'a ikinci kez load() edilirse
        # eski kayıtlar kopyalanmaz (deterministik geri yükleme).
        self.episodic.clear()
        for kayit in data.get("episodic", []):
            try:
                s, a, r = kayit
                self.episodic.append((str(s), str(a), float(r)))
            except (TypeError, ValueError):
                continue          # bozuk kayıt atlanır (doğuşu iptal etmez)
        # usage: (özellik, eylem) → sayı — alışkanlık boostu kalıcı olsun.
        self.usage = {}
        for kayit in data.get("usage", []):
            try:
                f, a, n = kayit
                self.usage[(str(f), str(a))] = int(n)
            except (TypeError, ValueError):
                continue          # bozuk kayıt atlanır
        # Dondurulmuş sayaçlar (KÖK NEDEN 3): kanıt gücü, tablo şişmeden.
        self.usage_tasma = {}
        for kayit in data.get("usage_tasma", []):
            try:
                f, a, n = kayit
                self.usage_tasma[(str(f), str(a))] = int(n)
            except (TypeError, ValueError):
                continue          # bozuk kayıt atlanır
        # --- sağlık eğitimi (kalıcı) ---
        self.saglik_egitim = []
        for kayit in data.get("saglik_egitim", []):
            try:
                d, p, s = kayit
                self.saglik_egitim.append((dict(d), float(p), str(s)))
            except (TypeError, ValueError):
                continue          # bozuk kayıt atlanır
        # Eski (tavansız) kayıtlardan gelen şişik tablo sınırsız kalmasın.
        # Yeni yazılan beyinler zaten ≤ USAGE_TAVAN girdi içerdiğinden
        # save→load→load sabit nokta korunur (birebir round-trip bozulmaz).
        # ÖNCE dondur: yüklenen büyük sayaçlar tavanlanmadan önce taşınır,
        # kanıt gücü korunur (KÖK NEDEN 3).
        # ÇAPRAZ kanıtları temizle (KÖK NEDEN 4): eski tablolarda birikmiş
        # kombinatoryal gürültü "kanıtlı" görünüp budamayı engelliyordu.
        self._capraz_kullanim_temizle()
        self._usage_dondur()
        self._usage_tavanla()
        return len(links)
SINIFLAR = ("Ölüm Tehlikesi", "Normal", "Mükemmel")

class OzHedef:
    """Özgür hedefleme organi - merak odaklı kendi hefleri belirler."""
    def __init__(self, brain, drives):
        self.brain = brain
        self.drives = drives
        self._hedef = None
        self._baslangic_tik = 0
        self._sureci_tik = 0
        self._gecmis = []

    # -----------------------------------------------------------
    # Bağlam Sınıflandırması
    # -----------------------------------------------------------
    def _baglam_klas(self, drives):
        """İç durumu 'tehlike' / 'acık' / 'rahatlama' olarak sınıflandır."""
        try:
            energy = float(getattr(drives, "energy", 50.0))
            hunger = float(getattr(drives, "hunger", 30.0))
        except (TypeError, ValueError):
            energy, hunger = 50.0, 30.0

        pain = 0.0
        try:
            _p = getattr(drives, "pain", 0.0)
            if callable(_p): _p = _p()
            pain = max(0.0, min(1.0, float(_p)))
        except (TypeError, ValueError):
            pass

        in_danger = bool(getattr(drives, "in_danger", False))

        if in_danger or pain > 0.5 or energy < 30.0 or hunger > 85.0:
            return "tehlike"
        if energy < 60.0 or hunger > 50.0:
            return "acık"
        return "rahatlama"

    # -----------------------------------------------------------
    # Her Tick Güncelleme
    # -----------------------------------------------------------
    def guncelle(self, tik):
        """Her ana döngü tickinde çağrılır. Özgür hedefler belirlenir."""
        # 1. Sürpriz/merak ölçümlerini topla
        novel = float(getattr(self.drives, "novel", 0.0))
        merak = float(getattr(self.drives, "merak", 0.0))

        self._novel_gecmisi = getattr(self, "_novel_gecmisi", [])
        self._merak_gecmisi = getattr(self, "_merak_gecmisi", [])
        self._novel_gecmisi.append(novel)
        self._merak_gecmisi.append(merak)

        # 2. Bağlamı belirle
        baglam = self._baglam_klas(self.drives)
        self._aktif_baglam = baglam

        # 3. Yeni hedef mı oluştur?
        yeni_hedef = False

        # Bağlama özel eşikler ve faktörler
        if baglam == "tehlike":
            novel_esik = 0.7   # tehlikede daha yüksek novelty gerekir
            merak_esik = 0.5   # ve merak
            koruma_faktori = 0.5  # mevcut hefi korumaya daha empefyok
        elif baglam == "acık":
            novel_esik = 0.5   # normal eşik
            merak_esik = 0.3
            koruma_faktori = 1.0
        else:  # rahatlama
            novel_esik = 0.4   # rahattalama'da daha düşük eşik
            merak_esik = 0.2
            koruma_faktori = 0.8  # hafifpekti teşvik

        # A) Yüksek novelty + yüksek merak + Henüz hedef yoksa → HEFI BELİRLE
        context_condition = (novel > novel_esik and merak > merak_esik and self._hedef is None)

        if context_condition:
            # Bağlama göre hedef türü belirle
            if baglam == "tehlike":
                # Tehlikede "keşif" yerine "sıfırla" veya korunmaya odaklan
                if self._sureci_tik < 50:  # Henüz yeni başlarsa keşif
                    self._hedef = "keşif"
                else:
                    self._hedef = "sıfırla"  # Uzun süredir varsa terk et
                self._baslangic_tik = tik
                self._sureci_tik = 0
                self._gecmis.append({
                    "tik": tik,
                    "hedef": self._hedef,
                    "novel": novel,
                    "merak": merak,
                    "baglam": baglam
                })
                yeni_hedef = True
            elif baglam == "acık":
                # Açlık: normal keşif
                self._hedef = "keşif"
                self._baslangic_tik = tik
                self._sureci_tik = 0
                self._gecmis.append({
                    "tik": tik,
                    "hedef": "keşif",
                    "novel": novel,
                    "merak": merak,
                    "baglam": baglam
                })
                yeni_hedef = True
            else:  # rahatlama
                # Rahatlama: keşif veya öğren
                self._hedef = "keşif"
                self._baslangic_tik = tik
                self._sureci_tik = 0
                self._gecmis.append({
                    "tik": tik,
                    "hedef": "keşif",
                    "novel": novel,
                    "merak": merak,
                    "baglam": baglam
                })
                yeni_hedef = True
        # B) Uzun süredir aynı hedef var ve sikiliniyorSA → TERK ET (koruma faktörü ile)
        elif (self._hedef and
              tik - self._baslangic_tik > 200 and
              float(getattr(getattr(self.drives, "sikilan", 0), "sikilan", 0) if hasattr(self.drives, "sikilan") else 0) > 0.5 * koruma_faktori):
            self._gecmis.append({
                "tik": tik,
                "hedef": "sıfırla",
                "novel": novel,
                "merak": merak,
                "reason": "sikilan_yüksek",
                "koruma_faktori": koruma_faktori
            })
            self._hedef = None
            self._sureci_tik = 0
            yeni_hedef = True
        # C) Mevcut hefin süresi doldu → Yeni hedef ara
        elif (self._hedef and
              self._sureci_tik >= getattr(self, "_HEDEFLER", {}).get(self._hedef, {}).get("max_sure", 100)):
            self._gecmis.append({
                "tik": tik,
                "hedef": self._hedef,
                "novel": novel,
                "merak": merak,
                "reason": "süre_doldu"
            })
            self._hedef = None
            self._sureci_tik = 0
            yeni_hedef = True

        # 3. Alt süreyi güncelle (varsa)
        if self._hedef:
            self._sureci_tik += 1

        return yeni_hedef

    # -----------------------------------------------------------
    # Mevcut Hedefi Döndür
    # -----------------------------------------------------------
    def mevcut_hedef(self):
        """Şu an aktif olan hedef string'i (None jika yok)."""
        return self._hedef

    # -----------------------------------------------------------
    # Hedef Talimatı (Main.py için çıktı)
    # -----------------------------------------------------------
    def hedef_talimat(self):
        """
        Dışarıya (main.py/yu) verilecek hedef talimatı.
        ['keşif'], ['öğren'] ya da None döner.
        """
        if self._hedef:
            return [self._hedef]
        return None

    # -----------------------------------------------------------
    # Rapor/İzleme
    # -----------------------------------------------------------
    def rapor(self):
        """Güncel hedef durumu raporu."""
        novel_ort = sum(getattr(self, "_novel_gecmisi", [0])) / max(1, len(getattr(self, "_novel_gecmisi", [0])))
        merak_ort = sum(getattr(self, "_merak_gecmisi", [0])) / max(1, len(getattr(self, "_merak_gecmisi", [0])))
        return {
            "aktif_hedef": self._hedef,
            "sureci_tik": self._sureci_tik,
            "novel_ortalama": round(novel_ort, 3),
            "merak_ortalama": round(merak_ort, 3),
            "gecmis_sayisi": len(self._gecmis)
        }


# -----------------------------------------------------------
SINIFLAR = ("Ölüm Tehlikesi", "Normal", "Mükemmel")
# -----------------------------------------------------------
