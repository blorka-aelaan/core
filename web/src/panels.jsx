import { useEffect, useState } from "react";

// ---------- yardımcılar ----------
export async function al(yol, secenek) {
  const r = await fetch("/api" + yol, secenek);
  return r.json();
}
export async function post(yol, govde) {
  return al(yol, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(govde) });
}
export function yuzde(x) { return Math.round((x || 0) * 1000) / 10; }

export function sure(sn) {
  if (sn == null) return "—";
  const g = Math.floor(sn / 86400), s = Math.floor((sn % 86400) / 3600),
    dk = Math.floor((sn % 3600) / 60), s2 = Math.floor(sn % 60);
  if (g) return g + "g " + s + "sa";
  if (s) return s + "sa " + dk + "dk";
  if (dk) return dk + "dk " + s2 + "sn";
  return s2 + "sn";
}

export function saat(t) {
  if (!t) return "—";
  return new Date(t * 1000).toLocaleTimeString("tr-TR", { hour12: false });
}

export function onceki(t) {
  if (!t) return "—";
  const sn = Math.max(0, Date.now() / 1000 - t);
  if (sn < 90) return Math.round(sn) + " sn önce";
  if (sn < 5400) return Math.round(sn / 60) + " dk önce";
  if (sn < 172800) return Math.round(sn / 3600) + " sa önce";
  return Math.round(sn / 86400) + " gün önce";
}

export function Cubuk({ etiket, deger, maks, renk, sag }) {
  const o = maks ? Math.max(0, Math.min(100, (deger / maks) * 100)) : 0;
  return (
    <div className="cubuk">
      <div className="et"><span>{etiket}</span><span>{sag}</span></div>
      <div className="ray">
        <div className="dolgu" style={{ width: o + "%", background: renk }} />
      </div>
    </div>
  );
}

export function Spark({ ad, seri, renk }) {
  if (!seri || seri.length < 2) {
    return <div className="spark-bas"><span>{ad}</span><span>veri yok</span></div>;
  }
  const vler = seri.map(([, v]) => v);
  const min = Math.min(...vler), max = Math.max(...vler);
  const ar = (max - min) || 1, n = vler.length;
  const yol = vler.map((v, i) =>
    `${(i / (n - 1)) * 100},${100 - ((v - min) / ar) * 100}`).join(" ");
  return (
    <div>
      <div className="spark-bas">
        <span>{ad}</span><span>{min.toFixed(1)} … {max.toFixed(1)}</span>
      </div>
      <svg className="spark" viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline points={yol} fill="none" stroke={renk} strokeWidth="1.5"
          vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

// ---------- vital ----------
export function Vital({ d }) {
  if (!d) {
    return <div className="kart"><h2>Vital</h2>
      <div className="not11 soluk">yükleniyor…</div></div>;
  }
  const c = d.canli, a = c.act || {};
  const e = a.E ?? 0, h = a.H ?? 0, s = c.sikilma ?? 0;
  return (
    <div className="kart">
      <h2>Vital<span className="yan">
        {c.uyariyor ? "yaşıyor" : "sessiz"}</span></h2>
      <div className="istat">
        <div><div className="sayi">{sure(c.uptime_s)}</div>
          <div className="alt">ÇALIŞMA SÜRESİ</div></div>
        <div><div className="sayi">{a.E ?? "—"}</div>
          <div className="alt">ENERJİ</div></div>
        <div><div className="sayi">{a.H ?? "—"}</div>
          <div className="alt">AÇLIK</div></div>
        <div><div className="sayi">{a.R ?? "—"}</div>
          <div className="alt">SON ÖDÜL</div></div>
        <div><div className="sayi">{s.toFixed(2)}</div>
          <div className="alt">SIKILMA (S)</div></div>
      </div>
      <Cubuk etiket="enerji" deger={e} maks={150}
        renk={e < 30 ? "var(--kirmizi)" : "var(--yesil)"}
        sag={e + " / 150"} />
      <Cubuk etiket="açlık" deger={h} maks={100} renk="var(--turuncu)"
        sag={h + " / 100"} />
      <Cubuk etiket="sıkılma" deger={s} maks={1} renk="var(--mor)"
        sag={s.toFixed(2)} />
      <div className="not11 soluk">
        son eylem ({saat(a.t)}): <b>{a.action}</b> —
        {" "}{String(a.obs || "").slice(0, 90)}
      </div>
      <div className="not11 soluk">
        son nabız: {c.son_act_s ?? "—"} sn önce
        {c.ticks_s ? ` · tik ≈ ${c.ticks_s} sn` : ""}
        {d.beyin?.baglanti ? ` · beyin: ${d.beyin.baglanti} bağlantı` : ""}
      </div>
    </div>
  );
}
// ---------- öğrenme / komut kullanımı ----------
export function Kullan({ d }) {
  const k = d.kullan;
  return (
    <div className="kart">
      <h2>Öğrenme — komut kullanımı
        <span className="yan">{k.n} deneme · %{yuzde(k.oran)}</span></h2>
      <div className="istat">
        <div><div className="sayi">%{yuzde(k.oran)}</div>
          <div className="alt">BAŞARI (tümü)</div></div>
        <div><div className="sayi">%{yuzde(k.zincir.baslatilan
          ? k.zincir.ok / k.zincir.baslatilan
          : d.kullan?.zincir_oran)}</div>
          <div className="alt">ZİNCİR TAMAM</div></div>
        <div><div className="sayi">{k.zincir.ilerleme}</div>
          <div className="alt">ARA VERİ ADIMI</div></div>
        <div><div className="sayi">{d.birak.n}</div>
          <div className="alt">İNKÂR (bırak)</div></div>
      </div>
      {["1", "2", "3"].map((x) => {
        const v = k.deneme[x];
        if (!v) return null;
        const renk = x === "1" ? "var(--yesil)"
          : x === "2" ? "var(--sari)" : "var(--kirmizi)";
        return <Cubuk key={x}
          etiket={"deneme " + (x === "3" ? "3+" : x)}
          deger={v.ok} maks={v.n} renk={renk}
          sag={`${v.ok}/${v.n} · %${yuzde(v.ok / v.n)}`} />;
      })}
      <table>
        <thead>
          <tr><th>hedef tipi</th><th className="sag">deneme</th>
            <th className="sag">doğru</th></tr>
        </thead>
        <tbody>
          {k.hedefler.map((h) => (
            <tr key={h.tip}>
              <td>{h.tip}</td>
              <td className="sag">{h.n}</td>
              <td className="sag">%{yuzde(h.baslatilan
                ? h.ok / h.baslatilan : h.ok / h.n)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="not11 soluk" style={{ marginTop: 4 }}>
        zincir hedefleri (SUREC_SAY, DOSYA_SAY): deneme 1 veri üretim
        adımıdır, sayılamaz — oran = tamamlanan / başlatılan
      </div>
      {(k.son || []).length > 0 && (
        <div className="not11 soluk" style={{ marginTop: 6 }}>
          son denemeler: {(k.son || []).slice(0, 4)
            .map((s) => `${s.komut}${s.dogru ? " ✓" : " ✗"}`).join(" · ")}
        </div>
      )}
      {d.birak.n > 0 && (
        <div className="not11 soluk">
          bırak dağılımı: {Object.entries(d.birak.deneme)
            .map(([z, n]) => `deneme${z}=${n}`).join(" · ")}
        </div>
      )}
    </div>
  );
}

// ---------- beyin ----------
export function Beyin({ d }) {
  const b = d.beyin, s = d.seriler;
  return (
    <div className="kart">
      <h2>Beyin<span className="yan">{b.baglanti} bağlantı</span></h2>
      <Spark ad="sıkılma (S) — son ~150 learn" seri={s.S} renk="#b18cff" />
      <Spark ad="enerji (E)" seri={s.E} renk="#3ddc84" />
      <Spark ad="ödül (R)" seri={s.R} renk="#4ea1ff" />
      <table>
        <thead><tr><th>en güçlü bağlantılar</th><th className="sag">w</th></tr></thead>
        <tbody>
          {b.guclu.map((g, i) => (
            <tr key={i}>
              <td><span className="kisa" title={g.stim}>{g.stim}</span>
                {" → "}<b>{g.action}</b></td>
              <td className="sag">{g.w}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------- uyku ----------
export function Uyku({ d }) {
  const olaylar = d.uyku || [];
  const hatlar = Object.entries(d.uyku_durum || {});
  return (
    <div className="kart">
      <h2>Uyku (konsolidasyon)
        <span className="yan">{olaylar.length} son uyku</span></h2>
      <table>
        <thead><tr><th>hat</th><th className="sag">veri</th>
          <th className="sag">süre</th><th className="sag">durum</th></tr></thead>
        <tbody>
          {olaylar.map((o, i) => (
            <tr key={i}>
              <td><b>{o.ad}</b> <span className="not11 soluk">{saat(o.t)}</span></td>
              <td className="sag">{o.veri ?? "—"}</td>
              <td className="sag">{o.sure != null ? o.sure + " sn" : "…"}</td>
              <td className="sag">
                {o.kod == null
                  ? <span className="rozet uyari">uyuyor</span>
                  : o.kod === 0
                    ? <span className="rozet ok">
                        tamam{o.ornek != null ? ` · ${o.ornek} örnek` : ""}</span>
                    : <span className="rozet kotu">hata {o.kod}</span>}
              </td>
            </tr>
          ))}
          {!olaylar.length && (
            <tr><td colSpan={4} className="not11 soluk">
              henüz uyku yok (jurnalde)</td></tr>)}
        </tbody>
      </table>
      <div className="not11 soluk" style={{ marginTop: 8 }}>
        model tazeliği:
        {hatlar.map(([ad, v]) => (
          <span key={ad} className="rozet"
            style={{ marginLeft: 5 }}
            title={`son: ${new Date(v.t * 1000).toLocaleString("tr-TR")}`}>
            {ad}: {onceki(v.t)}
          </span>
        ))}
        {!hatlar.length && " —"}
      </div>
    </div>
  );
}
// ---------- uzuv (Faz 2 süreç beyini + insan etiketi) ----------
export function Uzuv({ d }) {
  const [satirlar, setSatirlar] = useState(null);
  const [not, setNot] = useState(null);
  const m = d.uzuv.model, du = d.uzuv.durum;
  const toplam = m?.toplam || {};

  async function yukle() {
    setSatirlar("yükleniyor…");
    const r = await al("/uzuv/liste");
    if (r.satirlar) setSatirlar(r.satirlar);
    else { setSatirlar([]); setNot(r.hata || r.metin || "listelenemedi"); }
  }
  async function etiketle(comm, exe, sinif) {
    const metin = `${comm} ${exe} |sinif=${sinif}`;
    const r = await post("/uzuv/etiket", { metin });
    setNot(r.ok
      ? `yazıldı: ${metin} → uyku yeniden eğitecek`
      : `HATA: ${r.cikti || r.hata || "?"}`);
    if (r.ok) yukle();
  }

  return (
    <div className="kart">
      <h2>Uzuv (süreç beyini — Faz 2)
        <span className="yan">
          {du ? `durum: ${du.siniflar?.guvenli ?? "?"} güvenli / `
            + `${du.siniflar?.govde ?? "?"} gövde` : "durum yok"}
        </span>
      </h2>
      <div className="istat">
        <div><div className="sayi">{m?.ornek ?? "—"}</div>
          <div className="alt">MODEL ÖRNEĞİ</div></div>
        <div><div className="sayi">{toplam.guvenli ?? 0}</div>
          <div className="alt">GÜVENLİ</div></div>
        <div><div className="sayi">{toplam.govde ?? 0}</div>
          <div className="alt">GÖVDE</div></div>
        <div><div className="sayi">{toplam.bilinmeyen ?? 0}</div>
          <div className="alt">BİLİNMEYEN</div></div>
        <div><div className="sayi"
          style={{ color: (du?.tehlikeli || 0) > 0 ? "var(--kirmizi)" : undefined }}>
          {du?.tehlikeli ?? 0}</div>
          <div className="alt">TEHLİKELİ</div></div>
      </div>
      <div className="satir">
        <button className="dgm" onClick={yukle}>
          bilinmeyenleri listele
        </button>
        <span className="not11 soluk">
          insan etiketi → uyku anında yeniden eğitir (damga)
        </span>
      </div>
      {satirlar === "yükleniyor…" && <div className="not11 soluk">{satirlar}</div>}
      {Array.isArray(satirlar) && (
        satirlar.length === 0
          ? <div className="not11 ok">bilinmeyen yok — hepsi etiketli/düşünmüş</div>
          : <table>
              <thead><tr><th>comm</th><th>exe</th><th>tahmin</th>
                <th className="sag">etiket</th></tr></thead>
              <tbody>
                {(satirlar || []).slice(0, 30).map((s, i) => (
                  <tr key={i}>
                    <td><b>{s.comm}</b></td>
                    <td><span className="kisa" title={s.exe}>{s.exe}</span></td>
                    <td><span className="rozet">{s.tahmin}</span></td>
                    <td className="sag">
                      <button className="dgm tiny"
                        onClick={() => etiketle(s.comm, s.exe, "guvenli")}>
                        güvenli</button>{" "}
                      <button className="dgm tiny tehlike"
                        onClick={() => etiketle(s.comm, s.exe, "tehlikeli")}>
                        tehlikeli</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
      )}
      {not && <div className={"not11 " + (not.startsWith("HATA") ? "hata" : "ok")}>
        {not}</div>}
    </div>
  );
}

// ---------- ders (insan düzeltme defteri) ----------
export function Ders({ d }) {
  const [ornek, setOrnek] = useState([]);
  const [hedef, setHedef] = useState("");
  const [dogrusu, setDogrusu] = useState("");
  const [not, setNot] = useState(null);
  const s = d.ders;

  async function yukle() {
    const r = await al("/ders/acik");
    setOrnek(r.ornekler || []);
  }
  useEffect(() => { yukle(); }, []);

  async function gonder(e) {
    e.preventDefault();
    const r = await post("/ders", { hedef, dogrusu });
    setNot(r.ok
      ? `işlendi: ${hedef} → ${dogrusu} (${r.islenen} satır işaretlendi)`
      : `HATA: ${r.hata || r.cikti || "?"}`);
    if (r.ok) { setHedef(""); setDogrusu(""); yukle(); }
  }

  return (
    <div className="kart">
      <h2>Ders (insan düzeltme defteri)
        <span className="yan">öğretmen hiyerarşisinde insan en üstte</span></h2>
      <div className="istat">
        <div><div className="sayi">{s.acik}</div><div className="alt">AÇIK SATIR</div></div>
        <div><div className="sayi">{s.bekleyen}</div><div className="alt">İŞLENMEYİ BEKLİYOR</div></div>
        <div><div className="sayi">{s.islenmis}</div><div className="alt">İŞLENDİ</div></div>
        <div><div className="sayi">{s.toplam}</div><div className="alt">TOPLAM</div></div>
      </div>
      <form onSubmit={gonder}>
        <div className="satir">
          <input placeholder="hedef: PAKET_SOR" value={hedef}
            onChange={(e) => setHedef(e.target.value)} />
          <input placeholder="doğrusu: cmd:dpkg,cmd:grep" value={dogrusu}
            onChange={(e) => setDogrusu(e.target.value)} />
          <button className="dgm" type="submit">toplu düzelt</button>
        </div>
      </form>
      <div className="not11 soluk">
        açık satırların TÜMÜNE yazılır; organizma 20 tikte bir okur,
        beyne işler ve |ok=1 ile boşa alır.
      </div>
      {not && <div className={"not11 " + (not.startsWith("HATA") ? "hata" : "ok")}>
        {not}</div>}
      {ornek.length > 0 && <pre className="kutu">{ornek.join("\n")}</pre>}
      {d.ders_islem.length > 0 && (
        <div className="not11 soluk">
          son işlemler: {d.ders_islem.slice(0, 3).map((i) =>
            i.kind === "ders_uygulandi"
              ? `${i.hedef}: ${i.yanlis} → ${i.dogrusu}`
              : `${i.hedef} RED (${i.not_})`).join(" · ")}
        </div>
      )}
    </div>
  );
}
// ---------- kapı (yönetim) ----------
export function Kapi() {
  const [shock, setShock] = useState("50");
  const [gorev, setGorev] = useState("");
  const [serbest, setSerbest] = useState("");
  const [cevap, setCevap] = useState(null);

  async function gonder(msg) {
    const r = await post("/door", { msg });
    setCevap(r);
  }

  return (
    <div className="kart">
      <h2>Kapı (yönetim — TCP 5777)
        <span className="yan">mesaj = uyaran</span></h2>
      <div className="satir">
        <input style={{ maxWidth: 90 }} value={shock}
          onChange={(e) => setShock(e.target.value)} placeholder="şok" />
        <button className="dgm tehlike"
          onClick={() => gonder("shock:" + shock)}>şok ver</button>
        <input value={gorev} onChange={(e) => setGorev(e.target.value)}
          placeholder="gorev: /klasor/yolu" />
        <button className="dgm"
          onClick={() => gorev && gonder("gorev:" + gorev)}>
          görev ver</button>
      </div>
      <div className="satir">
        <input value={serbest} onChange={(e) => setSerbest(e.target.value)}
          placeholder="serbest kapı tokası (door_inbox + kıvılcım)"
          onKeyDown={(e) => {
            if (e.key === "Enter" && serbest.trim()) {
              gonder(serbest.trim());
              setSerbest("");
            }
          }} />
        <button className="dgm" onClick={() => {
          if (serbest.trim()) { gonder(serbest.trim()); setSerbest(""); }
        }}>çal</button>
        <button className="dgm" onClick={() => gonder("ac")}>
          kutu açtır</button>
      </div>
      <div className="not11 soluk">
        şok: enerji sınavı (güvenlik beyini karar verir) · görev: klasör
        misyonu · ac: bir kutu açtır (damak ölçümü)
      </div>
      {cevap && (
        <pre className="kutu">{cevap.ok
          ? JSON.stringify(cevap.durum || cevap.cevap, null, 1).slice(0, 600)
          : "KAPI YOK: " + (cevap.cevap || "?")}</pre>
      )}
    </div>
  );
}

// ---------- atölye (Sahne 0-2: merak + araç-kompozisyonu) ----------
export function Atolye({ d }) {
  const a = d?.atolye;
  if (!a) return null;
  const islemler = Object.entries(a.islem || {})
    .sort((x, y) => y[1] - x[1]);
  return (
    <div className="kart">
      <h2>Atölye<span className="yan">
        {a.arac ? `${a.arac} araç · ${a.kuvvet} kuvvet`
          : "araç yok"}</span></h2>
      <div className="istat">
        <div><div className="sayi">{a.nesne}</div>
          <div className="alt">NESNE</div></div>
        <div><div className="sayi" style={{ color: a.bozuk ? "var(--kirmizi)" : undefined }}>
          {a.bozuk}</div>
          <div className="alt">BOZUK</div></div>
        <div><div className="sayi" style={{ color: a.arac ? "var(--mor)" : undefined }}>
          {a.arac}</div>
          <div className="alt">ARAÇ</div></div>
        <div><div className="sayi">{a.merak_n}</div>
          <div className="alt">MERAK OLAYI</div></div>
        <div><div className="sayi">{a.merak_odul}</div>
          <div className="alt">ÖZ ÖDÜL TOPLAMI</div></div>
      </div>
      <Cubuk etiket="dünya sağlığı" deger={(a.saglik || 0) * 100} maks={100}
        renk={a.saglik > 0.7 ? "var(--yesil)"
          : a.saglik > 0.4 ? "var(--sari)" : "var(--kirmizi)"}
        sag={yuzde(a.saglik) + "%"} />
      <Spark ad="sağlık serisi (merak olayları)" seri={a.seri} renk="var(--yesil)" />
      {islemler.length > 0 && (
        <div className="chips" style={{ marginTop: 6 }}>
          {islemler.map(([is, n]) => (
            <span key={is} className="chip acik">{is} ×{n}</span>
          ))}
        </div>
      )}
      <div className="akis-kisa">
        {(a.son || []).map((m, i) => (
          <div key={i} className="satir-olay k-merak">
            <span className="saat">{saat(m.t)}</span>
            <span className="tur">{m.islem}</span>
            <span className="metin">
              sürpriz {m.surpriz} → merak {m.odul} · sağlık {m.saglik}
              {m.obs ? ` · ${String(m.obs).slice(0, 60)}` : ""}
            </span>
          </div>
        ))}
        {!(a.son || []).length &&
          <div className="not11 soluk">merak olayı yok</div>}
      </div>
    </div>
  );
}

// ---------- ağ keşfi (AG_TARA / BENI_TARA) ----------
export function Ag({ d }) {
  if (!d || !d.ag) return null;
  const a = d.ag, k = a.kapsam;
  const renk = (o) => (o > 0.8 ? "var(--yesil)"
    : o > 0.5 ? "var(--sari)" : "var(--kirmizi)");
  return (
    <div className="kart">
      <h2>Ağ keşfi
        <span className="yan">
          {a.toplam.n
            ? `${yuzde(a.toplam.oran)}% · ${a.toplam.n} deneme`
            : "kanıt yok"}
        </span>
      </h2>
      <div className="chips">
        <span className={"rozet " + (k ? (k.acik ? "ok" : "kotu") : "uyari")}>
          kapsam {k ? (k.acik ? "açık" : "kapalı") : "?"}
        </span>
        <span className={"rozet " + (k?.ben_tarama ? "ok" : "kotu")}>
          ben_tarama {k?.ben_tarama ? "açık" : "kapalı"}
        </span>
        {k?.ben_http_port ? (
          <span className="rozet">http :{k.ben_http_port}</span>
        ) : null}
        {(k?.izin_aglari || []).map((x) => (
          <span key={x} className="rozet">{x}</span>
        ))}
        {a.duraklama > 0 && (
          <span className="rozet uyari">⚠ duraklama {a.duraklama}</span>
        )}
      </div>
      {a.kapi.length > 0 ? a.kapi.map((v) => (
        <Cubuk key={v.komut} etiket={v.komut}
          deger={v.ok} maks={v.n} renk={renk(v.oran)}
          sag={`${v.ok}/${v.n} · %${yuzde(v.oran)}${v.duraklama
            ? ` · ⚠${v.duraklama}` : ""}`} />
      )) : <div className="not11 soluk">AG/BENI denemesi yok</div>}
      {a.hedef.length > 0 && (
        <div className="chips" style={{ marginTop: 6 }}>
          {a.hedef.map((h) => (
            <span key={h.tip} className="chip">
              {h.tip}: {h.ok}/{h.n} (%{yuzde(h.oran)})
            </span>
          ))}
        </div>
      )}
      <div className="akis-kisa">
        {a.son.map((m, i) => (
          <div key={i}
            className={"satir-olay " + (m.duraklama ? "k-duraklama" : "k-kullan")}>
            <span className="saat">{saat(m.t)}</span>
            <span className="tur">{m.komut || "?"}</span>
            <span className="metin">
              {m.duraklama
                ? `${m.hedef} 3'te takıldı (deneme ${m.deneme}) — ölü kapı adayı`
                : `${m.hedef} ${m.dogru ? "✓" : "✗"} · deneme ${m.deneme}`}
            </span>
          </div>
        ))}
        {!a.son.length && <div className="not11 soluk">deneme yok</div>}
      </div>
    </div>
  );
}

// ---------- üst beyin (ust_beyn.py) ----------
export function UstBeyn({ d }) {
  if (!d || !d.ust_beyn) return null;
  const u = d.ust_beyn;
  const m = u.model, c = u.canli;
  const adlar = u.komutlar || [];

  // Komut başına model ölçümleri (indeks → komut adı).
  const komutSatir = adlar.map((ad, i) => ({
    ad, i,
    dogrulama: (m.dogrulama || [])[i] ?? 0,
    secim: (m.secim || [])[i] ?? 0,
  }));

  // Bağlamsal doğrulama: "idx|bağlam" → puan
  const baglamsal = Object.entries(m.dogrulama_baglam || {})
    .map(([k, v]) => {
      const [idx, bag] = k.split("|");
      return { ad: adlar[Number(idx)] || idx, bag, puan: v };
    })
    .sort((x, y) => y.puan - x.puan);

  const dogrEsik = m.dogrulama_esigi ?? 0.35;
  const guvenEsik = m.guven_esigi ?? 0.45;

  // "yok" bir EYLEM DEĞİL, pasif varsayılandır: sec() onu hiç seçmez,
  // nötr gözlemlerde sayacı artar. Bu yüzden "seçim" hâkimiyeti
  // hesabına katılmaz; ayrıca pasif oranı olarak gösterilir.
  const pasifIdx = adlar.indexOf("yok");
  const aktifSatir = komutSatir.filter((k) => k.i !== pasifIdx);
  const toplamSecim = aktifSatir.reduce((s, x) => s + x.secim, 0);
  const toplamHepsi = komutSatir.reduce((s, x) => s + x.secim, 0);
  // Tek komut hâkimiyeti: öğrenmenin tek kalıba kilitlenmesi teşhisi.
  const enCok = aktifSatir.reduce(
    (a, b) => (b.secim > (a?.secim ?? -1) ? b : a), null);
  const hakimiyet = toplamSecim && enCok ? enCok.secim / toplamSecim : 0;
  const pasifOran = toplamHepsi
    ? (komutSatir[pasifIdx]?.secim ?? 0) / toplamHepsi : 0;

  // Görüntülenen sayıların hepsi tam sayı olmalı (NaN/undefined kırılmasın).
  const say = (x) => (Number.isFinite(x) ? Math.round(x) : 0).toLocaleString("tr-TR");
  const ondalik = (x, b = 2) => (Number.isFinite(x) ? x.toFixed(b) : "—");

  const renk = (o) => (o > 0.8 ? "var(--yesil)"
    : o > 0.5 ? "var(--sari)" : "var(--kirmizi)");

  return (
    <div className="kart">
      <h2>Üst beyin
        <span className="yan">
          {say(m.samples)} örnek · ε {ondalik(m.epsilon, 3)}
        </span>
      </h2>

      <div className="istat">
        <div><div className="sayi">{say(m.tik)}</div>
          <div className="alt">TİK</div></div>
        <div><div className="sayi">{say(m.reddedilen)}</div>
          <div className="alt">REDDEDİLEN</div></div>
        <div><div className="sayi">{say(c.override_toplam)}</div>
          <div className="alt">OVERRIDE</div></div>
        <div><div className="sayi">{say(c.red_toplam)}</div>
          <div className="alt">RED (GÜNLÜK)</div></div>
        <div><div className="sayi">%{yuzde(pasifOran)}</div>
          <div className="alt">PASİF ORAN</div></div>
      </div>

      <div className="chips" style={{ marginTop: 6 }}>
        <span className="rozet">güven eşiği {guvenEsik}</span>
        <span className="rozet">doğrulama eşiği {dogrEsik}</span>
        <span className="rozet">override ömrü {m.sure_azami} tik</span>
        <span className="rozet">marj ölçeği {m.marj_olcek}</span>
        <span className="rozet">kanıt çarpanı {m.kanit_carpani}</span>
      </div>

      {/* ---- komut komut kanıt tablosu ---- */}
      <table style={{ marginTop: 8 }}>
        <thead><tr><th>komut</th><th className="sag">seçim</th>
          <th className="sag">doğrulama</th><th className="sag">durum</th></tr></thead>
        <tbody>
          {komutSatir.map((k) => (
            <tr key={k.ad}>
              <td><b>{k.ad}</b>{k.i === pasifIdx
                ? <span className="not11 soluk"> (pasif)</span> : null}</td>
              <td className="sag">{say(k.secim)}</td>
              <td className="sag">{ondalik(k.dogrulama)}</td>
              <td className="sag">
                {k.i === pasifIdx ? <span className="rozet">varsayılan</span>
                  : k.dogrulama >= dogrEsik
                    ? <span className="rozet ok">onaylı</span>
                    : <span className="rozet kotu">kanıtsız</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* ---- canlı komut dağılımı ---- */}
      <div style={{ marginTop: 8 }}>
        {c.override.length > 0 ? c.override.map((v) => (
          <Cubuk key={v.komut} etiket={v.komut}
            deger={v.n} maks={c.override_toplam}
            renk={renk(v.n / c.override_toplam)}
            sag={`${v.n} · model ${v.model} / keşif ${v.kesif}`} />
        )) : <div className="not11 soluk">aktif günlükte override yok</div>}
      </div>

      {hakimiyet > 0.8 && enCok && (
        <div className="not11 hata" style={{ marginTop: 6 }}>
          ⚠ tek komut hâkimiyeti: {enCok.ad} seçimlerin
          {" "}%{yuzde(hakimiyet)}&apos;ini alıyor — model kilitlenmiş olabilir.
        </div>
      )}

      {/* ---- reddedilme gerekçeleri ---- */}
      {c.red.length > 0 && (
        <>
          <div className="not11 soluk" style={{ marginTop: 8 }}>
            reddedilme gerekçeleri (aktif günlük)
          </div>
          <div className="chips">
            {c.red.map((r) => (
              <span key={r.komut + r.gerekce}
                className={"rozet " + (r.gerekce === "guven_yetersiz"
                  ? "uyari" : "kotu")}>
                {r.komut} · {r.gerekce} ×{r.n}
              </span>
            ))}
          </div>
        </>
      )}

      {/* ---- sifirla (konsolidasyon) ---- */}
      <div className="not11 soluk" style={{ marginTop: 8 }}>
        sifirla (konsolidasyon): {say(c.sifirla.n)} kez · ortalama
        {" "}{ondalik(c.sifirla.ort_budanan, 1)} bağlantı budandı
        {c.sifirla.links ? ` · tablo ${say(c.sifirla.links)} bağlantı` : ""}
      </div>

      {/* ---- bağlamsal kanıt ---- */}
      {baglamsal.length > 0 && (
        <>
          <div className="not11 soluk" style={{ marginTop: 8 }}>
            bağlamsal doğrulama (kanıt hangi durumda toplandı)
          </div>
          <div className="chips">
            {baglamsal.map((b) => (
              <span key={b.ad + b.bag} className="rozet"
                title="doğrulama puanı">
                {b.ad} @ {b.bag}: {ondalik(b.puan)}
              </span>
            ))}
          </div>
        </>
      )}

      {/* ---- son olaylar ---- */}
      <div className="akis-kisa">
        {c.son_override.slice(0, 8).map((o, i) => (
          <div key={"o" + i} className="satir-olay k-uyku">
            <span className="saat">{saat(o.t)}</span>
            <span className="tur">{o.komut || "?"}</span>
            <span className="metin">
              override · güven {o.guven} · {o.kaynak}
            </span>
          </div>
        ))}
        {c.son_red.slice(0, 8).map((r, i) => (
          <div key={"r" + i} className="satir-olay k-hata">
            <span className="saat">{saat(r.t)}</span>
            <span className="tur">{r.komut || "?"}</span>
            <span className="metin">
              reddedildi · {r.gerekce} · güven {r.guven}
            </span>
          </div>
        ))}
        {!c.son_override.length && !c.son_red.length &&
          <div className="not11 soluk">üst beyin olayı yok</div>}
      </div>

      <div className="not11 soluk" style={{ marginTop: 6 }}>
        kanıt puanları zeka/ust_beyn.json&apos;dan okunur (organizma kapanışta
        yazar) · canlı sayılar aktif günlükten gelir (boyuta göre arşivlenir)
      </div>
    </div>
  );
}

// ---------- canlı olay akışı ----------
function ozet(k) {
  if (k.obs) return String(k.obs).slice(0, 140);
  const p = [];
  for (const [a, v] of Object.entries(k)) {
    if (a === "t" || a === "kind" || v == null) continue;
    p.push(`${a}=${typeof v === "object" ? JSON.stringify(v) : v}`);
  }
  return p.join(" ").slice(0, 150);
}

export function Akim({ olaylar, bagli }) {
  const [tur, setTur] = useState(null);   // null = hepsi
  const gorunen = olaylar.filter((k) => !tur || k.kind === tur);
  const turler = [...new Set(olaylar.map((k) => k.kind))].slice(0, 14);
  return (
    <div className="kart">
      <h2>Canlı akış
        <span className="yan">
          {bagli ? "● bağlı" : "○ kopuk"} · {olaylar.length} olay
        </span>
      </h2>
      <div className="chips">
        <button className={"chip" + (tur === null ? " acik" : "")}
          onClick={() => setTur(null)}>hepsi</button>
        {turler.map((t) => (
          <button key={t}
            className={"chip" + (tur === t ? " acik" : "")}
            onClick={() => setTur(tur === t ? null : t)}>{t}</button>
        ))}
      </div>
      <div className="akim">
        {gorunen.slice(0, 200).map((k, i) => (
          <div key={i} className={"satir-olay k-" + k.kind}>
            <span className="saat">{saat(k.t)}</span>
            <span className="tur">{k.kind}</span>
            <span className="metin">{ozet(k)}</span>
          </div>
        ))}
        {!gorunen.length && <div className="not11 soluk">olay yok</div>}
      </div>
    </div>
  );
}



