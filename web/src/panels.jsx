import { useEffect, useState } from "react";

// API token'ı sunucu tarafında vite.config.js → define ile enjekte edilir.
// Yazma uçları (post) bu token'ı "Authorization: Bearer" başlığıyla gönderir.
const TOKEN = (typeof __CORE_TOKEN__ !== "undefined") ? __CORE_TOKEN__ : "";

function tokenBasliklari() {
  return TOKEN ? { "Authorization": "Bearer " + TOKEN } : {};
}

// ---------- yardımcılar ----------
export async function al(yol, secenek) {
  const r = await fetch("/api" + yol, secenek);
  return r.json();
}
export async function post(yol, govde) {
  return al(yol, { method: "POST",
    headers: { "Content-Type": "application/json", ...tokenBasliklari() },
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
  if (!t || t < 1000000000) return "—";
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
  const b = c.beden || {};
  const u = c.usb || {};
  const m = c.mood || {};
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
        {a.R_dis != null && (
          <div><div className="sayi">{a.R_dis > 0 ? "+" : ""}{a.R_dis}</div>
            <div className="alt">Dış Geri</div></div>
        )}
        <div><div className="sayi">{s.toFixed(2)}</div>
          <div className="alt">SIKILMA (S)</div></div>
      </div>
      <Cubuk etiket="enerji" deger={e} maks={450}
        renk={e < 30 ? "var(--kirmizi)" : "var(--yesil)"}
        sag={e + " / 450"} />
      <Cubuk etiket="açlık" deger={h} maks={100} renk="var(--turuncu)"
        sag={h + " / 100"} />
      <Cubuk etiket="sıkılma" deger={s} maks={1}
        renk={s >= 0.66 ? "var(--kirmizi)" : "var(--mor)"}
        sag={s.toFixed(2)} />
      {b.disk_yuzde != null && b.bellek_yuzde != null && (
        <>
          <div className="not11 soluk">
            insan: {b.insan_var ? "var" : "yok"} ·
            sistem: {b.sistem_saati ? Math.round(b.sistem_saati) + "s" : "—"} ·
            disk: {b.disk_yuzde}% ·
            bellek: {b.bellek_yuzde}%
          </div>
          <Cubuk etiket="disk" deger={b.disk_yuzde} maks={100}
            renk={b.disk_yuzde > 80 ? "var(--kirmizi)" : "var(--yesil)"}
            sag={b.disk_yuzde + " %"} />
          <Cubuk etiket="bellek" deger={b.bellek_yuzde} maks={100}
            renk={b.bellek_yuzde > 80 ? "var(--kirmizi)" : "var(--yesil)"}
            sag={b.bellek_yuzde + " %"} />
        </>
      )}
      {u.cihaz_sayisi != null && (
        <>
          <div className="not11 soluk">
            usb cihaz: {u.cihaz_sayisi} · usb node: {u.node_sayisi}
          </div>
        </>
      )}
      {m.dominant != null && (
        <>
          <div className="not11 soluk">
            ruh: {m.dominant} ·
            mutluluk: {Math.round(m.mutluluk * 100)}% ·
            korku: {Math.round(m.korku * 100)}% ·
            güven: {Math.round(m.guven * 100)}% ·
            merak: {Math.round(m.merak * 100)}%
          </div>
          <Cubuk etiket="mutluluk" deger={Math.round(m.mutluluk * 100)} maks={100}
            renk="var(--yesil)"
            sag={Math.round(m.mutluluk * 100) + " %"} />
          <Cubuk etiket="korku" deger={Math.round(m.korku * 100)} maks={100}
            renk={m.korku > 0.6 ? "var(--kirmizi)" : "var(--mor)"}
            sag={Math.round(m.korku * 100) + " %"} />
          <Cubuk etiket="güven" deger={Math.round(m.guven * 100)} maks={100}
            renk="var(--mavi)"
            sag={Math.round(m.guven * 100) + " %"} />
          <Cubuk etiket="merak" deger={Math.round(m.merak * 100)} maks={100}
            renk="var(--turuncu)"
            sag={Math.round(m.merak * 100) + " %"} />
        </>
      )}
      {(c.nn_usb || c.nn_ag || c.nn_ana) && (
        <div className="not11 soluk" style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 8 }}>
          <div style={{ fontWeight: 'bold', marginBottom: 4 }}>NÖRAL BEYİNLER</div>
          {c.nn_usb && (
            <div style={{ fontSize: '0.85rem', marginBottom: 2 }}>
              USB Beyn: katmanlar [{c.nn_usb.katmanlar?.join(',')}] · lr: {c.nn_usb.lr} · MSE: {(c.nn_usb.son_mse ?? 0).toFixed(4)} · öğrenme: {c.nn_usb.öğrenme_sayısı ?? 0}
            </div>
          )}
          {c.nn_ag && (
            <div style={{ fontSize: '0.85rem', marginBottom: 2 }}>
              Ağ Beyn: katmanlar [{c.nn_ag.katmanlar?.join(',')}] · lr: {c.nn_ag.lr} · MSE: {(c.nn_ag.son_mse ?? 0).toFixed(4)} · öğrenme: {c.nn_ag.öğrenme_sayısı ?? 0}
            </div>
          )}
          {c.nn_ana && (
            <div style={{ fontSize: '0.85rem', marginBottom: 2 }}>
              Ana Beyn: katmanlar [{c.nn_ana.katmanlar?.join(',')}] · lr: {c.nn_ana.lr} · MSE: {(c.nn_ana.son_mse ?? 0).toFixed(4)} · öğrenme: {c.nn_ana.öğrenme_sayısı ?? 0}
            </div>
          )}
        </div>
      )}
      <div className="not11 soluk">
        son eylem ({saat(a.t)}): <b>{a.action}</b> —
        {" "}{String(a.obs || "").slice(0, 90)}
      </div>
      <div className="not11 soluk">
        son nabız: {c.son_act_s ?? "—"} sn önce
        {c.ticks_s ? ` · tik ≈ ${c.ticks_s} sn` : ""}
        {d.beyin?.baglanti ? ` · beyin: ${d.beyin.baglanti} bağlantı` : ""}
      </div>
      {(d.hatalar || []).filter(h => h.tur === "tekrar_basarısızlık").length > 0 && (
        <div className="not11 hata" style={{ marginTop: 6 }}>
          ⚠ {(d.hatalar || []).filter(h => h.tur === "tekrar_basarısızlık").length}
          tekrarlayan başarisizlik (son 20 hata)
        </div>
      )}
    </div>
  );
}

export function Evren({ d }) {
  const world = d?.evren;
  if (!world) {
    return (
      <div className="kart">
        <h2>Evren</h2>
        <div className="not11 soluk">henüz çevre gözlemi yok</div>
      </div>
    );
  }
  const local = world.local || {};
  const internet = world.internet || [];
  return (
    <div className="kart">
      <h2>Evren
        <span className="yan">ev: bu bilgisayar · dış dünya: internet</span>
      </h2>
      <div className="chips">
        <span className="rozet">{world.tokens?.[0] || "yerel gözlem"}</span>
        <span className="rozet">
          CPU {local.cpu ?? "?"} · disk {local.disk || "?"} · bellek
          {" "}{local.memory || "?"} · arayüz {local.interfaces || "?"}
        </span>
      </div>
      <div className="not11 soluk" style={{ marginTop: 6 }}>
        Dış gözlem: {!world.internet_enabled
          ? "kapalı (izin listesi yapılandırılmamış)"
          : internet.length
            ? internet.map((site) => site.status
              ? `${site.host}: HTTP ${site.status}`
              : `${site.host}: erişilemedi (${site.error || "bekleniyor"})`)
              .join(" · ")
            : "izinli adreslerden yanıt bekleniyor"}
      </div>
      <div className="not11 soluk">
        Yalnızca HTTPS yanıt başlıkları okunur; gövde içeriği okunmaz veya
        öğrenme belleğine yazılmaz. Son gözlem {saat(world.t)}.
      </div>
    </div>
  );
}

export function YerelSurec({ d }) {
  const surec = d?.surec;
  const sample = surec?.son;
  if (!surec || !sample) {
    return (
      <div className="kart">
        <h2>Bilgisayar işleyişi</h2>
        <div className="not11 soluk">
          yerel süreç gözlemi bekleniyor
          {surec?.ornek ? ` · ${surec.ornek} örnek kaydedildi` : ""}
        </div>
      </div>
    );
  }
  const processes = sample.surecler || [];
  const profiles = Object.keys(surec.profiller || {}).length;
  return (
    <div className="kart">
      <h2>Bilgisayar işleyişi
        <span className="yan">{surec.ornek} örnek · {profiles} öğrenilen süreç profili</span>
      </h2>
      <div className="chips">
        <span className="rozet">
          süreç {sample.surec_sayisi ?? "?"} · tür {sample.surec_turu ?? "?"}
        </span>
        <span className="rozet">
          CPU {sample.cpu_yuzde == null ? "ölçülüyor" : `${sample.cpu_yuzde}%`}
          {" · "}bellek {sample.bellek_yuzde == null
            ? "?" : `${sample.bellek_yuzde}%`}
        </span>
        <span className="rozet">
          çalışan {sample.calisan ?? "?"} · bekleyen {sample.bekleyen ?? "?"}
        </span>
      </div>
      <div className="not11 soluk" style={{ marginTop: 6 }}>
        Örneklenen yerel süreçlerin CPU ve bellek örüntüleri zaman içinde
        öğrenilir; PID ve komut satırı saklanmaz.
      </div>
      {processes.length > 0 && (
        <div className="liste">
          {processes.slice(0, 8).map((process) => (
            <div className="satir" key={process.ad}>
              <b>{process.ad}</b>
              <span>
                {process.adet} süreç · CPU {process.cpu_yuzde == null
                  ? "—" : `${process.cpu_yuzde}%`}
                {" · "}{((process.bellek_kb || 0) / 1024).toFixed(1)} MB
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="not11 soluk">
        Son örnek: {saat(sample.t)}
        {sample.yeni?.length ? ` · yeni: ${sample.yeni.slice(0, 4).join(", ")}` : ""}
        {sample.eksik?.length ? ` · kayıp: ${sample.eksik.slice(0, 4).join(", ")}` : ""}
      </div>
    </div>
  );
}

// ---------- öğrenme / komut kullanımı ----------
export function Kullan({ d }) {
  if (!d || !d.kullan) {
    return (<div className="kart"><h2>Öğrenme — komut kullanımı</h2>
      <div className="not11 soluk">yükleniyor…</div></div>);
  }
  const k = d.kullan;
  const komutHelp = d.komut_help || {};
  const komutCiktilari = d.komut_ciktilari || {};
  const testSatirlari = Object.entries(komutCiktilari).map(([anahtar, v]) => {
    const [hedef, eskiKomut] = anahtar.split("|");
    const komut = v.komut || eskiKomut || anahtar;
    return {
      anahtar,
      komut,
      hedef: v.hedef || hedef || "—",
      help: komutHelp[komut] || null,
      test: v,
    };
  });
  const testEdilenler = new Set(testSatirlari.map((s) => s.komut));
  const helpSatirlari = Object.entries(komutHelp)
    .filter(([komut]) => !testEdilenler.has(komut))
    .map(([komut, help]) => ({
      anahtar: `help:${komut}`,
      komut,
      hedef: "—",
      help,
      test: null,
    }));
  const komutSatirlari = [...testSatirlari, ...helpSatirlari]
    .map((satir, sira) => ({
      ...satir,
      siralama: Math.max(
        Number(satir.test?.t) || Number(satir.test?.deneme) || 0,
        Number(satir.help?.t) || 0,
        sira / 1_000_000,
      ),
    }))
    .sort((a, b) => b.siralama - a.siralama)
    .slice(0, 10);
  return (
    <div className="kart">
      <h2>Öğrenme — komut kullanımı
        <span className="yan">{k.n} deneme · %{yuzde(k.oran)}</span></h2>
      <div className="istat">
        <div><div className="sayi">%{yuzde(k.oran)}</div>
          <div className="alt">BAŞARI (tümü)</div></div>
        <div><div className="sayi">%{yuzde(k.zincir?.baslatilan
          ? k.zincir.ok / k.zincir.baslatilan
          : k?.zincir_oran)}</div>
          <div className="alt">ZİNCİR TAMAM</div></div>
        <div><div className="sayi">{k.zincir?.ilerleme ?? "—"}</div>
          <div className="alt">ARA VERİ ADIMI</div></div>
        <div><div className="sayi">{d.birak?.n ?? "—"}</div>
          <div className="alt">İNKÂR (bırak)</div></div>
      </div>
      {["1", "2", "3"].map((x) => {
        const v = k.deneme?.[x];
        if (!v) return null;
        const renk = x === "1" ? "var(--yesil)"
          : x === "2" ? "var(--sari)" : "var(--kirmizi)";
        return <Cubuk key={x}
          etiket={"deneme " + (x === "3" ? "3+" : x)}
          deger={v.ok} maks={v.n} renk={renk}
          sag={`${v.ok}/${v.n} · %${yuzde(v.n ? v.ok / v.n : 0)}`} />;
      })}
      <table>
        <thead>
          <tr><th>hedef tipi</th><th className="sag">deneme</th>
            <th className="sag">doğru</th></tr>
        </thead>
        <tbody>
          {(k.hedefler || []).map((h) => (
            <tr key={h.tip}>
              <td>{h.tip}</td>
              <td className="sag">{h.n}</td>
              <td className="sag">%{yuzde(h.baslatilan
                ? h.ok / h.baslatilan : h.n ? h.ok / h.n : 0)}</td>
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
      {d.birak?.n > 0 && (
        <div className="not11 soluk">
          bırak dağılımı: {Object.entries(d.birak.deneme)
            .map(([z, n]) => `deneme${z}=${n}`).join(" · ")}
        </div>
      )}
      {(komutSatirlari.length > 0) && (
        <>
          <div className="not11 soluk" style={{ marginTop: 8 }}>
            son 10 komut keşfi ve denemesi · {Object.keys(komutHelp).length}
            help öğrenildi · {testSatirlari.length} komut/hedef denemesi
          </div>
          <table style={{ marginTop: 4 }}>
            <thead>
              <tr><th>komut</th><th>help / tür</th><th>hedef</th>
                <th>test</th><th>sonuç / çıktı</th></tr>
            </thead>
            <tbody>
              {komutSatirlari.map(({ anahtar, komut, hedef, help, test }) => (
                  <tr key={anahtar}>
                    <td>{komut}</td>
                    <td title={help?.ikinci_satir || ""}>
                      {help
                        ? `${help.tip || "?"}: ${help.aciklama || ""}`
                        : "help kaydı yok"}
                    </td>
                    <td>{hedef}</td>
                    <td>{test
                      ? `${test.dogru === true ? "başarılı" : test.dogru === false ? "başarısız" : "sonuç belirsiz"} · #${test.deneme ?? "—"}`
                      : "henüz cmd testi yok"}</td>
                    <td style={{ fontSize: 11, maxWidth: 260,
                      whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                      {test
                        ? String(test.obs || "(boş çıktı)").slice(0, 180)
                        : "—"}
                    </td>
                  </tr>
              ))}
            </tbody>
          </table>
          <div className="not11 soluk" style={{ marginTop: 4 }}>
            help satırları öğrenilen açıklamaları; cmd satırları komutun
            hedefte gerçekten denenmesini ve doğrulama çıktısını gösterir.
          </div>
        </>
      )}
    </div>
  );
}

// ---------- beyin ----------
export function Beyin({ d }) {
  const b = d.beyin, s = d.seriler;
  const guclu = b.guclu || [];

  // Eylem türlerine göre grupla
  const gruplara = {};
  guclu.forEach((g) => {
    const act = g.action;
    let tur;
    if (act === "eat") tur = "ye";
    else if (act === "rest") tur = "dinlen";
    else if (act === "wander") tur = "gezin";
    else if (act.startsWith("cmd:")) tur = "komut";
    else if (act.startsWith("help:")) tur = "help";
    else if (act.startsWith("explore:")) tur = "keşif";
    else if (act.startsWith("go:")) tur = "git";
    else if (act.startsWith("read:")) tur = "oku";
    else if (act.startsWith("console")) tur = "konsol";
    else tur = "diğer";
    if (!gruplara[tur]) gruplara[tur] = [];
    gruplara[tur].push(g);
  });

  // Komut eylemlerini ayrı göster (en güçlü 12)
  const komutBaglantilari = guclu
    .filter((g) => g.action.startsWith("cmd:"))
    .sort((a, b) => b.w - a.w)
    .slice(0, 12);

  return (
    <div className="kart">
      <h2>Beyin<span className="yan">{b.baglanti} bağlantı</span></h2>
      <Spark ad="sıkılma (S) — son ~150 learn" seri={s.S} renk="#b18cff" />
      <Spark ad="enerji (E)" seri={s.E} renk="#3ddc84" />
      <Spark ad="ödül (R)" seri={s.R} renk="#4ea1ff" />

      {/* Eylem türü dağılımı */}
      <div className="istat" style={{ marginTop: 8 }}>
        {Object.entries(gruplara).map(([tur, liste]) => (
          <div key={tur} style={{ display: "inline-block", marginRight: 12 }}>
            <div className="sayi" style={{ fontSize: 14 }}>
              {liste.length}
            </div>
            <div className="alt" style={{ fontSize: 10 }}>{tur}</div>
          </div>
        ))}
      </div>

      {/* Komut bağlantıları (hangi stim hangi komutu çağırır) */}
      {komutBaglantilari.length > 0 && (
        <>
          <div className="not11 soluk" style={{ marginTop: 8 }}>
            komut bağlantıları (stim → cmd:)
          </div>
          <table style={{ marginTop: 4 }}>
            <thead>
              <tr><th>uyaran (stim)</th><th className="sag">komut</th>
                <th className="sag">w</th></tr>
            </thead>
            <tbody>
              {komutBaglantilari.map((g, i) => (
                <tr key={i}>
                  <td><span className="kisa" title={g.stim}>{g.stim}</span></td>
                  <td className="sag">{g.action}</td>
                  <td className="sag">{g.w}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="not11 soluk" style={{ marginTop: 4 }}>
            komut bağlantıları: organizma hangi durumda hangi komutu
            çağırmayı öğreniyor.
          </div>
        </>
      )}

      {/* Genel en güçlü bağlantılar */}
      <div className="not11 soluk" style={{ marginTop: 8 }}>
        genel en güçlü bağlantılar
      </div>
      <table style={{ marginTop: 4 }}>
        <thead><tr><th>uyaran → eylem</th><th className="sag">w</th></tr></thead>
        <tbody>
          {guclu.slice(0, 8).map((g, i) => (
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
    try {
      const r = await post("/uzuv/etiket", { metin });
      setNot(r.ok
        ? `yazıldı: ${metin} → uyku yeniden eğitecek`
        : `HATA: ${r.cikti || r.hata || "?"}`);
      if (r.ok) yukle();
    } catch (err) {
      setNot(`HATA: ${err?.message || err}`);
    }
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
    try {
      const r = await post("/ders", { hedef, dogrusu });
      setNot(r.ok
        ? `işlendi: ${hedef} → ${dogrusu} (${r.islenen} satır işaretlendi)`
        : `HATA: ${r.hata || r.cikti || "?"}`);
      if (r.ok) { setHedef(""); setDogrusu(""); yukle(); }
    } catch (err) {
      setNot(`HATA: ${err?.message || err}`);
    }
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
  const [yukleniyor, setYukleniyor] = useState(false);

  async function gonder(msg) {
    setYukleniyor(true);
    setCevap(null);
    try {
      const r = await post("/door", { msg });
      setCevap(r);
    } catch (e) {
      setCevap({ ok: false, hata: String(e) });
    } finally {
      setYukleniyor(false);
    }
  }

  return (
    <div className="kart">
      <h2>Kapı (yönetim — TCP 5777)
        <span className="yan">mesaj = uyaran</span></h2>
      <div className="satir">
        <input style={{ maxWidth: 90 }} value={shock}
          onChange={(e) => setShock(e.target.value)} placeholder="şok" />
        <button className="dgm tehlike" disabled={yukleniyor}
          onClick={() => gonder("shock:" + (shock || "50"))}>
          {yukleniyor ? "…" : "şok ver"}</button>
        <input value={gorev} onChange={(e) => setGorev(e.target.value)}
          placeholder="gorev: /klasor/yolu" />
        <button className="dgm" disabled={yukleniyor}
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
        <button className="dgm" disabled={yukleniyor} onClick={() => {
          if (serbest.trim()) { gonder(serbest.trim()); setSerbest(""); }
        }}>çal</button>
        <button className="dgm" disabled={yukleniyor} onClick={() => gonder("ac")}>
          kutu açtır</button>
      </div>
      <div className="not11 soluk">
        şok: enerji sınavı (güvenlik beyini karar verir) · görev: klasör
        misyonu · ac: bir kutu açtır (damak ölçümü)
      </div>
      {cevap && (
        <div className={"not11 " + (cevap.ok ? "ok" : "hata")}>
          {cevap.ok
            ? "✓ " + (typeof cevap.durum === "object" ? JSON.stringify(cevap.durum) : cevap.durum || cevap.cevap || "cevap yok")
            : "✗ " + (cevap.hata || "bilinmeyen hata")}
        </div>
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
  const b = d.ag_beyin;
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
      <div className="not11 soluk">
        Başarı oranı yalnızca hedefe uygun ağ komutlarını içerir
        (nmap, ping, ip, traceroute, ss, curl).
      </div>
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
        {a.son.length > 0 ? (
          <div key="son"
            className={"satir-olay " + (a.son[0].duraklama ? "k-duraklama" : "k-kullan")}>
            <span className="saat">{saat(a.son[0].t)}</span>
            <span className="tur">{a.son[0].komut || "?"}</span>
            <span className="metin">
              {a.son[0].duraklama
                ? `${a.son[0].hedef} 3'te takıldı (deneme ${a.son[0].deneme}) — ölü kapı adayı`
                : `${a.son[0].hedef} ${a.son[0].dogru ? "✓" : "✗"} · deneme ${a.son[0].deneme}`}
              {a.son[0].calisti === false ? " · çalıştırılmadı" : ""}
              {a.son[0].obs ? ` · ${String(a.son[0].obs).slice(0, 90)}` : ""}
            </span>
          </div>
        ) : <div className="not11 soluk">deneme yok</div>}
      </div>
      {(a.diger || []).length > 0 && (
        <>
          <div className="not11 soluk" style={{ marginTop: 8 }}>
            Ağ hedefinde denenmiş, ağ kapısı olmayan komutlar — ağ oranına
            katılmaz
          </div>
          <div className="chips">
            {a.diger.map((v) => (
              <span key={v.komut} className="chip">
                {v.komut}: {v.ok}/{v.n} (%{yuzde(v.oran)})
              </span>
            ))}
          </div>
          {(a.sonDiger || []).map((m, i) => (
            <div key={i} className="not11 soluk">
              {m.komut} ({m.hedef}) — {m.calisti !== true
                ? "bu hedefin ağ haritasında yok; çalıştırılmadı, çıktı oluşmadı"
                : m.obs || "eski günlük kaydında sonuç özeti yok"}
            </div>
          ))}
        </>
      )}
      <h3 style={{ marginTop: 12 }}>Öğrenen yerel envanter</h3>
      {b ? (
        <>
          <div className="chips">
            <span className="rozet">
              son 24 saatte {b.schedule.attempts_in_24h}/
              {b.schedule.limit_per_24h} tarama denemesi
            </span>
            <span className="rozet">
              cihaz {b.online_count} çevrimiçi / son {Math.min(b.device_count, 20)} gösteriliyor ({b.device_count} toplam)
            </span>
            <span className="rozet">
              sonraki tarama {sure(b.schedule.next_in_seconds)}
            </span>
            {b.last_scan && (
              <span className={"rozet " + (b.last_scan.ok ? "ok" : "uyari")}>
                son deneme {saat(b.last_scan.t)}
                {b.last_scan.probe ? ` · seçilen: ${b.last_scan.probe}` : ""}
                {Number.isFinite(b.last_scan.probe_reward)
                  ? ` · yeni kanıt ödülü ${b.last_scan.probe_reward}` : ""}
                {!b.last_scan.ok && b.last_scan.reason
                  ? ` · ${b.last_scan.reason}` : ""}
              </span>
            )}
          </div>
          {Object.keys(b.probe_learning || {}).length > 0 && (
            <div className="soluk">
              Keşif yöntemi seçimi, her yöntemin geçmişte getirdiği yeni
              cihaz/port/servis kanıtlarına göre öğreniliyor:
              {" "}{Object.entries(b.probe_learning).map(([name, stats]) => (
                `${name} ${stats.attempts} deneme · ödül ${stats.reward_total}`
              )).join(" | ")}
            </div>
          )}
          {Object.keys(b.skills || {}).length > 0 && (
            <div className="soluk">
              Beceri doğrulaması:
              {" "}{Object.entries(b.skills).map(([name, skill]) => (
                `${name} ${skill.successes || 0}/${skill.attempts || 0} `
                + `(%${Math.round((skill.confidence || 0) * 100)})`
              )).join(" · ")}
            </div>
          )}
          {b.social_learning?.enabled && (
            <div className="soluk">
              Yerel sosyal öğrenme açık · kimlik {b.social_learning.instance_id}
              {" · "}eşler {(b.social_learning.peers || []).join(", ") || "yok"}
              {" · "}alınan kanıt {b.social_learning.reports_received || 0}
            </div>
          )}
          {b.devices.length ? b.devices.slice(0, 20).map((device) => (
            <div className="not11" key={device.ip} style={{ marginTop: 8 }}>
              <strong>{device.ip}</strong>
              {device.hostname && (
                <span> · {device.hostname}</span>
              )}
              <span className="soluk">
                {" · "}{device.online ? "yanıt verdi" : "son taramada görülmedi"}
                {" · "}{device.seen_count} gözlem
              </span>
              {device.services.length > 0 && (
                <div className="chips">
                  {device.services.map((service) => (
                    <span className="chip" key={service.type}>
                      {service.type}{service.instance
                        ? ` · ${service.instance}` : ""}
                    </span>
                  ))}
                </div>
              )}
              {device.hints.length > 0 && (
                <div className="chips">
                  {device.hints.map((hint) => (
                    <span className="chip" key={hint}>olası: {hint}</span>
                  ))}
                </div>
              )}
              {device.ports.length > 0 ? device.ports.map((port) => (
                <div className="soluk" key={port.port}>
                  {port.port} · {port.name}: {port.purpose}
                  {" · "}{port.seen_count} gözlem
                </div>
              )) : <div className="soluk">bilinen açık TCP portu yok</div>}
              <div className="soluk">{device.classification_note}</div>
            </div>
          )) : (
            <div className="not11 soluk">
              Henüz ağ cihazı gözlemi yok; ilk sınırlı yerel keşif bekleniyor.
            </div>
          )}
          {b.devices.length > 20 && (
            <div className="not11 soluk" style={{ marginTop: 6 }}>
              {b.devices.length - 20} daha eski cihaz gizlendi (son 20 gösteriliyor).
            </div>
          )}
          <details style={{ marginTop: 8 }}>
            <summary>Ağ araçları ve port bilgisi belleği</summary>
            <div className="not11 soluk">
              Otomatik kullanım yerel host keşfi ve öğrenerek seçilen sınırlı
              TCP port kontrolü, mDNS duyurusu veya pasif komşu tablosu
              gözlemiyle sınırlıdır. Metasploit veritabanı sorguları yalnızca
              bilgi belleğinde bulunur; modül çalıştırılmaz.
            </div>
            {b.tools.map((tool) => (
              <div className="soluk" key={tool.tool + tool.usage}>
                <strong>{tool.tool}</strong>
                {tool.usage ? ` · ${tool.usage}` : ""}
                {" — "}{tool.purpose}
                {" · "}{tool.mode}
              {tool.learned_help && (
                <div>
                  Yerel yardım ({tool.learned_from}):{" "}
                  {tool.learned_help.join(" · ")}
                </div>
              )}
            </div>
            ))}
            {Object.keys(b.reference_learning || {}).length > 0 && (
            <div className="soluk">
              Yerel servis dosyaları:
              {" "}{Object.entries(b.reference_learning).map(([file, info]) => (
                `${file} (${info.entries_learned || 0} yeni ad)`
              )).join(" · ")}
            </div>
            )}
            <h4>Port sözlüğü</h4>
            <div className="not11 soluk">
              UDP portları bilgi amaçlıdır; otomatik tarama yalnızca belirtilen
              sınırlı TCP portlarını kontrol eder. Porttan cihaz türü kesin
              çıkarılamaz.
            </div>
            {b.port_knowledge.map((port) => (
              <div className="soluk" key={port.port}>
                <strong>{port.port} · {port.name}</strong>
                {" — "}{port.purpose}
                {port.reference_names?.length
                  ? ` · yerel dosya adları: ${port.reference_names.join(", ")}` : ""}
              </div>
            ))}
          </details>
        </>
      ) : (
        <div className="not11 soluk">
          Ağ bilgi belleği henüz oluşturulmadı.
        </div>
      )}
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

// ---------- asm öğrenme paneli ----------
export function AsmOgren({ d }) {
  const [durum, setDurum] = useState(null);
  const [cikti, setCikti] = useState("");
  const [yukleniyor, setYukleniyor] = useState(false);
  const [mesaj, setMesaj] = useState(null);
  const [dakika, setDakika] = useState("1");

  useEffect(() => {
    const yenile = async () => {
      try {
        const r = await al("/asm/durum");
        setDurum(r);
      } catch { /* yoksay */ }
    };
    yenile();
    const i = setInterval(yenile, 15000);
    return () => clearInterval(i);
  }, []);

  async function baslat() {
    const dk = Math.min(Math.max(parseFloat(dakika || "1"), 0.1), 600);
    setDakika(String(dk));
    setYukleniyor(true);
    setMesaj(null);
    try {
      const r = await post("/asm/ogren", { dakika: dk });
      setCikti(r.cikti || "");
      if (r.ok) {
        const r2 = await al("/asm/durum");
        setDurum(r2);
        setMesaj(`✓ ${dk} dakika öğrenme tamamlandı`);
      } else {
        setMesaj("HATA: " + (r.cikti || r.hata));
      }
    } catch (e) {
      setMesaj("HATA: " + (e?.message || e));
    } finally {
      setYukleniyor(false);
    }
  }

  const say = (x) => (Number.isFinite(x) ? Math.round(x) : 0).toLocaleString("tr-TR");
  const yuzde2 = (x) => (Number.isFinite(x) ? (x * 100).toFixed(1) : "—");
  const renk = (o) => (o > 0.7 ? "var(--yesil)" : o > 0.4 ? "var(--sari)" : "var(--kirmizi)");

  if (!durum) {
    return (
      <div className="kart">
        <h2>ASM Öğrenme<span className="yan">yükleniyor…</span></h2>
        <div className="not11 soluk">veri bekleniyor</div>
      </div>
    );
  }

  const son20 = durum.son_20 || {};

  return (
    <div className="kart">
      <h2>ASM Öğrenme
        <span className="yan">
          {say(durum.toplam_gorev)} görev · seviye {durum.maks_seviye}
        </span>
      </h2>

      <div className="istat">
        <div><div className="sayi">{say(durum.toplam_gorev)}</div>
          <div className="alt">TOPLAMLI GÖREV</div></div>
        <div><div className="sayi">{say(durum.primtik)}</div>
          <div className="alt">PRIMTİK (KALIP)</div></div>
        <div><div className="sayi">{say(durum.basarisiz)}</div>
          <div className="alt">BAŞARISIZ ÖNBELLEK</div></div>
        <div><div className="sayi">{say(durum.baglam)}</div>
          <div className="alt">BAĞLAM</div></div>
      </div>

      <div className="istat" style={{ marginTop: 8 }}>
        <div><div className="sayi">{yuzde2(son20.cozulme_orani)}%</div>
          <div className="alt">SON 20 ÇÖZÜLME ORANI</div></div>
        <div><div className="sayi">{say(son20.ort_deneme)}</div>
          <div className="alt">ORT. DENEME</div></div>
      </div>

      <div style={{ marginTop: 8 }}>
        <Cubuk etiket="Çözüm Oranı" deger={son20.cozulme_orani || 0}
          maks={1} renk={renk(son20.cozulme_orani || 0)}
          sag={`${yuzde2(son20.cozulme_orani)}%`} />
      </div>

      <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <input type="number" value={dakika} min="0.1" max="600" step="0.1"
          onChange={(e) => setDakika(e.target.value)}
          style={{ width: 70, padding: 4 }} />
        <span className="not11 soluk">dakika</span>
        <button className="dgm" disabled={yukleniyor}
          onClick={baslat}>
          {yukleniyor ? "Çalışıyor…" : "Öğren Başlat"}
        </button>
        {mesaj && <span className={"not11 " + (mesaj.startsWith("✓") ? "ok" : "hata")} style={{ marginLeft: 8 }}>{mesaj}</span>}
      </div>

      {cikti && (
        <div className="not11 soluk" style={{ marginTop: 8, whiteSpace: "pre-wrap", fontSize: 12 }}>
          {cikti.slice(0, 2000)}
        </div>
      )}
    </div>
  );
}


// ---------- kod düzenleme durumu paneli ----------

export function KodDurum({ d }) {
  const [kayitlar, setKayitlar] = useState([]);
  const [yukleniyor, setYukleniyor] = useState(true);

  useEffect(() => {
    al("/kod-durum")
      .then((r) => setKayitlar(r.kayitlar || []))
      .catch(() => setKayitlar([]))
      .finally(() => setYukleniyor(false));
  }, []);

  const renk = (kind) =>
    kind === "kod_duzenle_gerialindi" ? "var(--kirmizi)" : "var(--yesil)";

  if (yukleniyor) {
    return (
      <div className="kart">
        <h2>Kod Düzenleme<span className="yan">yükleniyor…</span></h2>
        <div className="not11 soluk">veri bekleniyor</div>
      </div>
    );
  }

  return (
    <div className="kart">
      <h2>Kod Düzenleme (Aşama 4)
        <span className="yan">
          {kayitlar.length} kayıt
        </span>
      </h2>
      {kayitlar.length === 0 ? (
        <div className="not11 soluk">henüz kod düzenlemesi yapılmadı</div>
      ) : (
        <table className="kod-tablo">
          <thead>
            <tr>
              <th>Zaman</th>
              <th>Dosya</th>
              <th>Önceki</th>
              <th>Yeni</th>
              <th>Durum</th>
            </tr>
          </thead>
          <tbody>
            {kayitlar.map((k, i) => (
              <tr key={i}>
                <td>{saat(k.t)}</td>
                <td>{k.dosya}</td>
                <td>{k.onceki_bayt ?? "—"}</td>
                <td>{k.yeni_bayt ?? "—"}</td>
                <td>
                  <span
                    className="rozet"
                    style={{ color: renk(k.kind), fontWeight: "bold" }}
                  >
                    {k.kind === "kod_duzenle_gerialindi"
                      ? "GERİ YÜKLENDİ"
                      : k.mesaj || "başarılı"}
                  </span>
                  {k.hata && (
                    <span className="not11 soluk" style={{ fontSize: 10 }}>
                      · {k.hata.slice(0, 60)}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---------- hata sınıflandırması (Faz 1) ----------

export function Hatalar({ d }) {
  const hatalar = d.hatalar || [];
  if (!hatalar.length) {
    return (
      <div className="kart">
        <h2>Hata Sınıflandırması</h2>
        <div className="not11 soluk">henüz hata kaydı yok</div>
      </div>
    );
  }
  return (
    <div className="kart">
      <h2>Hata Sınıflandırması</h2>
      <table>
        <thead>
          <tr>
            <th>tür</th><th className="sag">odul</th>
            <th className="sag">guven</th><th className="sag">eylem</th>
          </tr>
        </thead>
        <tbody>
          {hatalar.slice().reverse().map((h, i) => (
            <tr key={i}>
              <td>
                <b>{h.tur}</b> <span className="not11 soluk">{saat(h.t)}</span>
              </td>
              <td className="sag">{h.odul != null ? h.odul.toFixed(2) : "—"}</td>
              <td className="sag">{h.guven != null ? h.guven.toFixed(2) : "—"}</td>
              <td className="sag">{h.eylem}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------- karar neden / kanıt (Faz 5) ----------

export function Neden({ d }) {
  const kayitlar = d.neden || [];
  if (!kayitlar.length) {
    return (
      <div className="kart">
        <h2>Neden / Kanıt</h2>
        <div className="not11 soluk">henüz karar kaydı yok</div>
      </div>
    );
  }
  return (
    <div className="kart">
      <h2>Neden / Kanıt</h2>
      <table>
        <thead>
          <tr>
            <th>eylem</th><th className="sag">guven</th>
            <th className="sag">tehlike</th><th>ozellikler</th>
          </tr>
        </thead>
        <tbody>
          {kayitlar.slice().reverse().map((k, i) => (
            <tr key={i}>
              <td>
                <b>{k.eylem}</b>
                <span className="not11 soluk">{saat(k.t)}</span>
              </td>
              <td className="sag">{k.guven != null ? k.guven.toFixed(2) : "—"}</td>
              <td className="sag">
                {k.tehlike_olasiligi != null
                  ? (k.tehlike_olasiligi * 100).toFixed(0) + "%"
                  : "—"}
              </td>
              <td className="sag">
                {(k.ozellik_katkilari || []).slice(0, 3).map((ok, j) => (
                  <span key={j}>
                    {ok.ozellik}={ok.agirlik.toFixed(2)}
                    {j < 2 ? " · " : ""}
                  </span>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------- dışsal geri bildirim (Faz 7) ----------

export function DisSal({ d }) {
  const kayitlar = d.disSal || [];
  if (!kayitlar.length) {
    return (
      <div className="kart">
        <h2>Dışsal Geri Bildirim</h2>
        <div className="not11 soluk">henüz geri bildirim yok</div>
      </div>
    );
  }
  const iyi = kayitlar.filter((k) => k.deger === "iyi").length;
  const kotu = kayitlar.filter((k) => k.deger === "kotu").length;
  return (
    <div className="kart">
      <h2>Dışsal Geri Bildirim</h2>
      <div className="istat">
        <div>
          <div className="sayi">{iyi}</div>
          <div className="alt">İYİ</div>
        </div>
        <div>
          <div className="sayi">{kotu}</div>
          <div className="alt">KOTU</div>
        </div>
      </div>
      <table>
        <thead>
          <tr><th>değer</th><th className="sag">zaman</th></tr>
        </thead>
        <tbody>
          {kayitlar.slice().reverse().map((k, i) => (
            <tr key={i}>
              <td><b>{k.deger}</b></td>
              <td className="sag">{saat(k.t)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
