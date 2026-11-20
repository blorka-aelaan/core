// CORE pano — veri katmanı.
// Jurnal tarayıcı (akış + tam tarama), sayaçlar, seriler, yan dosya
// önbelleği. Salt okuma: organizmaya asla yazmaz (yönetim ayrı uçta).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "..", "..");
export const JOURNAL = path.join(ROOT, "journal.jsonl");

const RING = 500;            // canlı akış halkası (act/learn hariç)
const SERI = 150;            // grafik serisi uzunluğu
const ZINCIR = new Set(["SUREC_SAY", "DOSYA_SAY"]);
const AG_KAPILARI = {
  AG_TARA: new Set(["cmd:nmap", "cmd:ping", "cmd:ip", "cmd:traceroute"]),
  BENI_TARA: new Set(["cmd:nmap", "cmd:ss", "cmd:traceroute", "cmd:curl"]),
};

export function agKomutSinifi(hedef, komut) {
  if (!Object.prototype.hasOwnProperty.call(AG_KAPILARI, hedef)
      || !String(komut || "").startsWith("cmd:")) return null;
  return AG_KAPILARI[hedef].has(komut) ? "ag" : "diger";
}

// Üst beyin komut sırası — ust_beyn.py KOMUTLAR ile birebir aynı.
// (Model dosyası yalnızca indeksle ölçüm saklar; adlar burada.)
const UST_KOMUTLAR = [
  "yok", "acil_dinlen", "acil_yem", "kapat_ag",
  "kisitla_dosya", "guvenli_mod", "sifirla", "asm_ogren",
];

let offset = 0;              // jurnalden okunan bayt
let artik = "";              // yarım satır artığı
let bozuk = 0;
let D = sifirla();

function sifirla() {
  return {
    toplam: 0,               // işlenen satır
    sayac: {},               // kind -> adet
    kullan: {
      n: 0, ok: 0,
      deneme: {},            // 1|2|3 -> {n, ok}
      hedef: {},             // tip -> {n, ok}
      zincir: { n: 0, ok: 0, ilerleme: 0, baslatilan: 0 },
      sonKullan: [],
    },
    birak: { n: 0, deneme: {}, son: [] },
    // Ağ keşfi (AG_TARA/BENI_TARA): kapı performansı + duraklama kanıtı
    ag: {
      kapi: {}, duraklama: {}, hedef: {}, son: [],
      diger: {}, sonDiger: [],
    },
    // Sahne 1/2: merak ekonomisi (öz-ödül olayları + dünya sağlığı serisi)
    merak: { n: 0, odul: 0, islem: {}, son: [], seri: [] },
    // Üst beyin (ust_beyn.py): komut seçimleri, reddedilmeler, sifirla
    // budamaları — günlükten (canlı) + zeka/ust_beyn.json'dan (model).
    ust: {
      override: {},             // komut -> {n, model, kesif}
      red: {},                 // komut|gerekce -> adet
      redKomut: {},            // komut -> adet
      sonOverride: [],         // son override olayları
      sonRed: [],              // son reddedilmeler
      sifirla: { n: 0, budanan: 0, links: 0, ornek: [] },
    },
    uyku: [],                // {t, ad, veri, kod, sure, ornek, soyutlasma}
    hatalar: [],             // {t, tur, stim, eylem, odul, guven}
    neden: [],               // {t, eylem, guven, ozellik_katkilari, gecmis_deneyim, tehlike_olasiligi}
    disSal: [],              // {t, deger, odul} — dışsal geri bildirim
    konsolidasyon: [],       // {t, adet} — çalışma bellek konsolidasyonu
    ders_islem: [],          // {t, kind, hedef, yanlis, dogrusu, not_}
    uzuvSon: null,
    evren: null,
    surec: { ornek: 0, adet: 0, son: null },
    dogum: 0,
    sonKapanis: 0,
    sonAct: null,
    sikilma: 0,
    // ---------- Yeni: Bu bilgisayarın bedeni (Aşama 8) ----------
    beden: { insan_var: false, sistem_saati: 0, disk_yuzde: 0, bellek_yuzde: 0 },
    // ---------- Yeni: USB — kernel seviyesinde (Aşama 10) ----------
    usb: { cihaz_sayisi: 0, node_sayisi: 0, keşif_bonusu: 0 },
    // ---------- Yeni: Ruh hali / mood vektörü (Aşama 9) ----------
    mood: {
      mutluluk: 0, korku: 0, guven: 0, merak: 0, sikilma: 0,
      beden_baski: 0, dominant: "-",
    },
    seriler: { E: [], H: [], R: [], S: [] },
    ring: [],
  };
}

function seri(liste, t, v) {
  liste.push([t, v]);
  if (liste.length > SERI) liste.splice(0, liste.length - SERI);
}

function halka(kayit) {
  if (kayit.kind === "act" || kayit.kind === "learn") return;
  D.ring.push(kayit);
  if (D.ring.length > RING) D.ring.splice(0, D.ring.length - RING);
}

function ekle(harita, anahtar, ok) {
  const v = (harita[anahtar] ||= { n: 0, ok: 0 });
  v.n += 1;
  if (ok) v.ok += 1;
}

function isle(k) {
  D.toplam += 1;
  const kind = k.kind || "?";
  D.sayac[kind] = (D.sayac[kind] || 0) + 1;
  halka(k);

  switch (kind) {
    case "kullan": {
      const u = D.kullan;
      u.n += 1;
      if (k.dogru) u.ok += 1;
      ekle(u.deneme, String(Math.min(k.deneme || 1, 3)), !!k.dogru);
      ekle(u.hedef, k.hedef || "?", !!k.dogru);
      if (ZINCIR.has(k.hedef)) {
        u.zincir.n += 1;
        if (k.dogru) u.zincir.ok += 1;
        // ILERLEME (kullan.py: ILERLEME=3.0) → main odul=int(gain)=3
        // yazar; kazanç 6.0. Eski ILERLEME=1.0 gününden kalma `=== 1`
        // kontrolü panoyu "0 ara veri adımı" gösteriyordu (jurnalde binlerce
        // gerçek sinyal). kazanç (odul=6) zaten u.ok'a girdi; burada
        // yalnızca başarısız-ama-ileri adımlar sayılır.
        if (!k.dogru && k.odul > 0) u.zincir.ilerleme += 1;
        // deneme 1 = veri üretim adımı: çıktısı sayı olmadığından yargıcı
        // asla geçemez (yapısal). Zincirdeki per-attempt % bu yüzden ~%50
        // tavanına mahkum — dürüst ölçü = tamamlanan/başlatılan dizi.
        if ((k.deneme || 1) === 1) {
          u.zincir.baslatilan += 1;
          u.hedef[k.hedef].baslatilan =
            (u.hedef[k.hedef].baslatilan || 0) + 1;
        }
      }
      // Yalnızca bu hedefte tanımlı ve yargılanabilir komutlar ağ kapısıdır.
      const agSinif = agKomutSinifi(k.hedef, k.komut);
      if (agSinif === "ag") {
        const a = D.ag;
        ekle(a.kapi, k.komut || "?", !!k.dogru);
        ekle(a.hedef, k.hedef, !!k.dogru);
        a.son = [{ t: k.t, hedef: k.hedef, komut: k.komut,
          dogru: !!k.dogru, deneme: k.deneme,
          calisti: k.calisti, obs: k.obs || "" },
          ...a.son].slice(0, 10);
      } else if (agSinif === "diger") {
        const a = D.ag;
        ekle(a.diger, k.komut || "?", !!k.dogru);
        a.sonDiger = [{ t: k.t, hedef: k.hedef, komut: k.komut,
          dogru: !!k.dogru, deneme: k.deneme,
          calisti: k.calisti, obs: k.obs || "" },
          ...a.sonDiger].slice(0, 10);
      }
      u.sonKullan = [k, ...u.sonKullan].slice(0, 8);
      break;
    }
    case "birak": {
      const b = D.birak;
      b.n += 1;
      const d = String(Math.min(k.deneme || 0, 3));
      b.deneme[d] = (b.deneme[d] || 0) + 1;
      b.son = [k, ...b.son].slice(0, 5);
      break;
    }
    case "kullan_duraklama": {
      // Duraklama yalnızca hedefte tanımlı bir ağ komutunda ağ kanıtıdır.
      const a = D.ag;
      if (agKomutSinifi(k.hedef, k.komut) === "ag") {
        a.duraklama[k.komut || "?"] =
          (a.duraklama[k.komut || "?"] || 0) + 1;
        a.son = [{ t: k.t, hedef: k.hedef, komut: k.komut,
          deneme: k.deneme, duraklama: true,
          calisti: k.calisti, obs: k.obs || "" },
          ...a.son].slice(0, 10);
      }
      break;
    }
    case "merak": {
      // Sahne 1/2: atölye öz-ödül olayı — işlem dağılımı, toplam ödül,
      // son olaylar, dünya sağlığı serisi (canlı curiositi göstergesi)
      const m = D.merak;
      m.n += 1;
      m.odul += k.odul || 0;
      m.islem[k.islem] = (m.islem[k.islem] || 0) + 1;
      m.son = [{ t: k.t, islem: k.islem, surpriz: k.surpriz, odul: k.odul,
        saglik: k.saglik, nesne: k.nesne, obs: k.obs },
        ...m.son].slice(0, 8);
      seri(m.seri, k.t, k.saglik ?? 0);
      break;
    }
    case "uyku_basla":
      D.uyku.push({ t: k.t, ad: k.ad, veri: k.veri, kod: null });
      if (D.uyku.length > 16) D.uyku.splice(16);
      break;
    case "uyku_bitti": {
      const u = D.uyku;
      const son = u[u.length - 1];
      if (son) {
        son.kod = k.kod;
        son.sure = k.sure;
        son.ornek = k.ornek;
        son.soyutlasma = k.soyutlasma || 0;
      }
      D.konsolidasyon.push({ t: k.t, adet: k.soyutlasma || 0 });
      if (D.konsolidasyon.length > 20) D.konsolidasyon.splice(20);
      break;
    }
    case "calisma_bellek_konsolidasyon":
      D.konsolidasyon.push({ t: k.t, adet: k.adet || 0 });
      if (D.konsolidasyon.length > 20) D.konsolidasyon.splice(20);
      break;
    case "hata":
      D.hatalar.push({
        t: k.t, tur: k.tur, stim: k.stim, eylem: k.eylem,
        odul: k.odul, guven: k.guven,
      });
      if (D.hatalar.length > 20) D.hatalar.splice(20);
      break;
    case "neden":
      D.neden.push({
        t: k.t, eylem: k.eylem, guven: k.guven,
        ozellik_katkilari: k.ozellik_katkilari || [],
        gecmis_deneyim: k.gecmis_deneyim || null,
        dusunme_tahmini_odul: k.dusunme_tahmini_odul,
        dusunme_guven: k.dusunme_guven,
        tehlike_olasiligi: k.tehlike_olasiligi,
        tehlike_aciklama: k.tehlike_aciklama,
      });
      if (D.neden.length > 20) D.neden.splice(20);
      break;
    case "door_feedback_isle":
      D.disSal.push({ t: k.t, deger: k.deger });
      if (D.disSal.length > 20) D.disSal.splice(20);
      break;
    case "learn":
      if (typeof k.S === "number") {
        D.sikilma = k.S;
        seri(D.seriler.S, k.t, k.S);
      }
      // ---------- Yeni: Bu bilgisayarın bedeni (Aşama 8) ----------
      if (typeof k.insan_var === "boolean") D.beden.insan_var = k.insan_var;
      if (typeof k.sistem_saati === "number") D.beden.sistem_saati = k.sistem_saati;
      if (typeof k.disk_yuzde === "number") D.beden.disk_yuzde = k.disk_yuzde;
      if (typeof k.bellek_yuzde === "number") D.beden.bellek_yuzde = k.bellek_yuzde;
      // ---------- Yeni: USB — kernel seviyesinde (Aşama 10) ----------
      if (typeof k.usb_cihaz_sayisi === "number") D.usb.cihaz_sayisi = k.usb_cihaz_sayisi;
      if (typeof k.usb_node_sayisi === "number") D.usb.node_sayisi = k.usb_node_sayisi;
      if (typeof k.usb_keşif_bonusu === "number") D.usb.keşif_bonusu = k.usb_keşif_bonusu;
      // ---------- Yeni: Ruh hali / mood vektörü (Aşama 9) ----------
      if (typeof k.mood_mutluluk === "number") D.mood.mutluluk = k.mood_mutluluk;
      if (typeof k.mood_korku === "number") D.mood.korku = k.mood_korku;
      if (typeof k.mood_guven === "number") D.mood.guven = k.mood_guven;
      if (typeof k.mood_merak === "number") D.mood.merak = k.mood_merak;
      if (typeof k.mood_sikilma === "number") D.mood.sikilma = k.mood_sikilma;
      if (typeof k.mood_beden_baski === "number") D.mood.beden_baski = k.mood_beden_baski;
      if (typeof k.mood_dominant === "string") D.mood.dominant = k.mood_dominant;
      break;
    case "ders_uygulandi":
    case "ders_red":
      D.ders_islem.push({
        t: k.t, kind: k.kind, hedef: k.hedef,
        yanlis: k.yanlis, dogrusu: k.dogrusu, not_: k.not_,
      });
      if (D.ders_islem.length > 20) D.ders_islem.splice(20);
      break;
    case "uzuv_sinif":
      D.uzuvSon = k;
      break;
    case "birth":
      D.dogum = k.t;
      break;
    case "home_world":
      D.evren = k;
      break;
    case "surec_olcum":
      D.surec = {
        ...D.surec,
        ornek: k.ornek || D.surec.ornek,
        adet: k.surec_turu ?? D.surec.adet,
        son: k,
      };
      break;
    case "sleep":
      D.sonKapanis = k.t;
      break;
    case "act":
      D.sonAct = k;
      seri(D.seriler.E, k.t, k.E);
      seri(D.seriler.H, k.t, k.H);
      seri(D.seriler.R, k.t, k.R);
      break;
    case "ust_beyn_override": {
      const u = D.ust;
      const komut = k.komut || "?";
      const v = (u.override[komut] ||= { n: 0, model: 0, kesif: 0 });
      v.n += 1;
      if (k.kaynak === "kesif") v.kesif += 1; else v.model += 1;
      u.sonOverride = [{ t: k.t, komut: k.komut, idx: k.idx,
        guven: k.guven, kaynak: k.kaynak }, ...u.sonOverride].slice(0, 12);
      break;
    }
    case "ust_beyn_reddedildi":
    case "ust_beyn_reddedildi_sayac": {
      // Aynı olay iki kez düşüyor (reddedildi + sayac). Panoda tek
      // sayılması için yalnızca "_sayac" olayı sayılır.
      if (kind === "ust_beyn_reddedildi") break;
      const u = D.ust;
      const rk = `${k.komut || "?"}|${k.gerekce || "?"}`;
      u.red[rk] = (u.red[rk] || 0) + 1;
      u.redKomut[k.komut || "?"] = (u.redKomut[k.komut || "?"] || 0) + 1;
      u.sonRed = [{ t: k.t, komut: k.komut, gerekce: k.gerekce,
        guven: k.guven, kaynak: k.kaynak }, ...u.sonRed].slice(0, 12);
      break;
    }
    case "ust_beyn_sifirla": {
      const s = D.ust.sifirla;
      s.n += 1;
      s.budanan += k.budanan || 0;
      s.links = k.links || 0;
      s.ornek = [{ t: k.t, budanan: k.budanan, links: k.links },
        ...s.ornek].slice(0, 10);
      break;
    }
    default:
      break;
  }
}

/** Tam tarama (ilk açılış ya da jurnal dönüşü): sayaçlar sıfırlanır. */
function tamTara() {
  D = sifirla();
  offset = 0;
  artik = "";
  akis();
}

/** Akış taraması: yalnızca yeni baytlar (sn'lik döngüden çağrılır). */
const sonSatirlar = [];
function akis() {
  let buf;
  try {
    buf = fs.readFileSync(JOURNAL);
  } catch {
    return;                    // jurnal henüz yok
  }
  if (buf.length < offset) {   // döndü/arsivlendi → baştan
    tamTara();
    return;
  }
  if (buf.length === offset) return;
  const ham = artik + buf.subarray(offset).toString("utf-8");
  offset = buf.length;
  const parcalar = ham.split("\n");
  artik = parcalar.pop() || "";
  for (const s of parcalar) {
    if (!s.trim()) continue;
    try {
      const k = JSON.parse(s);
      isle(k);
      sonSatirlar.push(k);
    } catch {
      bozuk += 1;
    }
  }
}

let yayinci = () => {};
export function onYayin(fn) { yayinci = fn; }

/** İlk yükleme + saniyede bir akış; yeni satırları yayına verir. */
export function baslat() {
  tamTara();
  setInterval(() => {
    sonSatirlar.length = 0;
    try {
      akis();
    } catch (e) {
      console.error("jurnal tarama:", e.message);
    }
    if (sonSatirlar.length) {
      const y = sonSatirlar.splice(0, sonSatirlar.length);
      try { yayinci(y); } catch { /* pano kapalı olabilir */ }
    }
  }, 1000);
}
// ---------- yan dosyalar (salt okuma) ----------

function jsonOk(yol, yedek = null) {
  try {
    return JSON.parse(fs.readFileSync(yol, "utf-8"));
  } catch {
    return yedek;
  }
}

function dersSay() {
  try {
    const ham = fs.readFileSync(path.join(ROOT, "ders.jsonl"), "utf-8");
    const satirlar = ham.split("\n").filter((s) => s.trim());
    let acik = 0, bekleyen = 0, islenmis = 0;
    for (const s of satirlar) {
      if (s.includes("|ok=")) islenmis += 1;
      else if (s.includes("|dogrusu=")) bekleyen += 1;
      else acik += 1;
    }
    return { toplam: satirlar.length, acik, bekleyen, islenmis };
  } catch {
    return { toplam: 0, acik: 0, bekleyen: 0, islenmis: 0 };
  }
}

/** İnsanın göreceği açık satır örnekleri (son N). */
export function dersOrnekleri(n = 8) {
  try {
    const ham = fs.readFileSync(path.join(ROOT, "ders.jsonl"), "utf-8");
    return ham.split("\n").filter((s) => s.trim()
      && !s.includes("|ok=") && !s.includes("|dogrusu=")).slice(0, n);
  } catch {
    return [];
  }
}

/** Anlık durum paketi (panonun tek JSON'u). */
export function durum() {
  const brain = jsonOk(path.join(ROOT, "zeka", "brain.json"), { links: [] });
  const guclu = [...(brain.links || [])]
    .sort((a, b) => Math.abs(b[2]) - Math.abs(a[2])).slice(0, 10)
    .map(([stim, action, w]) => ({ stim, action, w: Math.round(w * 100) / 100 }));
  const uyku = jsonOk(path.join(ROOT, "zeka", "uyku.json"), { son: {} });
  const uzuv = jsonOk(path.join(ROOT, "zeka", "uzuv.json"), null);
  const durumUzuv = jsonOk(path.join(ROOT, "zeka", "uzuv_durum.json"), null);
  const surec = jsonOk(path.join(ROOT, "zeka", "surec.json"), {});
  const damak = jsonOk(path.join(ROOT, "zeka", "damak.json"), {});
  const agBeyin = jsonOk(path.join(ROOT, "zeka", "ag_beyin.json"), null);
  const usbBeyin = jsonOk(path.join(ROOT, "zeka", "usb.json"), null);
  const nnUsb = jsonOk(path.join(ROOT, "zeka", "nn_usb.json"), null);
  const nnAg = jsonOk(path.join(ROOT, "zeka", "nn_ag.json"), null);
  const nnAna = jsonOk(path.join(ROOT, "zeka", "nn_ana.json"), null);
  const cfg = jsonOk(path.join(ROOT, "body.json"), {});
  const komutTehlike = jsonOk(
    path.join(ROOT, "zeka", "komut_tehlike.json"), {});
  const kapanis = D.sonKapanis > D.dogum;
  const actT = D.sonAct?.t || 0;

  const nowSec = Date.now() / 1000;
  // Geçerli unix zamanı mı? (yaklaşık 1 milyar üzeri; 1126 gibi tik sayacı değil)
  // Eğer tik sayacıysa (küçük pozitif sayı), eylem şimdi yapılmış sayılır.
  const gecerliZaman = actT > 1000000000;
  const actUnix = gecerliZaman ? actT : (actT > 0 ? nowSec : 0);
  const sonEtkinlikS = actT > 0 ? nowSec - actUnix : null;
  const staleSec = sonEtkinlikS == null ? Number.POSITIVE_INFINITY : sonEtkinlikS;
  const waiting = D.toplam === 0 && !D.dogum && !D.sonAct;
  const bozukUyari = bozuk > 0 ? [`${bozuk} bozuk satır tespit edildi`] : [];
  const staleUyari = staleSec > 180 ? ["son etkinlik çok eski; veri stale"] : [];
  const dogumUyari = !D.dogum && !waiting ? ["doğum bilgisi eksik"] : [];
  const agNow = Date.now() / 1000;
  const agScans = (agBeyin?.scans || []).filter((scan) =>
    Number.isFinite(scan.t) && agNow - scan.t < 86400);
  const agScanTimes = agScans.map((scan) => scan.t).sort((a, b) => a - b);
  const agNextScan = !agScanTimes.length ? 0
    : agScanTimes.length >= 5
      ? Math.max(0, agScanTimes[0] + 86400 - agNow)
      : Math.max(0, agScanTimes[agScanTimes.length - 1] + 86400 / 5 - agNow);
  const agDevicesAll = Object.entries(agBeyin?.devices || {})
    .map(([ip, device]) => ({
      ip,
      online: !!device.online,
      seen_count: device.seen_count || 0,
      last_seen: device.last_seen || null,
      hints: device.hints || [],
      hostname: device.hostname || null,
      classification_note: device.classification_note || "",
      services: Object.entries(device.services || {}).map(([type, evidence]) => ({
        type,
        instance: evidence.instance || "",
        seen_count: evidence.seen_count || 0,
        last_seen: evidence.last_seen || null,
      })),
      ports: Object.entries(device.ports || {}).map(([port, evidence]) => {
        const info = agBeyin?.ports?.[port] || {};
        return {
          port,
          name: info.name || "Bilinmeyen",
          purpose: info.purpose || "Kayitli acik TCP portu",
          seen_count: evidence.seen_count || 0,
          last_seen: evidence.last_seen || null,
        };
      }).sort((a, b) => a.port.localeCompare(b.port)),
    }))
    .sort((a, b) => (b.last_seen || 0) - (a.last_seen || 0));
  // Web panelde çok uzun listeye neden olmamak için sadece son 20 cihaz gösterilir.
  const AG_WEB_DEVICE_LIMIT = 20;
  const agDevices = agDevicesAll.slice(0, AG_WEB_DEVICE_LIMIT);
  const sistem = {
    durum: waiting ? "bekleniyor" : (bozuk > 0 || staleSec > 180 || (!D.dogum && !waiting)) ? "degraded" : "güvenilir",
    integrity: bozuk > 0 ? "uyumsuz" : (staleSec > 180 ? "eski" : "güvenilir"),
    stale: staleSec > 180,
    bozuk_satir: bozuk,
    son_etkinlik_s: sonEtkinlikS,
    uyari: [...bozukUyari, ...staleUyari, ...dogumUyari],
  };

  return {
    simdi: nowSec,
    sistem,
    canli: {
      ad: cfg.identity?.name || "core",
      uyariyor: actT > 0 && !kapanis,
      son_act_s: sonEtkinlikS != null ? Math.round(sonEtkinlikS) : null,
      dogum: D.dogum,
      uptime_s: D.dogum ? Math.round(nowSec - D.dogum) : null,
      act: D.sonAct,
      sikilma: D.sikilma,
      ticks_s: cfg.metabolism?.tick_seconds ?? null,
      // ---------- Yeni: Bu bilgisayarın bedeni (Aşama 8) ----------
      beden: D.beden,
      // ---------- Yeni: Ruh hali / mood vektörü (Aşama 9) ----------
      mood: D.mood,
      // ---------- Yeni: USB — kernel seviyesinde (Aşama 10) ----------
      usb: D.usb,
      // ---------- Yeni: USB beyni (Aşama USB-Beyn) ----------
      usb_beyni: usbBeyin ? {
        toplam_cihaz: usbBeyin.toplam_cihaz || 0,
        yeni_cihaz_sayisi: usbBeyin.yeni_cihaz_sayisi || 0,
        son_etkinlik: usbBeyin.son_etkinlik || 0,
        cihaz_sayisi: Object.keys(usbBeyin.cihazlar || {}).length,
        cihazlar: Object.entries(usbBeyin.cihazlar || {})
          .map(([adres, c]) => ({
            adres,
            vendor: c.vendor || "?",
            product: c.product || "?",
            manufacturer: c.manufacturer || "",
            product_name: c.product_name || "",
            gorulenme_sayisi: c.gorulenme_sayisi || 0,
            durum: c.durum || "bilinik",
            son_gorunme: c.son_gorunme || null,
          }))
          .sort((a, b) => (b.son_gorunme || 0) - (a.son_gorunme || 0))
          .slice(0, 20),
      } : null,
      // ---------- Yeni: Nöral beyinler (kanal bazlı öğrenme) ----------
      nn_usb: nnUsb ? {
        ad: nnUsb.ad,
        katmanlar: nnUsb.katmanlar,
        lr: nnUsb.lr,
        son_mse: nnUsb.son_mse || 0,
        öğrenme_sayısı: nnUsb.öğrenme_sayısı || 0,
      } : null,
      nn_ag: nnAg ? {
        ad: nnAg.ad,
        katmanlar: nnAg.katmanlar,
        lr: nnAg.lr,
        son_mse: nnAg.son_mse || 0,
        öğrenme_sayısı: nnAg.öğrenme_sayısı || 0,
      } : null,
      nn_ana: nnAna ? {
        ad: nnAna.ad,
        katmanlar: nnAna.katmanlar,
        lr: nnAna.lr,
        son_mse: nnAna.son_mse || 0,
        öğrenme_sayısı: nnAna.öğrenme_sayısı || 0,
      } : null,
    },
    kullan: {
      n: D.kullan.n, ok: D.kullan.ok,
      deneme: D.kullan.deneme,
      hedefler: Object.entries(D.kullan.hedef)
        .map(([tip, v]) => ({ tip, ...v }))
        .sort((a, b) => b.n - a.n).slice(0, 8),
      zincir: D.kullan.zincir,
      oran: D.kullan.n ? D.kullan.ok / D.kullan.n : 0,
      zincir_oran: D.kullan.zincir.n
        ? D.kullan.zincir.ok / D.kullan.zincir.n : 0,
      son: D.kullan.sonKullan,
    },
    birak: D.birak,
    uyku: D.uyku.slice(-10).reverse(),
    uyku_durum: uyku.son || {},
    hatalar: D.hatalar,
    ders_islem: D.ders_islem,
    ders: dersSay(),
    beyin: { baglanti: (brain.links || []).length, guclu },
    komut_help: komutTehlike.help_aciklamalar || {},
    komut_ciktilari: komutTehlike.komut_ciktilari || {},
    uzuv: {
      model: uzuv ? { siniflar: uzuv.siniflar, ornek: uzuv.ornek,
        toplam: uzuv.toplam } : null,
      durum: durumUzuv,
      son: D.uzuvSon,
    },
    evren: D.evren,
    surec: {
      ornek: D.surec.ornek || surec.ornek || 0,
      adet: D.surec.adet
        || (surec.adet ? Object.keys(surec.adet).length : 0),
      son: D.surec.son || surec.son_olcum || null,
      profiller: surec.profiller || {},
      gecmis: surec.gecmis || [],
    },
    ag_beyin: agBeyin ? {
      schedule: {
        limit_per_24h: 5,
        attempts_in_24h: agScanTimes.length,
        next_in_seconds: agNextScan,
      },
      device_count: agDevices.length,
      online_count: agDevices.filter((device) => device.online).length,
      devices: agDevices,
      tools: Object.values(agBeyin.tools || {}),
      skills: agBeyin.skills || {},
      probe_learning: agBeyin.probe_learning || {},
      reference_learning: agBeyin.reference_learning || {},
      social_learning: agBeyin.social_learning || { enabled: false, peers: [] },
      consolidation: agBeyin.consolidation || {},
      port_knowledge: Object.entries(agBeyin.ports || {})
        .map(([port, info]) => ({ port, ...info }))
        .sort((a, b) => a.port.localeCompare(b.port)),
      last_scan: agBeyin.last_scan || null,
    } : null,
    damak: { samples: damak.samples || 0 },
    // Atölye (Sahne 0-2): canlı dünya durumu (kalıcı .durum.json'dan anlık
    // okuma — jurnal değil, dosyanın kendisi) + merak ekonomisi
    atolye: (() => {
      const durumJson = jsonOk(
        path.join(ROOT, "world", "atolye", ".durum.json"), {});
      let nesne = 0, arac = 0, kuvvet = 0, bozuk = 0;
      for (const v of Object.values(durumJson || {})) {
        nesne += 1;
        if (v.bozuk) bozuk += 1;
        if (v.tur === "arac" && (v.kuvvet || 0) > 0 && !v.bozuk) {
          arac += 1; kuvvet += v.kuvvet;
        }
      }
      return {
        nesne, arac, kuvvet, bozuk,
        saglik: nesne ? (nesne - bozuk) / nesne : 0,
        merak_n: D.merak.n,
        merak_odul: Math.round(D.merak.odul * 10) / 10,
        islem: D.merak.islem,
        son: D.merak.son,
        seri: D.merak.seri,
      };
    })(),
    // Ağ keşfi (AG_TARA/BENI_TARA): jurnal kanıtı kapı performansı +
    // kapsam dosyasının anlık hali (salt okuma, yönetim ayrı uçta)
    ag: (() => {
      const a = D.ag;
      const kapsam = jsonOk(path.join(ROOT, "ag_kapsam.json"), null);
      const kapi = Object.entries(a.kapi)
        .map(([komut, v]) => ({ komut, ...v,
          oran: v.n ? v.ok / v.n : 0,
          duraklama: a.duraklama[komut] || 0 }))
        .sort((x, y) => y.n - x.n);
      const n = kapi.reduce((s, v) => s + v.n, 0);
      const ok = kapi.reduce((s, v) => s + v.ok, 0);
      return {
        kapsam: kapsam && {
          acik: !!kapsam.acik,
          izin_aglari: Array.isArray(kapsam.izin_aglari)
            ? kapsam.izin_aglari : [],
          ben_tarama: !!kapsam.ben_tarama,
          ben_http_port: kapsam.ben_http_port ?? null,
          ben_zaman_asimi: kapsam.ben_zaman_asimi ?? null,
          ayni_hedef_aralik_sn: kapsam.ayni_hedef_aralik_sn ?? null,
        },
        kapi,
        toplam: { n, ok, oran: n ? ok / n : 0 },
        hedef: Object.entries(a.hedef)
          .map(([tip, v]) => ({ tip, ...v, oran: v.n ? v.ok / v.n : 0 })),
        diger: Object.entries(a.diger)
          .map(([komut, v]) => ({ komut, ...v,
            oran: v.n ? v.ok / v.n : 0 }))
          .sort((x, y) => y.n - x.n),
        sonDiger: a.sonDiger,
        duraklama: Object.values(a.duraklama).reduce((s, x) => s + x, 0),
        son: a.son,
      };
    })(),
    // Üst beyin: model dosyası (zeka/ust_beyn.json) + canlı günlük
    // istatistikleri. Kanıt/doğrulama eşikleri panelde "neden reddedildi"
    // sorusunun cevabıdır.
    ust_beyn: (() => {
      const m = jsonOk(path.join(ROOT, "zeka", "ust_beyn.json"), {});
      const u = D.ust;
      const secim = m.secim_sayilari || [];
      const redToplam = Object.values(u.redKomut)
        .reduce((s, x) => s + x, 0);
      const ovToplam = Object.values(u.override)
        .reduce((s, v) => s + v.n, 0);
      return {
        komutlar: UST_KOMUTLAR,
        model: {
          surum: m.surum ?? 0,
          samples: m.samples ?? 0,
          tik: m.tik ?? 0,
          epsilon: m.epsilon ?? 0,
          guven_esigi: m.guven_esigi ?? 0,
          dogrulama_esigi: m.dogrulama_esigi ?? 0,
          marj_olcek: m.marj_olcek ?? 0,
          kanit_carpani: m["kanit_çarpani"] ?? m.kanit_carpani ?? 0,
          sure_azami: m.sure_azami ?? 0,
          reddedilen: m.reddedilen ?? 0,
          dogrulama: m.dogrulama || [],
          dogrulama_baglam: m.dogrulama_baglam || {},
          secim: secim,
        },
        canli: {
          override: Object.entries(u.override)
            .map(([komut, v]) => ({ komut, ...v }))
            .sort((a, b) => b.n - a.n),
          red: Object.entries(u.red)
            .map(([anahtar, n]) => {
              const [komut, gerekce] = anahtar.split("|");
              return { komut, gerekce, n };
            })
            .sort((a, b) => b.n - a.n),
          redKomut: u.redKomut,
          red_toplam: redToplam,
          override_toplam: ovToplam,
          son_override: u.sonOverride,
          son_red: u.sonRed,
          sifirla: {
            ...u.sifirla,
            ort_budanan: u.sifirla.n
              ? u.sifirla.budanan / u.sifirla.n : 0,
          },
        },
      };
    })(),
    sayac: D.sayac,
    seriler: D.seriler,
    toplam_satir: D.toplam,
    bozuk,
    neden: D.neden,
    disSal: D.disSal,
    konsolidasyon: D.konsolidasyon,
  };
}

export function halkaSon(n = 150) {
  return D.ring.slice(-n).reverse();
}
