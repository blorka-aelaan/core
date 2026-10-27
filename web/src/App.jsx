import { useEffect, useState } from "react";
import {
  al, post, Vital, Atolye, Kullan, Ag, Beyin, Uyku, Uzuv, Ders, Kapi, Akim, UstBeyn, sure,
} from "./panels.jsx";

// ---------- canlı pano bağlamı: SSE + ilk yükleme ----------
function usePano() {
  const [durum, setDurum] = useState(null);
  const [olaylar, setOlaylar] = useState([]);
  const [bagli, setBagli] = useState(false);
  useEffect(() => {
    let es = null;
    al("/state").then(setDurum).catch(() => {});
    al("/feed?n=250").then(setOlaylar).catch(() => {});
    try {
      es = new EventSource("/api/stream");
      es.onopen = () => setBagli(true);
      es.onerror = () => setBagli(false);
      es.addEventListener("state", (e) => {
        try { setDurum(JSON.parse(e.data)); } catch { /* yoksay */ }
      });
      es.addEventListener("feed", (e) => {
        try { setOlaylar(JSON.parse(e.data)); } catch { /* yoksay */ }
      });
      es.addEventListener("journal", (e) => {
        try {
          const y = JSON.parse(e.data);
          // gelen olaylar eski→yeni; akış yeni en üstte
          setOlaylar((a) => [...y.slice().reverse(), ...a].slice(0, 400));
        } catch { /* yoksay */ }
      });
    } catch {
      setBagli(false);
    }
    return () => { if (es) es.close(); };
  }, []);
  return { durum, olaylar, bagli };
}

function ServisRozet({ ad, v }) {
  return (
    <span className={"rozet " + (v?.aktif ? "ok" : "kotu")}
      style={{ marginRight: 6 }}>
      {ad}: {v?.durum || "?"}{v?.pid ? ` · ${v.pid}` : ""}
    </span>
  );
}

export default function App() {
  const { durum, olaylar, bagli } = usePano();
  const [not, setNot] = useState(null);

  async function yonet(action, etiket) {
    if (!window.confirm(`${etiket}?\n(Temiz sinyal → systemd geri getirir.)`)) {
      return;
    }
    try {
      const r = await post("/manage", { action });
      setNot(r.ok ? `✓ ${etiket} — ${r.not}` : `HATA: ${r.cikti || r.hata}`);
    } catch (e) {
      setNot(`HATA: ${e?.message || e}`);
    }
    setTimeout(() => setNot(null), 8000);
  }

  const c = durum?.canli, s = durum?.servisler;
  return (
    <>
      <div className="baslik">
        <h1>CORE</h1>
        <span>
          <span className={"nokta " + (c?.uyariyor ? "canli" : "uyari")} />
          {c ? (c.uyariyor ? `${c.ad} — yaşıyor` : `${c.ad} — sessiz`)
            : "bağlanıyor…"}
        </span>
        <span className="kesit">
          {durum ? `çalışma ${sure(c?.uptime_s)}` : ""}
          {c?.son_act_s != null ? ` · son nabız ${c.son_act_s} sn` : ""}
          {durum ? ` · ${durum.toplam_satir} jurnal satırı` : ""}
          {durum?.bozuk ? ` · ${durum.bozuk} bozuk` : ""}
        </span>
        <span className="sag">
          {s && <>
            <ServisRozet ad="organizma" v={s.organizma} />
            <ServisRozet ad="ag" v={s.ag} />
            <button className="dgm tiny"
              onClick={() => yonet("restart_main",
                "organizmayı yeniden başlat")}>↻ organizma</button>
            <button className="dgm tiny"
              onClick={() => yonet("restart_ag",
                "ag'yi yeniden başlat")}>↻ ag</button>
          </>}
          <span className={"rozet " + (bagli ? "ok" : "kotu")}>
            SSE {bagli ? "●" : "○"}
          </span>
        </span>
      </div>
      {not && (
        <div className={"not11 " + (not.startsWith("HATA") ? "hata" : "ok")}
          style={{ marginBottom: 8 }}>{not}</div>
      )}
      <div className="izgara">
        <div className="sutun">
          <Vital d={durum} />
          {durum && <Atolye d={durum} />}
          {durum && <Kullan d={durum} />}
          {durum && <Ag d={durum} />}
        </div>
        <div className="sutun">
          {durum && <UstBeyn d={durum} />}
          {durum && <Beyin d={durum} />}
          {durum && <Uzuv d={durum} />}
          {durum && <Ders d={durum} />}
          <Kapi />
          {durum && <Uyku d={durum} />}
        </div>
        <div className="sutun">
          <Akim olaylar={olaylar} bagli={bagli} />
        </div>
      </div>
    </>
  );
}
