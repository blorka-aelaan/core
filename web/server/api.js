// CORE pano — API (Vite middleware).
// Salt okuma uçları + yönetim: kapı (door TCP), servis sinyalleri,
// uzuv etiketi, ders toplu düzeltme. Organizmaya asla dosya yazmaz;
// yazma işlemleri kendi Python araçlarıyla (uzuv.py / ders.py) olur.
import net from "node:net";
import { execFile } from "node:child_process";
import {
  ROOT, baslat, onYayin, durum, halkaSon, dersOrnekleri,
} from "./veri.js";

const DOOR = { host: "127.0.0.1", port: 5777 };
const kiler = new Set();
let kuruldu = false;

function json(res, kod, veri) {
  res.writeHead(kod, { "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store" });
  res.end(JSON.stringify(veri));
}

function govde(req) {
  return new Promise((resolve) => {
    let t = "";
    req.on("data", (c) => {
      t += c;
      if (t.length > 8192) { req.destroy(); resolve(null); }
    });
    req.on("end", () => {
      try { resolve(JSON.parse(t || "{}")); } catch { resolve(null); }
    });
    req.on("error", () => resolve(null));
  });
}

function calistir(komut, argumanlar, zaman = 15000) {
  return new Promise((resolve) => {
    execFile(komut, argumanlar,
      { cwd: ROOT, timeout: zaman, maxBuffer: 1024 * 1024 },
      (hata, stdout, stderr) => resolve({
        kod: hata ? (hata.code || 1) : 0,
        cikti: (stdout || stderr || String(hata?.message || "")).trim(),
      }));
  });
}

// ---------- servisler (systemd, 4 sn önbellek) ----------
let servisOnbellek = { t: 0, veri: null };
async function servisler() {
  if (servisOnbellek.veri && Date.now() - servisOnbellek.t < 4000) {
    return servisOnbellek.veri;
  }
  const v = {};
  await Promise.all([
    ["organizma", "core-organizma.service"],
    ["ag", "core-ag.service"],
  ].map(async ([ad, b]) => {
    const [a, p] = await Promise.all([
      calistir("systemctl", ["is-active", b], 4000),
      calistir("systemctl", ["show", "-p", "MainPID", "--value", b], 4000),
    ]);
    const pid = parseInt(p.cikti, 10) || 0;
    let uptime_s = null;
    if (pid > 0) {
      // ps etimes: süreç başlangıcından bu yana saniye (işletim sistemi
      // hükmü — jurnal döndüğünde birth olayı arşive gider, D.dogum sıfırlanır)
      const e = await calistir("ps", ["-o", "etimes=", "-p", String(pid)], 4000);
      uptime_s = parseInt(e.cikti, 10) || null;
    }
    v[ad] = { aktif: a.cikti === "active", durum: a.cikti || "?",
      pid, uptime_s };
  }));
  servisOnbellek = { t: Date.now(), veri: v };
  return v;
}

async function tamDurum() {
  const d = durum();
  const s = await servisler();
  // uptime'i ana sürecin başlangıcından türet (D.dogum jurnal dönüşünde
  // kaybolabilir; sistem hükmü daha güvenilir).
  const up = s.organizma && typeof s.organizma.uptime_s === "number"
    ? s.organizma.uptime_s : null;
  if (up != null && d.canli) d.canli.uptime_s = up;
  return { ...d, servisler: s };
}

// ---------- kapı (door.py TCP protokolü) ----------
function kapiGonder(mesaj) {
  return new Promise((resolve) => {
    const s = net.connect(DOOR, () => s.write(mesaj + "\n"));
    let cevap = "";
    let bitti = false;
    const bitir = (sonuc) => {
      if (bitti) return;
      bitti = true;
      try { s.destroy(); } catch { /* yoksay */ }
      resolve(sonuc);
    };
    setTimeout(() => bitir({ ok: false, cevap: "kapı zaman aşımı" }), 4000);
    s.on("data", (c) => {
      cevap += c;
      if (cevap.includes("\n")) {
        try {
          bitir({ ok: true, durum: JSON.parse(cevap) });
        } catch {
          bitir({ ok: true, cevap: cevap.trim() });
        }
      }
    });
    s.on("error", (e) => bitir({ ok: false, cevap: e.message }));
    s.on("close", () => bitir({ ok: !!cevap,
      cevap: cevap.trim() || "kapı kapandı (yanıt yok)" }));
  });
}

function kapiDogrula(msg) {
  if (typeof msg !== "string" || !msg.trim() || msg.length > 300) return null;
  if (/[\r\n]/.test(msg)) return null;
  if (msg.startsWith("shock:")) {
    const n = parseFloat(msg.slice(6).replace(",", "."));
    if (!Number.isFinite(n) || n < 0 || n > 200) return null;
    return "shock:" + n;
  }
  if (msg.startsWith("gorev:")) {
    const yol = msg.slice(6).trim();
    if (!/^[A-Za-z0-9._/\- ]{1,200}$/.test(yol)) return null;
    return "gorev:" + yol;
  }
  if (msg === "ac") return "ac";
  return msg.trim();  // serbest tık (door_inbox + kıvılcım)
}

// ---------- yönetim: temiz yeniden başlatma ----------
const YONETIM = {
  restart_main: {
    arg: ["kill", "-s", "SIGINT", "core-organizma.service"],
    not: "SIGINT → temiz kapanış (beyin+surec+damak kaydı) → systemd "
       + "10 sn içinde geri getirir",
  },
  restart_ag: {
    arg: ["kill", "-s", "SIGTERM", "core-ag.service"],
    not: "SIGTERM → ag döngü sonunda kapanır → systemd geri getirir",
  },
};

// ---------- SSE canlı akış ----------
function sse(res, olay, veri) {
  res.write("event: " + olay + "\n");
  res.write("data: " + JSON.stringify(veri) + "\n\n");
}

function akisBaslat(req, res) {
  res.writeHead(200, { "Content-Type": "text/event-stream",
    "Cache-Control": "no-store", Connection: "keep-alive" });
  res.write("retry: 2000\n\n");
  kiler.add(res);
  const nabiz = setInterval(() => res.write(": nabız\n\n"), 20000);
  req.on("close", () => {
    clearInterval(nabiz);
    kiler.delete(res);
  });
  sse(res, "feed", halkaSon(150));
  tamDurum().then((d) => sse(res, "state", d)).catch(() => {});
}

function yayinla(satirlar) {
  for (const res of kiler) sse(res, "journal", satirlar);
}

async function yayinDurum() {
  if (!kiler.size) return;
  try {
    const d = await tamDurum();
    for (const res of kiler) sse(res, "state", d);
  } catch { /* yoksay */ }
}

export function coreApi() {
  return {
    name: "core-api",
    configureServer(server) {
      if (!kuruldu) {
        baslat();
        onYayin(yayinla);
        setInterval(yayinDurum, 5000);
        kuruldu = true;
      }
      server.middlewares.use("/api", (req, res) => {
        rota(req, res).catch((e) => json(res, 500, { hata: String(e.message || e) }));
      });
    },
  };
}
async function rota(req, res) {
  const url = new URL(req.url || "/", "http://pano");
  const y = url.pathname.replace(/\/$/, "") || "/";
  const mt = req.method || "GET";

  if (mt === "GET" && y === "/state") {
    return json(res, 200, await tamDurum());
  }
  if (mt === "GET" && y === "/feed") {
    const n = Math.min(parseInt(url.searchParams.get("n") || "150", 10), 500);
    return json(res, 200, halkaSon(n));
  }
  if (mt === "GET" && y === "/stream") {
    return akisBaslat(req, res);
  }
  if (mt === "GET" && y === "/ders/acik") {
    const d = durum();
    return json(res, 200, { sayi: d.ders, ornekler: dersOrnekleri(8) });
  }
  if (mt === "GET" && y === "/uzuv/liste") {
    if (!uzuvOnbellek.satirlar || Date.now() - uzuvOnbellek.t > 60000) {
      const r = await calistir("python3",
        ["uzuv.py", "listele", "--json"], 25000);
      try {
        uzuvOnbellek = { t: Date.now(), satirlar: JSON.parse(r.cikti) };
      } catch {
        return json(res, 500,
          { hata: (r.cikti || "listele başarısız").slice(0, 500) });
      }
    }
    return json(res, 200, { satirlar: uzuvOnbellek.satirlar });
  }

  if (mt === "POST" && y === "/door") {
    const b = await govde(req);
    const mesaj = kapiDogrula(b?.msg ?? "");
    if (!mesaj) {
      return json(res, 400, { hata: "geçersiz kapı mesajı (boş/uzun/şüpheli)" });
    }
    const cevap = await kapiGonder(mesaj);
    return json(res, 200, cevap);
  }

  if (mt === "POST" && y === "/manage") {
    const b = await govde(req);
    const plan = YONETIM[b?.action ?? ""];
    if (!plan) {
      return json(res, 400, { hata: "bilinmeyen eylem",
        izinli: Object.keys(YONETIM) });
    }
    const r = await calistir("sudo", ["-n", "systemctl", ...plan.arg], 8000);
    servisOnbellek.t = 0;  // önbelleği boşalt
    return json(res, r.kod === 0 ? 200 : 500,
      { ok: r.kod === 0, not: plan.not, cikti: r.cikti.slice(0, 500) });
  }

  if (mt === "POST" && y === "/uzuv/etiket") {
    const b = await govde(req);
    const metin = (b?.metin || "").trim();
    if (!/^[A-Za-z0-9._\-*]+\s+\S+\s+\|sinif=(govde|guvenli|bilinmeyen|tehlikeli)$/
        .test(metin)) {
      return json(res, 400, {
        hata: 'biçim: "comm exe |sinif=guvenli|govde|bilinmeyen|tehlikeli"',
      });
    }
    const r = await calistir("python3", ["uzuv.py", "etiketle", metin]);
    return json(res, r.kod === 0 ? 200 : 500,
      { ok: r.kod === 0, cikti: r.cikti.slice(0, 1000) });
  }

  if (mt === "POST" && y === "/ders") {
    const b = await govde(req);
    const hedef = (b?.hedef || "").trim();
    const dogrusu = (b?.dogrusu || "").trim();
    if (!/^[A-Za-z0-9_]{1,40}$/.test(hedef)
        || !dogrusu
        || !dogrusu.split(",").every((s) => /^cmd:[a-z0-9._\-]{1,30}$/.test(s))) {
      return json(res, 400, {
        hata: "biçim: hedef=PAKET_SOR, dogrusu=cmd:wc,cmd:head",
      });
    }
    const kod = "import sys; import ders; print(ders.toplu("
      + "sys.argv[1], sys.argv[2]))";
    const r = await calistir("python3", ["-c", kod, hedef, dogrusu]);
    return json(res, r.kod === 0 ? 200 : 500,
      { ok: r.kod === 0, islenen: r.cikti.trim(), hedef, dogrusu });
  }

  return json(res, 404, { hata: "bilinmeyen uç", yol: y });
}

let uzuvOnbellek = { t: 0, satirlar: null };

