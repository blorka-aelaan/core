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
                "aciklama": "Koşulsuz olarak belirtilen adrese/etikete atlar. RIP değerini günceller."},
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
                "aciklama": "dest değerini count kadar sola kaydırır."},
        "SHR": {"operanlar": "dest, count", "bayraklar": "ZF, SF, CF, OF",
                "aciklama": "dest değerini count kadar sağa kaydırır (mantıksal)."},
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
        if not self.ders_path.exists():
            return
        try:
            with open(self.ders_path, "r", encoding="utf-8") as f:
                for satir in f:
                    satir = satir.strip()
                    if not satir:
                        continue
                    kayit = json.loads(satir)
                    pattern = kayit.get("syntax_pattern")
                    hata = kayit.get("hata_mesaji")
                    if pattern and hata:
                        self.hata_dersleri[pattern] = hata
        except (ValueError, OSError) as e:
            self.log("ders_yukle_hata", hata=str(e))

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
        }
        tmp = self.beyn_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(self.beyn_path))

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
                        if pattern and hata and pattern not in self.hata_dersleri:
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
    def numpy_istatistik_analizi(self):
        import numpy as np
        stats = dict(self.istatistikler)
        success_rate = stats['basarili_deneme'] / stats['toplam_deneme'] if stats['toplam_deneme'] > 0 else 0
        analysis = {
            'success_rate': float(success_rate),
            'error_distribution': {},
            'most_error_prone': None,
            'performance_score': 0.0,
            'recommendations': []
        }
        if self.syntax_hata:
            error_patterns = list(self.syntax_hata.keys())
            error_counts = np.array([self.syntax_hata.get(p, 0) for p in error_patterns])
            error_pct = np.round(error_counts / error_counts.sum() * 100, 1)
            for i, pattern in enumerate(error_patterns):
                analysis['error_distribution'][pattern] = float(error_pct[i])
            if len(error_counts) > 0:
                most_error_idx = np.argmax(error_counts)
                analysis['most_error_prone'] = error_patterns[most_error_idx]
            success_counts = np.array([self.syntax_basari.get(p, 0) for p in error_patterns])
            analysis['success_by_pattern'] = {p: int(c) for p, c in zip(error_patterns, success_counts)}
        analysis['performance_score'] = float(np.round(success_rate, 3))
        if success_rate < 0.5:
            analysis['recommendations'].append("Daha fazla pratiği yapin - basari orani dusuk")
            if 'MOV' in self.hata_dersleri:
                analysis['recommendations'].append("MOV komutundan daha fazla pratiği yapin")
        elif success_rate < 0.7:
            analysis['recommendations'].append("Orta seviyede progress - some areas need attention")
        else:
            analysis['recommendations'].append("Harika! Temel asmanya hakimsiniz, ileri seviye konulara gecin")
        all_known_patterns = set(self.KOMUTLAR.keys()) | set(self.REGISTERLER.keys())
        missing = all_known_patterns - set(self.hata_dersleri.keys()) - set(self.syntax_basari.keys())
        if missing:
            analysis['available_to_learn'] = list(missing)[:10]
        return analysis

    def ders_plan_olustur(self, hedef_pattern=None):
        import numpy as np

        analysis = self.numpy_istatistik_analizi()

        learned_patterns = set(self.hata_dersleri.keys()) | set(self.syntax_basari.keys())
        all_commands = list(self.KOMUTLAR.keys()) + list(self.REGISTERLER.keys())
        unlearned = [c for c in all_commands if c not in learned_patterns]

        error_based_priority = []
        for pattern in unlearned:
            error_penalty = self.hata_dersleri.get(pattern, 0)
            error_based_priority.append((pattern, error_penalty))

        error_based_priority.sort(key=lambda x: x[1], reverse=True)

        penalties = np.array([p[1] for p in error_based_priority])
        if len(penalties) > 0:
            priority_weights = penalties / penalties.sum() if penalties.sum() > 0 else np.ones(len(penalties)) / len(penalties)
        else:
            priority_weights = np.ones(len(error_based_priority)) / len(error_based_priority)

        plan = {
            'current_level': 'beginner' if analysis['success_rate'] < 0.5 else 'intermediate' if analysis['success_rate'] < 0.8 else 'advanced',
            'success_rate': float(analysis['success_rate']),
            'total_patterns_learned': len(learned_patterns),
            'patterns_to_learn': len(unlearned),
            'most_needed_focus': analysis.get('most_error_prone', 'Basics'),
            'recommended_next': [],
            'numpy_analysis': {
                'performance_score': analysis['performance_score'],
                'error_distribution': analysis['error_distribution'],
                'recommendations': analysis['recommendations']
            }
        }

        top_priority = [p[0] for p in error_based_priority[:5] if p[1] > 0]
        if top_priority:
            plan['recommended_next'] = top_priority

        if hedef_pattern and hedef_pattern in all_commands:
            plan['focus_pattern'] = hedef_pattern
            plan['recommended_next'] = [hedef_pattern]

        if not plan['recommended_next'] and unlearned:
            weights = np.ones(len(unlearned)) / len(unlearned)
            if analysis['most_error_prone'] and analysis['most_error_prone'] in unlearned:
                weights = np.array([1 if p == analysis['most_error_prone'] else 0.5 for p in unlearned])
                weights = weights / weights.sum()
            choice = np.random.choice(unlearned, size=min(3, len(unlearned)), p=weights, replace=False)
            plan['recommended_next'] = list(choice)

        return plan

    def assembled_code_exercise(self, count=5, difficulty='beginner'):
        import numpy as np
        import time

        commands = list(self.KOMUTLAR.keys())
        registers = list(self.REGISTERLER.keys())

        if difficulty == 'beginner':
            focus = ['MOV', 'ADD', 'XOR']
            operand_types = ['register', 'immediate']
        elif difficulty == 'intermediate':
            focus = ['MOV', 'ADD', 'SUB', 'XOR', 'AND', 'OR']
            operand_types = ['register', 'immediate', 'memory']
        else:
            focus = list(commands)
            operand_types = ['register', 'immediate', 'memory', 'base_plus_offset']

        exercises = []
        rng = np.random.RandomState(42)

        for i in range(count):
            cmd = rng.choice(focus)

            if cmd == 'MOV':
                dst = rng.choice(registers)
                src_type = rng.choice(operand_types)
                if src_type == 'register':
                    src = rng.choice([r for r in registers if r != dst])
                    code = f"mov {dst}, {src}"
                else:
                    val = rng.randint(-128, 127)
                    code = f"mov {dst}, {val}"

            elif cmd == 'ADD':
                dst = rng.choice(registers)
                src = rng.choice([r for r in registers if r != dst])
                code = f"add {dst}, {src}"

            elif cmd == 'XOR':
                dst = rng.choice(registers)
                src = rng.choice([r for r in registers if r != dst])
                code = f"xor {dst}, {src}"

            elif cmd == 'SUB':
                dst = rng.choice(registers)
                src = rng.choice([r for r in registers if r != dst])
                code = f"sub {dst}, {src}"

            elif cmd == 'AND':
                dst = rng.choice(registers)
                src = rng.choice([r for r in registers if r != dst])
                code = f"and {dst}, {src}"

            elif cmd == 'OR':
                dst = rng.choice(registers)
                src = rng.choice([r for r in registers if r != dst])
                code = f"or {dst}, {src}"

            else:
                code = f"{cmd} rdx, rax"

            exercise = {
                'id': i + 1,
                'difficulty': difficulty,
                'code': code,
                'pattern': cmd,
                'hint': self._generate_hint(cmd, difficulty),
                'solution': self._get_solution(cmd),
                'timestamp': time.time()
            }
            exercises.append(exercise)

        return exercises

    def _generate_hint(self, cmd, difficulty):
        hints = {
            "MOV": "Kaynakı hedefe kopyala - Bellek transferi yapılamaz, register kullan",
            "ADD": "Topla - Sonuç hedef registera kaydedilir, flaglar güncellenir",
            "XOR": "XOR ile sifirla - Aynı registerla XOR sonucu sifir olur",
            "SUB": "Cikar - Result = dst - src, CF/ZF bayraklari etkilenir",
            "AND": "Bitwise AND - Her iki operand icin 1 bit ise result 1",
            "OR": "Bitwise OR - Her iki operand icin 1 bit ise result 1"
        }
        return hints.get(cmd, "Dikkatli olarak okutun")

    def _get_solution(self, cmd):
        solutions = {
            "MOV": "Register'a veri kopyalanir, eski deger kaybolur",
            "ADD": "ZF (Sifir), SF (Negatif), CF (Overflow) bayraklari guncellenir",
            "XOR": "Rax/Register sifirlanir, aynı registerla XOR 0 verir",
            "SUB": "CF ve ZF bayraklari test edilir, borrowing/borrow olur",
            "AND": "Bitwise operasyonu, maskeler icin kullanilir",
            "OR": "Bitwise OR operasyonu, flag'lar etkilenmez'"
        }
        return solutions.get(cmd, "Cozum belirtilmadi")

