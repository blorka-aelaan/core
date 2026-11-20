"""
CORE Uzuv — x86-64 Assembly Bilgi Tabanı ve Öğrenme Organu

Ayrı beyin dosyası (asm_beyn.json), ayrı günlük dosyası (asm_log.jsonl),
ayrı ders dosyası (asm_dersler.jsonl). Ana organizma beynine karışmaz,
danışmanlık verir.

Kullanım örneği:
    from uzuv.asm_uzuv import AsmUzuv
    asm = AsmUzuv()
    asm.sorgula("RAX")
    asm.dene_kod("mov rax, 5", basarili=True)
    asm.ogren_hata("mov [rax], [rbx]", "bellekten belleğe doğrudan transfer yapılamaz")
    asm.rapor()
"""

import json
import os
import random
import re
import time
from pathlib import Path
from collections import defaultdict

CORE_ROOT = Path(__file__).resolve().parent.parent
UZUV_DIR = CORE_ROOT / "uzuv"

BEYIN_DOSYA = UZUV_DIR / "asm_beyn.json"
GUNLUK_DOSYA = UZUV_DIR / "asm_log.jsonl"
DERS_DOSYA = UZUV_DIR / "asm_dersler.jsonl"


class AsmUzuv:
    """
    x86-64 Assembly bilgi tabanı ve öğrenme organu.

    Her örneğe özel kendi beyin ve günlük dosyalarına sahiptir.
    """
    # ---------------------------------------------------------------- Bilgi Tabanı (PDF'den)
    REGISTERLER = {
        "RAX": {"32": "EAX", "16": "AX", "8": "AL",
                "rol": "Akümülatör",
                "ai_rol": "Fonksiyon dönüş değerleri"},
        "RBX": {"32": "EBX", "16": "BX", "8": "BL",
                "rol": "Taban Yazmacı",
                "ai_rol": "Veri göstericisi"},
        "RCX": {"32": "ECX", "16": "CX", "8": "CL",
                "rol": "Sayaç Yazmacı",
                "ai_rol": "Döngüler ve string işlemleri"},
        "RDX": {"32": "EDX", "16": "DX", "8": "DL",
                "rol": "Veri Yazmacı",
                "ai_rol": "Girdi-Çıktı ve büyük aritmetik"},
        "RSI": {"32": "ESI", "16": "SI", "8": "SIL",
                "rol": "Kaynak Göstericisi",
                "ai_rol": "String/bellek kopyalama"},
        "RDI": {"32": "EDI", "16": "DI", "8": "DIL",
                "rol": "Hedef Göstericisi",
                "ai_rol": "String/bellek kopyalama"},
        "RBP": {"32": "EBP", "16": "BP", "8": "BPL",
                "rol": "Taban Göstericisi",
                "ai_rol": "Fonksiyon yerel yığın çerçevesi"},
        "RSP": {"32": "ESP", "16": "SP", "8": "SPL",
                "rol": "Yığın Göstericisi",
                "ai_rol": "Anlık stack tepesi adresi"},
        "RIP": {"32": "EIP", "16": "IP", "8": None,
                "rol": "Komut Göstericisi",
                "ai_rol": "Çalıştırılacak bir sonraki satır"},
    }

    EK_YAZMACLAR = {
        "R8-R15": {"32": "R8D-R15D", "16": "R8W-R15W", "8": "R8B-R15B",
                   "rol": "Genel Amaçlı Ek Yazmaçlar",
                   "ai_rol": "Fonksiyon parametreleri (x64)"},
    }

    KOMUTLAR = {
        "MOV": {"operanlar": "dest, src", "bayraklar": "Yok",
                "aciklama": "src içeriğini dest alanına kopyalar. Bellekten belleğe doğrudan transfer yapılamaz."},
        "LEA": {"operanlar": "dest, src", "bayraklar": "Yok",
                "aciklama": "Etkin adresi hesaplar ve dest alanına yükler. Bellek içeriğini okumaz, adresi alır."},
        "PUSH": {"operanlar": "src", "bayraklar": "Yok",
                 "aciklama": "RSP değerini 8 azaltır ve src değerini yığına (stack) yazar."},
        "POP": {"operanlar": "dest", "bayraklar": "Yok",
                "aciklama": "Yığının tepesindeki değeri dest alanına yazar ve RSP değerini 8 artırır."},
        "ADD": {"operanlar": "dest, src", "bayraklar": "ZF, SF, CF, OF",
                "aciklama": "dest = dest + src işlemini gerçekleştirir."},
        "SUB": {"operanlar": "dest, src", "bayraklar": "ZF, SF, CF, OF",
                "aciklama": "dest = dest - src işlemini gerçekleştirir."},
    }

    KOMUTLAR2 = {
        "IMUL": {"operanlar": "dest, src", "bayraklar": "CF, OF",
                 "aciklama": "İşaretli çarpma işlemi. dest = dest * src."},
        "IDIV": {"operanlar": "src", "bayraklar": "Belirsiz",
                 "aciklama": "İşaretli bölme. RDX:RAX çiftini src değerine böler. Bölüm RAX, kalan RDX'e yazılır."},
        "AND": {"operanlar": "dest, src", "bayraklar": "ZF, SF, CF=0, OF=0",
                "aciklama": "Bit düzeyinde VE mantıksal işlemi uygular. Maskeleme için kullanılır."},
        "OR": {"operanlar": "dest, src", "bayraklar": "ZF, SF, CF=0, OF=0",
               "aciklama": "Bit düzeyinde VEYA mantıksal işlemi uygular. Bitsel açma yapar."},
        "XOR": {"operanlar": "dest, src", "bayraklar": "ZF, SF, CF=0, OF=0",
                "aciklama": "Bit düzeyinde ÖZEL VEYA işlemi uygular. Kendisiyle XOR'lama register sıfırlama desenidir."},
        "CMP": {"operanlar": "op1, op2", "bayraklar": "ZF, SF, CF, OF",
                "aciklama": "op1 - op2 çıkarma işlemi yapar ama sonucu kaydetmez. Sadece bayrakları günceller."},
        "TEST": {"operanlar": "op1, op2", "bayraklar": "ZF, SF, CF=0, OF=0",
                 "aciklama": "op1 & op2 mantıksal VE işlemi yapar ama sonucu kaydetmez. Sıfır testi için idealdir."},
        "JMP": {"operanlar": "label", "bayraklar": "Yok",
                "aciklama": "Koşulsuz olarak belirtilen adrese/etikete atlar. RIP değerini günceller. Register ya da bellek üzerinden dolaylı atlama da olur (jmp rax)."},
        "JE": {"operanlar": "label", "bayraklar": "Yok",
               "aciklama": "Eğer Sıfır Bayrağı (ZF = 1) ise atlar. Eşitlik durumunu kontrol eder."},
        "JZ": {"operanlar": "label", "bayraklar": "Yok",
               "aciklama": "JE'nin takma adı. Zero Flag ise atlar."},
        "JNE": {"operanlar": "label", "bayraklar": "Yok",
                "aciklama": "Eğer Sıfır Bayrağı sıfır ise (ZF = 0) atlar. Eşit olmama durumu."},
        "JNZ": {"operanlar": "label", "bayraklar": "Yok",
                "aciklama": "JNE'nin takma adı."},
        "JG": {"operanlar": "label", "bayraklar": "Yok",
               "aciklama": "Büyüktse atlar (İşaretli)."},
        "JL": {"operanlar": "label", "bayraklar": "Yok",
               "aciklama": "Küçükse atlar (İşaretli)."},
        "CALL": {"operanlar": "label", "bayraklar": "Yok",
                 "aciklama": "Bir sonraki komutun adresini (RIP) stack'e pushlar ve fonksiyona atlar."},
        "RET": {"operanlar": "Yok", "bayraklar": "Yok",
                "aciklama": "Stack'ten dönüş adresini poplar ve RIP'e yazar. Fonksiyondan döner."},
        "INC": {"operanlar": "dest", "bayraklar": "ZF, SF, CF, OF",
                "aciklama": "dest değerini 1 artırır."},
        "DEC": {"operanlar": "dest", "bayraklar": "ZF, SF, CF, OF",
                "aciklama": "dest değerini 1 azaltır."},
        "NEG": {"operanlar": "dest", "bayraklar": "ZF, SF, CF, OF",
                "aciklama": "dest değerinin işaretini ters çevirir (iki'lik tamlayıcı)."},
        "NOT": {"operanlar": "dest", "bayraklar": "Yok",
                "aciklama": "dest değerinin bitlerini ters çevirir (bit complement)."},
        "SHL": {"operanlar": "dest, count", "bayraklar": "ZF, SF, CF, OF",
                "aciklama": "dest değerini count kadar sola kaydırır. count sabit sayı ya da CL olabilir."},
        "SHR": {"operanlar": "dest, count", "bayraklar": "ZF, SF, CF, OF",
                "aciklama": "dest değerini count kadar sağa kaydırır (mantıksal). count sabit sayı ya da CL olabilir."},
        "ROL": {"operanlar": "dest, count", "bayraklar": "CF, OF",
                "aciklama": "dest değerini count kadar sola döndürür (rotate)."},
        "ROR": {"operanlar": "dest, count", "bayraklar": "CF, OF",
                "aciklama": "dest değerini count kadar sağa döndürür (rotate)."},
        "XCHG": {"operanlar": "op1, op2", "bayraklar": "Yok",
                 "aciklama": "İki operandın değerini birbirine değiştirir."},
        "INT": {"operanlar": "imm8", "bayraklar": "Yok",
                "aciklama": "Belirtilen kesme numarasıyla çekirdeğe geçiş yapar."},
        "SYSCALL": {"operanlar": "Yok", "bayraklar": "Yok",
                    "aciklama": "x64 hızlı sistem çağrısı. Sayı rax'ta, argümanlar rdi, rsi, rdx, r10, r8, r9'da."},
        "NOP": {"operanlar": "Yok", "bayraklar": "Yok",
                "aciklama": "Hiçbir işlem yapmaz, sadece zaman harcar."},
    }
    TUM_KOMUTLAR = {**KOMUTLAR, **KOMUTLAR2}

    # ---------------------------------------------------------------- Komut-Operand Eşleşme Tablosu (B)
    OPERAND_LIMITESI = {
        "MOV":    {"min": 2, "mak": 2, "tipler": ["reg", "imm", "mem"], "bellekten_bellege": False},
        "LEA":    {"min": 2, "mak": 2, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "PUSH":   {"min": 1, "mak": 1, "tipler": ["reg", "imm", "mem"], "bellekten_bellege": False},
        "POP":    {"min": 1, "mak": 1, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "ADD":    {"min": 2, "mak": 2, "tipler": ["reg", "imm", "mem"], "bellekten_bellege": False},
        "SUB":    {"min": 2, "mak": 2, "tipler": ["reg", "imm", "mem"], "bellekten_bellege": False},
        "IMUL":   {"min": 2, "mak": 2, "tipler": ["reg", "imm", "mem"], "bellekten_bellege": False},
        "IDIV":   {"min": 1, "mak": 1, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "AND":    {"min": 2, "mak": 2, "tipler": ["reg", "imm", "mem"], "bellekten_bellege": False},
        "OR":     {"min": 2, "mak": 2, "tipler": ["reg", "imm", "mem"], "bellekten_bellege": False},
        "XOR":    {"min": 2, "mak": 2, "tipler": ["reg", "imm", "mem"], "bellekten_bellege": False},
        "CMP":    {"min": 2, "mak": 2, "tipler": ["reg", "imm", "mem"], "bellekten_bellege": False},
        "TEST":   {"min": 2, "mak": 2, "tipler": ["reg", "imm", "mem"], "bellekten_bellege": False},
        "JMP":    {"min": 1, "mak": 1, "tipler": ["label"], "bellekten_bellege": False},
        "JE":     {"min": 1, "mak": 1, "tipler": ["label"], "bellekten_bellege": False},
        "JZ":     {"min": 1, "mak": 1, "tipler": ["label"], "bellekten_bellege": False},
        "JNE":    {"min": 1, "mak": 1, "tipler": ["label"], "bellekten_bellege": False},
        "JNZ":    {"min": 1, "mak": 1, "tipler": ["label"], "bellekten_bellege": False},
        "JG":     {"min": 1, "mak": 1, "tipler": ["label"], "bellekten_bellege": False},
        "JL":     {"min": 1, "mak": 1, "tipler": ["label"], "bellekten_bellege": False},
        "CALL":   {"min": 1, "mak": 1, "tipler": ["label"], "bellekten_bellege": False},
        "RET":    {"min": 0, "mak": 0, "tipler": [], "bellekten_bellege": False},
        "INC":    {"min": 1, "mak": 1, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "DEC":    {"min": 1, "mak": 1, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "NEG":    {"min": 1, "mak": 1, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "NOT":    {"min": 1, "mak": 1, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "SHL":    {"min": 2, "mak": 2, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "SHR":    {"min": 2, "mak": 2, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "ROL":    {"min": 2, "mak": 2, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "ROR":    {"min": 2, "mak": 2, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "XCHG":   {"min": 2, "mak": 2, "tipler": ["reg", "mem"], "bellekten_bellege": False},
        "INT":    {"min": 1, "mak": 1, "tipler": ["imm"], "bellekten_bellege": False},
        "SYSCALL":{"min": 0, "mak": 0, "tipler": [], "bellekten_bellege": False},
        "NOP":    {"min": 0, "mak": 0, "tipler": [], "bellekten_bellege": False},
    }


    DESENLER = {
        "if_else": {
            "aciklama": "C kodundaki 'if (x == y) return 1; else return 0;' yapısının karşılığıdır.",
            "ornek": """check_equality:
    push rbp
    mov rbp, rsp
    cmp rdi, rsi
    jne .not_equal
    mov rax, 1
    jmp .exit
.not_equal:
    mov rax, 0
.exit:
    mov rsp, rbp
    pop rbp
    ret""",
        },
        "loop_sum": {
            "aciklama": "Bir tamsayı dizisinin elemanlarını döngü ile toplama algoritması.",
            "ornek": """sum_array:
    xor rax, rax
    xor rcx, rcx
.loop_cond:
    cmp rcx, rsi
    jge .loop_end
    add rax, [rdi + rcx*8]
    inc rcx
    jmp .loop_cond
.loop_end:
    ret""",
        },
        "syscall_write": {
            "aciklama": "Linux x86-64 64-bit sistem çağrısı: ekran çıktısı (sys_write).",
            "ornek": """_start:
    mov rax, 1
    mov rdi, 1
    mov rsi, msg
    mov rdx, msg_len
    syscall""",
        },
        "syscall_exit": {
            "aciklama": "Linux x86-64 64-bit sistem çağrısı: program çıkışı (sys_exit).",
            "ornek": """    mov rax, 60
    xor rdi, rdi
    syscall""",
        },
        "function_prologue": {
            "aciklama": "Fonksiyon giriş bloğu: önceki frame pointer'ı yığına kaydırır ve yeni frame kurar.",
            "ornek": """    push rbp
    mov rbp, rsp""",
        },
        "function_epilogue": {
            "aciklama": "Fonksiyon çıkış bloğu: frame'i kaldırır ve çağrıyana döner.",
            "ornek": """    mov rsp, rbp
    pop rbp
    ret""",
        },
        "array_access": {
            "aciklama": "Dizi elemanına erişim: base + index * scale (64-bit için scale=8).",
            "ornek": """    mov rax, [rdi + rcx*8]""",
        },
        "zero_register": {
            "aciklama": "Bir register'ı sıfırlamak için kendi üzerine XOR uygulanır (en kısa yöntem).",
            "ornek": """    xor rax, rax""",
        },
        "stack_push_pop": {
            "aciklama": "Yığına değer gönderme ve geri alma desenleri.",
            "ornek": """    push rax
    pop rbx""",
        },
    }

    # ---------------------------------------------------------------- Başlatma
    def __init__(self, root=CORE_ROOT):
        self.root = Path(root)
        self.uzuv_dir = self.root / "uzuv"
        self.uzuv_dir.mkdir(exist_ok=True)

        self.beyn_path = self.uzuv_dir / "asm_beyn.json"
        self.log_path = self.uzuv_dir / "asm_log.jsonl"
        self.ders_path = self.uzuv_dir / "asm_dersler.jsonl"

        self.syntax_basari = defaultdict(int)
        self.syntax_hata = defaultdict(int)
        self.hata_dersleri = {}
        self.bilinen_programlar = {}
        self._ders_gorulen = set()
        self.istatistikler = {
            "toplam_sorgulama": 0,
            "toplam_deneme": 0,
            "basarili_deneme": 0,
            "basarisiz_deneme": 0,
            "olusturulma": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        self._yukle_beyn()
        self._yukle_dersler()
        self.log("baslat", versiyon=1, not_="x86-64 asm uzuv başlatıldı")

    def _yukle_dersler(self):
        if self.ders_path.exists():
            try:
                with open(self.ders_path, "r", encoding="utf-8") as f:
                    for satir in f:
                        satir = satir.strip()
                        if not satir:
                            continue
                        try:
                            kayit = json.loads(satir)
                        except ValueError:
                            continue
                        pattern = kayit.get("syntax_pattern")
                        hata = kayit.get("hata_mesaji")
                        if not (pattern and self._gecerli_mesaj(hata)):
                            continue
                        self._ders_gorulen.add((pattern, hata))
                        if kayit.get("kaynak") != "tahmin" or pattern not in self.hata_dersleri:
                            self.hata_dersleri[pattern] = hata
            except OSError as e:
                self.log("ders_yukle_hata", hata=str(e))
        # eski beyin dosyasından gelen çöp mesajları ayıkla
        self.hata_dersleri = {p: m for p, m in self.hata_dersleri.items()
                              if self._gecerli_mesaj(m)}

    def _yukle_beyn(self):
        if not self.beyn_path.exists():
            self._kaydet_beyn()
            return
        try:
            with open(self.beyn_path, "r", encoding="utf-8") as f:
                veri = json.load(f)
            self.istatistikler = veri.get("istatistikler", self.istatistikler)
            self.syntax_basari = defaultdict(
                int, {k: v for k, v in veri.get("syntax_basari", {}).items()}
            )
            self.syntax_hata = defaultdict(
                int, {k: v for k, v in veri.get("syntax_hata", {}).items()}
            )
            self.hata_dersleri = veri.get("hata_dersleri", {})
            self.bilinen_programlar = veri.get("bilinen_programlar", {})
        except (ValueError, OSError) as e:
            self.log("beyn_yukle_hata", hata=str(e))

    def _kaydet_beyn(self):
        veri = {
            "surum": 1,
            "son_guncelleme": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "istatistikler": self.istatistikler,
            "syntax_basari": dict(self.syntax_basari),
            "syntax_hata": dict(self.syntax_hata),
            "hata_dersleri": self.hata_dersleri,
            "bilinen_programlar": self.bilinen_programlar,
        }
        # Ensure directory exists
        self.beyn_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.beyn_path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(str(tmp), str(self.beyn_path))
        except OSError:
            # Fallback: directly write to the brain file if tmp approach fails
            try:
                self.beyn_path.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass

    def program_kaydet(self, kod, baglam, deneme=1, kaynak="asm_ogren"):
        """Çözülen bir programı beynin 'bilinen_programlar' deposuna kaydeder.

        Aynı kod aynı bağlamda daha önce kaydedilmişse deneme sayacı artırılır.
        """
        if not hasattr(self, "bilinen_programlar"):
            self.bilinen_programlar = {}
        ctx = str(baglam)
        liste = self.bilinen_programlar.setdefault(ctx, [])
        for giris in liste:
            if giris.get("kod") == kod:
                giris["deneme"] = giris.get("deneme", 0) + deneme
                giris["son_guncelleme"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                self._kaydet_beyn()
                return giris
        giris = {
            "kod": kod,
            "deneme": deneme,
            "kaynak": kaynak,
            "olusturma": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "son_guncelleme": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        liste.append(giris)
        self._kaydet_beyn()
        self.log("program_kaydet", kod=kod, baglam=ctx, deneme=deneme, kaynak=kaynak)
        return giris

    def program_listele(self, baglam=None):
        """Belirli bir bağlamdaki (b Hepsini) bilinen programları döndürür."""
        if not hasattr(self, "bilinen_programlar"):
            return []
        if baglam is None:
            sonuc = []
            for ctx, liste in self.bilinen_programlar.items():
                sonuc.extend(liste)
            return sonuc
        return self.bilinen_programlar.get(str(baglam), [])

    def guncelle_der_veritabani(self):
        """asm_dersler.jsonl'den hata_dersleri'yi güncelle.
        
        Öğrenme günlüğündeki yeni deneme kayıtlarından çıkarılan hata mesajları
        beynin hata_dersleri dict'ine eklenir. Bu, uzuvun zamanla öğrenmesi
        ve hataları zamenleştirmesi sağlar.
        """
        if not self.ders_path.exists():
            self.log("güncelle_yok", not_="ders dosyası yok")
            return
        
        güncellenen = 0
        try:
            with open(self.ders_path, "r", encoding="utf-8") as f:
                for satir in f:
                    satir = satir.strip()
                    if not satir:
                        continue
                    try:
                        kayit = json.loads(satir)
                        pattern = kayit.get("syntax_pattern")
                        hata = kayit.get("hata_mesaji")
                        if pattern and self._gecerli_mesaj(hata) and pattern not in self.hata_dersleri:
                            self.hata_dersleri[pattern] = hata
                            güncellenen += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError as e:
            self.log("ders_yükle_hata", hata=str(e))
        
        if güncellenen > 0:
            self._kaydet_beyn()
            self.log("der_güncellendi", güncellenen=güncellenen)
        else:
            self.log("güncelle_yok", not_="yeni hata kaydı bulmadı")
    # ---------------------------------------------------------------- Yardımcılar
    @staticmethod
    def _gecerli_mesaj(m):
        """Log hatasından gelen çöp mesajları ('hata', 'rax True') ders sayma."""
        if not isinstance(m, str):
            return False
        m = m.strip()
        if len(m) < 10:
            return False
        return not ({"True", "False", "None"} & set(m.split()))

    @staticmethod
    def _komutlar(kod):
        """Koddaki komut adlarını sırayla çıkarır (etiket, yorum ve direktifleri atlar)."""
        sonuc = []
        for satir in kod.splitlines():
            satir = re.split(r"#|;|//", satir)[0].strip()
            satir = re.sub(r"^[\w.$]+:\s*", "", satir)
            if not satir or satir.startswith("."):
                continue
            sonuc.append(satir.split()[0].upper())
        return sonuc

    def _deneme_say(self, basarili):
        st = self.istatistikler
        st["toplam_deneme"] = st.get("toplam_deneme", 0) + 1
        anahtar = "basarili_deneme" if basarili else "basarisiz_deneme"
        st[anahtar] = st.get(anahtar, 0) + 1

    def _basari_kaydet(self, kod):
        for k in set(self._komutlar(kod)):
            self.syntax_basari[k] += 1

    # ---------------------------------------------------------------- Öğrenme
    def ogren_hata(self, pattern, mesaj, kaynak="manuel", kaydet=True):
        """Bir hatayı sayar ve (çöp değilse, yeniyse) ders dosyasına yazar."""
        pattern = str(pattern).upper()
        self.syntax_hata[pattern] += 1
        yeni_ders = False
        if self._gecerli_mesaj(mesaj):
            if kaynak in ("assembler", "manuel") or pattern not in self.hata_dersleri:
                self.hata_dersleri[pattern] = mesaj
            anahtar = (pattern, mesaj)
            if anahtar not in self._ders_gorulen:
                self._ders_gorulen.add(anahtar)
                kayit = {"t": time.time(), "syntax_pattern": pattern,
                         "hata_mesaji": mesaj, "kaynak": kaynak}
                with open(self.ders_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
                yeni_ders = True
        if kaydet:
            self._kaydet_beyn()
        self.log("ogren_hata", pattern=pattern, mesaj=mesaj, kaynak=kaynak, yeni_ders=yeni_ders)
        return yeni_ders

    def _sonuc_isle(self, kod, sonuc):
        """Harness sonucunu sayaçlara ve derslere çevirir."""
        if sonuc["tamam"]:
            self._deneme_say(True)
            self._basari_kaydet(kod)
        else:
            self._deneme_say(False)
            m = re.search(r"`(\w+)'", sonuc["hata"] or "")
            ilk = self._komutlar(kod)
            pattern = m.group(1) if m else (ilk[0] if ilk else "?")
            if sonuc["asama"] == "derleme":
                self.ogren_hata(pattern, sonuc["hata"], kaynak="assembler", kaydet=False)
            else:
                self.ogren_hata(pattern, f"çalışma hatası: {sonuc['hata']}",
                                kaynak="calisma", kaydet=False)
        self._kaydet_beyn()
        self.log("deneme", kod=kod, tamam=sonuc["tamam"], asama=sonuc["asama"], hata=sonuc["hata"])

    def dene_kod(self, kod, basarili=True, hata=None):
        """Elle sonuç bildirme: kodu çalıştırmadan, başarılı/başarısız olarak kaydeder."""
        if basarili:
            self._deneme_say(True)
            self._basari_kaydet(kod)
            self._kaydet_beyn()
            self.log("deneme_elle", kod=kod, tamam=True)
        else:
            self._deneme_say(False)
            ilk = self._komutlar(kod)
            self.ogren_hata(ilk[0] if ilk else "?", hata or "belirtilmemiş hata", kaynak="manuel")

    def _calistir(
        self, kod, baslangic=None, baslangic_bellek=None, bellek_adresleri=None
    ):
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from asm_dogrula import dene
        return dene(
            kod,
            baslangic or {},
            baslangic_bellek=baslangic_bellek,
            bellek_adresleri=bellek_adresleri,
        )

    def test_kod(self, kod, baslangic=None):
        """Kodu gerçekten derler ve çalıştırır; sonucu öğrenmeye işler.

        Dönen: {'tamam', 'asama', 'hata', 'yazmac', 'bayrak'}
        """
        sonuc = self._calistir(kod, baslangic)
        self._sonuc_isle(kod, sonuc)
        return sonuc

    def tahmin_dene(
        self, kod, tahmin, baslangic=None, baslangic_bellek=None
    ):
        """Önce tahmin, sonra gerçek: tahmin = {'rax': 8, 'ZF': 0, ...}.

        Tahmin ile makine arasındaki fark 'sürpriz'dir (0.0 = tam isabet) ve
        tutmayan her tahmin o komut için bir ders olarak kaydedilir.
        """
        norm = {(k.upper() if k.upper() in ("CF", "PF", "AF", "ZF", "SF", "OF") else k.lower()): v
                for k, v in tahmin.items()}
        bellek_adresleri = (
            tahmin.get("bellek", {}).keys()
            if isinstance(tahmin.get("bellek"), dict) else None
        )
        sonuc = self._calistir(
            kod, baslangic, baslangic_bellek, bellek_adresleri
        )
        st = self.istatistikler
        if not sonuc["tamam"]:
            self._sonuc_isle(kod, sonuc)
            return {"sonuc": sonuc, "fark": {}, "dogru": False, "surpriz": 1.0}

        from asm_dogrula import karsilastir
        fark = karsilastir(norm, sonuc)
        surpriz = len(fark) / len(norm) if norm else 0.0
        st["tahmin_toplam"] = st.get("tahmin_toplam", 0) + 1
        self._deneme_say(True)
        ilk = self._komutlar(kod)
        pattern = ilk[0] if ilk else "?"
        if fark:
            mesaj = "tahmin tutmadı: " + ", ".join(
                f"{k} beklenen={b} gerçek={g}" for k, (b, g) in fark.items())
            self.ogren_hata(pattern, mesaj, kaynak="tahmin", kaydet=False)
        else:
            st["tahmin_dogru"] = st.get("tahmin_dogru", 0) + 1
            self._basari_kaydet(kod)
        self._kaydet_beyn()
        self.log("tahmin", kod=kod, surpriz=surpriz, fark={k: list(v) for k, v in fark.items()})
        return {"sonuc": sonuc, "fark": fark, "dogru": not fark, "surpriz": surpriz}

    # ---------------------------------------------------------------- Bilgi sorgusu
    def sorgula(self, ad):
        """Yazmaç, alt yazmaç, komut ya da desen bilgisini döndürür; yoksa None."""
        self.istatistikler["toplam_sorgulama"] = self.istatistikler.get("toplam_sorgulama", 0) + 1
        a = str(ad).strip().upper()
        if a in self.REGISTERLER:
            return {"tur": "yazmac", "ad": a, **self.REGISTERLER[a]}
        for ust, b in self.REGISTERLER.items():
            if a in (b["32"], b["16"], b["8"]):
                return {"tur": "alt_yazmac", "ad": a, "ust": ust, **b}
        if re.fullmatch(r"R(8|9|1[0-5])[DWB]?", a):
            return {"tur": "yazmac", "ad": a, **self.EK_YAZMACLAR["R8-R15"]}
        if a in self.TUM_KOMUTLAR:
            return {"tur": "komut", "ad": a, **self.TUM_KOMUTLAR[a],
                    "operand_limiti": self.OPERAND_LIMITESI.get(a),
                    "bilinen_hata": self.hata_dersleri.get(a)}
        if a.lower() in self.DESENLER:
            return {"tur": "desen", "ad": a.lower(), **self.DESENLER[a.lower()]}
        return None

    # ---------------------------------------------------------------- Analiz ve plan (stdlib)
    def numpy_istatistik_analizi(self):
        """(Ad eski çağrılar için aynı; artık numpy gerektirmez.)"""
        st = self.istatistikler
        toplam = st.get("toplam_deneme", 0)
        oran = st.get("basarili_deneme", 0) / toplam if toplam else 0.0
        analiz = {"success_rate": float(oran), "error_distribution": {},
                  "most_error_prone": None, "performance_score": round(oran, 3),
                  "recommendations": []}
        toplam_hata = sum(self.syntax_hata.values())
        if toplam_hata:
            for p, c in self.syntax_hata.items():
                analiz["error_distribution"][p] = round(c / toplam_hata * 100, 1)
            analiz["most_error_prone"] = max(self.syntax_hata, key=self.syntax_hata.get)
            analiz["success_by_pattern"] = {p: int(self.syntax_basari.get(p, 0))
                                            for p in self.syntax_hata}
        if oran < 0.5:
            analiz["recommendations"].append("Daha fazla pratik yapın - başarı oranı düşük")
            if self.syntax_hata.get("MOV", 0) > 0:
                analiz["recommendations"].append("MOV komutundan daha fazla pratik yapın")
        elif oran < 0.7:
            analiz["recommendations"].append("Orta seviyede ilerleme - bazı alanlar dikkat istiyor")
        else:
            analiz["recommendations"].append("Temel assembly oturmuş, ileri konulara geçilebilir")
        gorulmeyen = [k for k in self.TUM_KOMUTLAR
                      if k not in self.syntax_basari and k not in self.syntax_hata]
        if gorulmeyen:
            analiz["available_to_learn"] = gorulmeyen[:10]
        return analiz

    def _ustalik(self, p):
        """(başarı, hata, hata_oranı) — hiç görülmediyse oran None."""
        b, h = self.syntax_basari.get(p, 0), self.syntax_hata.get(p, 0)
        return b, h, (h / (b + h) if b + h else None)

    def ders_plan_olustur(self, hedef_pattern=None):
        """Sıradaki konuları seçer: hata oranı yüksek olan önce, görülmemişler sonra,
        ustalaşılanlar (>=3 başarı ve hata oranı <=%20) en sona."""
        analiz = self.numpy_istatistik_analizi()
        tum = list(self.TUM_KOMUTLAR) + list(self.REGISTERLER)
        skorlar = {}
        usta = 0
        for p in tum:
            b, h, oran = self._ustalik(p)
            if oran is None:
                skorlar[p] = 0.5
            elif b >= 3 and oran <= 0.2:
                skorlar[p] = 0.0
                usta += 1
            else:
                skorlar[p] = max(oran, 0.05)
        sirali = sorted((p for p in tum if skorlar[p] > 0), key=lambda p: skorlar[p], reverse=True)

        oran = analiz["success_rate"]
        plan = {
            "current_level": "beginner" if oran < 0.5 else "intermediate" if oran < 0.8 else "advanced",
            "success_rate": float(oran),
            "total_patterns_learned": usta,
            "patterns_to_learn": len(sirali),
            "most_needed_focus": analiz.get("most_error_prone") or "Basics",
            "recommended_next": sirali[:5],
            "numpy_analysis": {
                "performance_score": analiz["performance_score"],
                "error_distribution": analiz["error_distribution"],
                "recommendations": analiz["recommendations"],
            },
        }
        if hedef_pattern and str(hedef_pattern).upper() in tum:
            plan["focus_pattern"] = str(hedef_pattern).upper()
            plan["recommended_next"] = [plan["focus_pattern"]]
        return plan

    def rapor(self):
        """Durum özeti: yazdırır ve sözlük olarak döndürür."""
        st = self.istatistikler
        analiz = self.numpy_istatistik_analizi()
        plan = self.ders_plan_olustur()
        satirlar = [
            "=== ASM Uzuv Raporu ===",
            f"Sorgu: {st.get('toplam_sorgulama', 0)} | Deneme: {st.get('toplam_deneme', 0)} "
            f"(başarılı {st.get('basarili_deneme', 0)}, başarısız {st.get('basarisiz_deneme', 0)})",
        ]
        if st.get("tahmin_toplam"):
            satirlar.append(f"Tahmin isabeti: {st.get('tahmin_dogru', 0)}/{st['tahmin_toplam']}")
        satirlar.append(f"Seviye: {plan['current_level']} | Ustalaşılan: {plan['total_patterns_learned']}")
        if analiz["most_error_prone"]:
            satirlar.append(f"En çok hata: {analiz['most_error_prone']} "
                            f"-> {self.hata_dersleri.get(analiz['most_error_prone'], '-')}")
        satirlar.append("Sıradaki: " + ", ".join(plan["recommended_next"]))
        metin = "\n".join(satirlar)
        print(metin)
        return {"istatistik": dict(st), "analiz": analiz, "plan": plan, "metin": metin}

    # ---------------------------------------------------------------- Alıştırmalar (makineyle doğrulanabilir)
    _GENEL = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11"]
    _BAYRAKLI = ("ADD", "SUB", "CMP", "TEST", "AND", "OR", "XOR", "INC", "DEC", "NEG")

    def assembled_code_exercise(self, count=5, difficulty="beginner", seed=None):
        """Doğrulanabilir alıştırmalar üretir. Her biri başlangıç değerleri, tek komutluk kod
        ve 'sorulan' alanları (tahmin edilecek yazmaç/bayraklar) içerir.
        Cevabı alistirma_degerlendir(ex, tahmin) makineyle kontrol eder."""
        rng = random.Random(seed)
        odak = ["MOV", "ADD", "SUB", "XOR", "INC", "DEC"]
        if difficulty in ("intermediate", "advanced"):
            odak += ["AND", "OR", "NEG", "NOT", "SHL", "SHR", "CMP", "TEST", "IMUL"]
        if difficulty == "advanced":
            odak += ["LEA", "XCHG", "ROL", "ROR"]

        sonuc = []
        for i in range(count):
            cmd = rng.choice(odak)
            dst = rng.choice(self._GENEL)
            src = rng.choice([r for r in self._GENEL if r != dst])
            bas = {dst: rng.randint(-8, 20), src: rng.randint(-8, 20)}
            imm = rng.randint(-8, 20)

            if cmd in ("INC", "DEC", "NEG", "NOT"):
                kod = f"{cmd.lower()} {dst}"
            elif cmd in ("SHL", "SHR", "ROL", "ROR"):
                kod = f"{cmd.lower()} {dst}, {rng.randint(1, 7)}"
            elif cmd == "LEA":
                kod = rng.choice([f"lea {dst}, [{src} + {abs(imm)}]",
                                  f"lea {dst}, [{src} + {src}*4]"])
            elif cmd == "XCHG":
                kod = f"xchg {dst}, {src}"
            elif cmd == "XOR" and rng.random() < 0.3:
                kod = f"xor {dst}, {dst}"
            elif rng.random() < 0.4:
                kod = f"{cmd.lower()} {dst}, {imm}"
            else:
                kod = f"{cmd.lower()} {dst}, {src}"

            sorulan = [] if cmd in ("CMP", "TEST") else [dst]
            if cmd == "XCHG":
                sorulan.append(kod.split(",")[1].strip())
            if cmd in self._BAYRAKLI:
                sorulan += ["ZF", "SF", "CF", "OF"]

            durum = ", ".join(f"{k}={v}" for k, v in bas.items())
            sonuc.append({
                "id": i + 1, "difficulty": difficulty, "code": kod, "pattern": cmd,
                "baslangic": bas, "sorulan": sorulan,
                "soru": f"{durum} iken `{kod}` sonrası {', '.join(sorulan)} ne olur?",
                "hint": self._generate_hint(cmd, difficulty),
                "solution": self._get_solution(cmd),
                "timestamp": time.time(),
            })
        return sonuc

    def alistirma_degerlendir(self, ex, tahmin):
        """Alıştırma cevabını makineyle doğrular ve sürprizi öğrenmeye işler."""
        return self.tahmin_dene(ex["code"], tahmin, ex["baslangic"])

    def _generate_hint(self, cmd, difficulty):
        hints = {
            "MOV": "Kaynağı hedefe kopyalar; bellekten belleğe doğrudan olmaz, bayrakları etkilemez",
            "ADD": "dest = dest + src; ZF/SF/CF/OF güncellenir (CF işaretsiz taşma, OF işaretli taşma)",
            "SUB": "dest = dest - src; CF 'ödünç alma' (işaretsiz dest < src), ZF eşitlikte 1",
            "XOR": "Aynı yazmaçla XOR sonucu 0 yapar (ZF=1); CF ve OF her zaman 0",
            "AND": "Bit bit VE: yalnızca iki bit de 1 ise sonuç 1; CF=OF=0",
            "OR": "Bit bit VEYA: bitlerden biri 1 ise sonuç 1; CF=OF=0, ZF/SF güncellenir",
            "INC": "1 artırır; CF değişmez, ZF/SF/OF güncellenir",
            "DEC": "1 azaltır; CF değişmez, ZF/SF/OF güncellenir",
            "NEG": "İkiye tümleyen: 0 - dest; dest 0 değilse CF=1",
            "NOT": "Bitleri ters çevirir; hiçbir bayrağı etkilemez",
            "CMP": "op1 - op2 hesaplar, sonucu atar; sadece bayraklar değişir",
            "TEST": "op1 AND op2 hesaplar, sonucu atar; CF=OF=0, ZF/SF güncellenir",
            "SHL": "Sola kaydırır; her adım değeri 2 ile çarpmak gibidir",
            "SHR": "Mantıksal sağa kaydırma; her adım 2'ye bölmek gibidir (işaretsiz)",
            "ROL": "Taşan bit karşı uçtan geri girer; bit kaybı olmaz",
            "ROR": "Taşan bit karşı uçtan geri girer; bit kaybı olmaz",
            "IMUL": "İşaretli çarpma: dest = dest * src",
            "LEA": "Adresi hesaplar, belleği okumaz; bayrakları etkilemez",
            "XCHG": "İki operandı yer değiştirir; bayrakları etkilemez",
        }
        return hints.get(cmd, "Komutun operandlarını ve bayrak etkisini dikkatle oku")

    def _get_solution(self, cmd):
        solutions = {
            "MOV": "Hedefe kopyalanır, eski değer kaybolur; bayraklar aynı kalır",
            "ADD": "ZF sonuç sıfırsa, SF sonuç negatifse, CF işaretsiz taşmada, OF işaretli taşmada 1 olur",
            "SUB": "CF işaretsiz ödünç almada, ZF eşitlikte, OF işaretli taşmada 1 olur",
            "XOR": "Aynı yazmaçla XOR yazmacı sıfırlar; CF ve OF 0",
            "AND": "Maskeleme için kullanılır; CF=OF=0, ZF/SF sonuca göre",
            "OR": "Bit açmak için kullanılır; CF=OF=0, ZF/SF sonuca göre",
            "INC": "CF dokunulmaz; diğer bayraklar sonuca göre",
            "DEC": "CF dokunulmaz; diğer bayraklar sonuca göre",
            "NEG": "0 - dest; dest sıfırsa CF=0, değilse CF=1",
            "NOT": "Bitleri tersler, bayrak değişmez",
            "CMP": "Çıkarma yapılır ama sonuç saklanmaz; yalnızca bayraklar",
            "TEST": "AND yapılır ama sonuç saklanmaz; yalnızca bayraklar",
        }
        return solutions.get(cmd, "Cevap makineyle doğrulanır (alistirma_degerlendir)")

    def log(self, kind, **data):
        """Kayıt yapar.
        
        Args:
            kind: Kayıt türü
            **data: Ek veri
        """
        import time
        entry = {"t": time.time(), "kind": kind}
        entry.update(data)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
