"""CORE reward — merkezi, yapılandırılabilir bileşik ödül hesaplayıcısı.

Tüm ödül bileşenleri tek sınıfın altında toplanır, main.py'den ayrıştırılır,
test edilebilir ve yapılandırılabilir hale getirilir.

Bileşenler:
  * sistem ödülü: gain − cost + veto + relief + merak + novel
  * acı & kurtuluş: pain_penalty, relief_bonus
  * üst-beyin ödülü: komut-amacı-hizalı bonus/ceza ([-1, +1] aralığına kırpılır)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _as_float(value: Any, default: float = 0.0) -> float:
    """Güvenli float dönüşümü: Any türünden gelen değeri float'a çevirir.

    body.json / res sözlüklerindeki değerler Any olarak gelir; bu yardımcı
    Pylance'ın float(Any) tür hatasını önler ve bozuk değerleri default'a düşürür.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class OdulHesaplayici:
    """Merkezi ödül hesaplayıcısı.

    Her bileşenin ağırlığı yapılandırılabilir. Tüm metodlar pure fonksiyon
    gibidir — dış durum değiştirmez, sadece hesaplar ve döndürür.
    """

    # ---------- Varsayılan ağırlıklar (body.json'dan override edilebilir) ----------
    W_GAIN: float = 1.0          # kazanılan enerji / kaynak
    W_COST: float = 1.0          # eylem maliyeti (çıkarılır)
    W_VETO: float = 1.0          # inkâr hakkı (bırakma eylemi)
    W_RELIEF: float = 0.4        # açlık azaltma çarpanı
    W_MERAK: float = 1.0         # atölye merak sinyali
    W_NOVEL: float = 3.0         # yenilik bonusu
    W_NOVEL_CMD: float = 4.0     # yeni komut keşfi bonusu
    W_BITE: float = 2.0          # .bite bulma bonusu
    W_REST_NEST: float = 1.0     # dinlenme / yuva bonusu
    W_PAIN_PENALTY: float = 1.0  # acı ceza çarpanı (drives.pain_penalty ile çarpılır)
    W_RELIEF_BONUS: float = 1.0  # kurtuluş ödülü çarpanı (drives.relief_bonus ile çarpılır)
    W_VERIFIED_SUCCESS: float = 2.0
    W_VERIFIED_FAILURE: float = 2.0
    W_DIS_SAL_GERIBILDIRIM: float = 1.0  # Faz 7: dışsal geri bildirim ödülü
    # ---------- Yeni: Beden duyuları ödülü (Aşama 2) ----------
    W_BEDEN_BASKI: float = 1.5   # disk/bellek baskısı cezası
    W_YENI_KEŞIF: float = 2.0    # yeni dizin/cihaz/ağ keşfi bonusu
    W_BEDEN_SAGLIK: float = 1.0  # enerji/aclık denge ödülü

    def __init__(self, cfg: Optional[Dict[str, Any]] = None) -> None:
        """Ağırlıkları cfg'den yükler veya varsayılanları kullanır."""
        self.cfg = cfg or {}
        self._yukle_agirliklar()

    def _yukle_agirliklar(self) -> None:
        """body.json / kurallar.json'dan ağırlıkları okur."""
        reward_cfg = self.cfg.get("reward", {})
        self.W_GAIN = _as_float(reward_cfg.get("w_gain", self.W_GAIN))
        self.W_COST = _as_float(reward_cfg.get("w_cost", self.W_COST))
        self.W_VETO = _as_float(reward_cfg.get("w_veto", self.W_VETO))
        self.W_RELIEF = _as_float(reward_cfg.get("w_relief", self.W_RELIEF))
        self.W_MERAK = _as_float(reward_cfg.get("w_merak", self.W_MERAK))
        self.W_NOVEL = _as_float(reward_cfg.get("w_novel", self.W_NOVEL))
        self.W_NOVEL_CMD = _as_float(reward_cfg.get("w_novel_cmd", self.W_NOVEL_CMD))
        self.W_BITE = _as_float(reward_cfg.get("w_bite", self.W_BITE))
        self.W_REST_NEST = _as_float(reward_cfg.get("w_rest_nest", self.W_REST_NEST))
        self.W_PAIN_PENALTY = _as_float(reward_cfg.get("w_pain_penalty", self.W_PAIN_PENALTY))
        self.W_RELIEF_BONUS = _as_float(reward_cfg.get("w_relief_bonus", self.W_RELIEF_BONUS))
        self.W_VERIFIED_SUCCESS = _as_float(
            reward_cfg.get("w_verified_success", self.W_VERIFIED_SUCCESS)
        )
        self.W_VERIFIED_FAILURE = _as_float(
            reward_cfg.get("w_verified_failure", self.W_VERIFIED_FAILURE)
        )
        self.W_DIS_SAL_GERIBILDIRIM = _as_float(
            reward_cfg.get("w_dis_sal_geribildirim", self.W_DIS_SAL_GERIBILDIRIM)
        )
        # ---------- Yeni: Beden duyuları ödülü ----------
        self.W_BEDEN_BASKI = _as_float(
            reward_cfg.get("w_beden_baski", self.W_BEDEN_BASKI)
        )
        self.W_YENI_KEŞIF = _as_float(
            reward_cfg.get("w_yeni_keşif", self.W_YENI_KEŞIF)
        )
        self.W_BEDEN_SAGLIK = _as_float(
            reward_cfg.get("w_beden_saglik", self.W_BEDEN_SAGLIK)
        )

    # ------------------------------------------------------------------ sistem ödül

    def sistem_odulu(
        self,
        gain: float,
        cost: float,
        veto: float,
        relief_done: float,
        res: Dict[str, Any],
        act: str,
    ) -> float:
        """Temel sistem ödülü: gain − cost + veto + relief + merak + novel + ..."""
        r = (
            gain * self.W_GAIN
            - cost * self.W_COST
            + veto * self.W_VETO
            + relief_done * self.W_RELIEF
            + _as_float(res.get("merak", 0.0)) * self.W_MERAK
            + self._yenilik_odulu(res, act)
            + (
                self.W_BITE
                if act.startswith("go:") and ".bite" in res.get("obs", "")
                else 0.0
            )
            + (self.W_REST_NEST if act in ("rest", "nest") else 0.0)
        )
        # ---------- Yeni: Beden duyuları ödülü (Aşama 2) ----------
        _beden_baski = _as_float(res.get("beden_baski", 0.0))   # 0..1, yüksek = kötü
        _yeni_keşif = _as_float(res.get("yeni_keşif", 0.0))     # 0..1, yüksek = iyi
        _beden_saglik = _as_float(res.get("beden_saglik", 0.0)) # 0..1, yüksek = iyi

        r += (
            -_beden_baski * self.W_BEDEN_BASKI
            + _yeni_keşif * self.W_YENI_KEŞIF
            + _beden_saglik * self.W_BEDEN_SAGLIK
        )

        return float(r + self._dogrulanmis_komut_odulu(res, act))

    def _yenilik_odulu(self, res: Dict[str, Any], act: str) -> float:
        novelty = (
            _as_float(res.get("novel", 0.0)) * self.W_NOVEL
            + (self.W_NOVEL_CMD if res.get("novel_cmd") else 0.0)
        )
        if (act.startswith(("cmd:", "help:"))
                and not res.get("ilerleme")
                and res.get("dogru") is False and novelty > 0.0):
            novelty = min(
                novelty, max(0.0, self.W_VERIFIED_FAILURE * 0.9)
            )
        return novelty

    def _dogrulanmis_komut_odulu(
        self, res: Dict[str, Any], act: str
    ) -> float:
        if not act.startswith(("cmd:", "help:")) or not isinstance(
            res.get("dogru"), bool
        ):
            return 0.0
        if res.get("ilerleme"):
            return 0.0
        return (
            self.W_VERIFIED_SUCCESS
            if res["dogru"]
            else -self.W_VERIFIED_FAILURE
        )

    # ------------------------------------------------------------------ dışsal geri bildirim

    def dis_geribildirim_odulu(self, deger: str) -> float:
        """Dışsal (kullanıcı/kapıdan gelen) geri bildirimi ödül olarak döndürür.

        Parametreler
        ----------
        deger : str
            "iyi" → pozitif ödül, "kotu" → negatif ödül, diğer → 0.0.
        """
        if deger == "iyi":
            return self.W_DIS_SAL_GERIBILDIRIM
        if deger == "kotu":
            return -self.W_DIS_SAL_GERIBILDIRIM
        return 0.0

    # ------------------------------------------------------------------ acı / kurtuluş

    def aci_ve_kurtulus(
        self,
        reward: float,
        in_danger: bool,
        was_danger: bool,
        pain: float,
        pain_penalty: float,
        relief_bonus: float,
    ) -> float:
        """Acı cezası veya kurtuluş ödülü uygular."""
        if in_danger:
            reward -= pain * pain_penalty * self.W_PAIN_PENALTY
        elif was_danger:
            reward += relief_bonus * self.W_RELIEF_BONUS
        return float(reward)

    # ------------------------------------------------------------------ üst-beyin ödülü

    def ust_beyn_odulu(
        self,
        reward: float,
        komut: Optional[str],
        sinyal: Optional[List[float]] = None,
        drives_state: Optional[Dict[str, Any]] = None,
        asm_son: Optional[Dict[str, Any]] = None,
        budanan: int = 0,
        bag_once: int = 0,
        reddedildi: bool = False,
    ) -> float:
        """Üst-beyin (MLP) komutu için amaç-hizalı ödül hesaplar.

        Yalnızca komutun amacıyla ilgili sinyaller öğrenilir; genel sistem
        ödülü parametresi eski çağrılarla uyum için korunur.
        """
        if komut is None:
            return 0.0

        odul = 0.0

        # Komut-amacı-hizalı bonuslar
        if komut == "acil_dinlen":
            if drives_state and drives_state.get("in_danger", False):
                odul += 0.2
        elif komut == "acil_yem":
            if drives_state and drives_state.get("aclik_once", 0) > 50.0:
                odul += 0.25
            if drives_state and drives_state.get("yemek_var", False):
                odul += 0.1
            else:
                odul -= 0.1
        elif komut == "kapat_ag":
            if sinyal is not None and len(sinyal) > 20 and sinyal[20] > 0.0:
                odul += 0.4
            else:
                odul -= 0.05
        elif komut == "kisitla_dosya":
            if sinyal is not None:
                mesaj_var = sinyal[21] if len(sinyal) > 21 else 0.0
                olum_risk = sinyal[23] if len(sinyal) > 23 else 0.0
                if mesaj_var > 0.0 or olum_risk > 0.0:
                    odul += 0.3
                else:
                    odul -= 0.05
        elif komut == "guvenli_mod":
            if drives_state and drives_state.get("in_danger", False):
                odul += 0.25
            else:
                odul -= 0.05
        elif komut == "asm_ogren":
            if asm_son:
                gorev = asm_son.get("oturum_gorev", 0)
                cozulen = asm_son.get("oturum_cozulen", 0)
                if gorev > 0:
                    odul += 0.4 * (cozulen / gorev) - 0.1
                if asm_son.get("yeni_primtik", 0) > 0:
                    odul += 0.15
        elif komut == "sifirla":
            BAG_KAP = 600
            bag_son = bag_once if bag_once else 0
            if bag_son <= BAG_KAP:
                odul -= 0.02
            elif budanan:
                odul += 0.15
            else:
                odul -= 0.10
        elif komut == "yok":
            # "yok" bir karar adımdır: tehlikede müdahale etmemek ceza alır
            if drives_state and drives_state.get("in_danger", False):
                odul -= 0.2

        return float(max(-1.0, min(1.0, odul)))

    # ------------------------------------------------------------------ birleşik hesaplama

    def hesapla(
        self,
        gain: float,
        cost: float,
        veto: float,
        relief_done: float,
        res: Dict[str, Any],
        act: str,
        in_danger: bool,
        was_danger: bool,
        pain: float,
        pain_penalty: float,
        relief_bonus: float,
        komut: Optional[str] = None,
        sinyal: Optional[List[float]] = None,
        drives_state: Optional[Dict[str, Any]] = None,
        asm_son: Optional[Dict[str, Any]] = None,
        budanan: int = 0,
        bag_once: int = 0,
        reddedildi: bool = False,
        dis_sal_geribildirim: Optional[str] = None,
    ) -> Dict[str, float]:
        """Tüm ödül bileşenlerini birleşik hesaplar ve ayrıntıları döndürür.

        Döner:
          {"sistem": x, "aci_kurtulus": y (delta),
           "alt_beyin": z, "ust_beyn": q, "yenilik": n,
           "dogrulanmis_komut": c, "dis_sal_geribildirim": d, "toplam": w}
        """
        sistem = self.sistem_odulu(gain, cost, veto, relief_done, res, act)
        aci_kurtulus = self.aci_ve_kurtulus(
            sistem, in_danger, was_danger, pain, pain_penalty, relief_bonus
        )
        ust = self.ust_beyn_odulu(
            aci_kurtulus, komut, sinyal, drives_state, asm_son,
            budanan, bag_once, reddedildi,
        )
        dis = self.dis_geribildirim_odulu(dis_sal_geribildirim) \
            if dis_sal_geribildirim else 0.0
        toplam = aci_kurtulus + ust + dis
        return {
            "sistem": round(sistem, 4),
            "aci_kurtulus": round(aci_kurtulus - sistem, 4),
            "alt_beyin": round(aci_kurtulus, 4),
            "ust_beyn": round(ust, 4),
            "yenilik": round(self._yenilik_odulu(res, act), 4),
            "dogrulanmis_komut": round(
                self._dogrulanmis_komut_odulu(res, act), 4
            ),
            "dis_sal_geribildirim": round(dis, 4),
            "toplam": round(toplam, 4),
        }


# --- Kolay kullanım için fonksiyon düzey wrapper ---

_hesaplayici: Optional[OdulHesaplayici] = None
_hesaplayici_cfg: Optional[Dict[str, Any]] = None


def get_hesaplayici(cfg: Optional[Dict[str, Any]] = None) -> OdulHesaplayici:
    """Ödül hesaplayıcısı örneği döndürür.

    cfg verildiğinde her seferinde yeni bir örnek oluşturulur (farklı
    yapılandırmaların aynı anda kullanılabilmesi için). cfg verilmezse
    önbellekli varsayılan örnek döndürülür.
    """
    global _hesaplayici, _hesaplayici_cfg
    if cfg is not None:
        return OdulHesaplayici(cfg)
    if _hesaplayici is None or _hesaplayici_cfg != cfg:
        _hesaplayici = OdulHesaplayici(cfg)
        _hesaplayici_cfg = cfg
    return _hesaplayici


def odul_hesapla(
    gain: float,
    cost: float,
    veto: float,
    relief_done: float,
    res: Dict[str, Any],
    act: str,
    in_danger: bool,
    was_danger: bool,
    pain: float,
    pain_penalty: float,
    relief_bonus: float,
    cfg: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> float:
    """Hızlı çağrı: tek float ödül döndürür."""
    h = get_hesaplayici(cfg)
    sonuc = h.hesapla(
        gain, cost, veto, relief_done, res, act,
        in_danger, was_danger, pain, pain_penalty, relief_bonus,
        **kwargs,
    )
    return sonuc["toplam"]