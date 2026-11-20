"""CORE body — beden: duyular, kaslar ve konsol organı.

İlke: okumada tam yetki, müdahalede beyaz liste + kuota.
Konsol, izinli komut sözlüğü kurulu bir "kas"tır; çıktısı bir duydur.
"""
import json
import os
import random
import re
import subprocess
import time
from pathlib import Path


class Body:
    COSTS = {"wander": 1, "eat": 1, "console": 2, "sense_self": 1,
             "nest": 3, "rest": 0, "go": 2, "katalogla": 3,
             "konum": 2, "nedir": 2, "atolye": 1,
             "explore": 2, "read": 1,
             "write": 2, "delete": 2, "mkdir": 2, "rmdir": 2,
             "copy": 2, "move": 2, "chmod": 2, "chown": 2,
             "help": 1,
             # Yeni duyular (Aşama 3): düşük maliyetli, salt-okunur algı
             "sense_power": 1, "sense_sensors": 1, "sense_journal": 1,
             "sense_usb": 1, "sense_docker": 1}

    def __init__(self, cfg, root, journal):
        self.cfg = cfg
        self.root = Path(root)
        self.world = (self.root / cfg["stage"]["world_dir"]).resolve()
        self.world.mkdir(parents=True, exist_ok=True)
        self.journal = journal
        self.allowed = set(cfg["console"]["allowed"])
        self.quota = cfg["quota"]
        self.wcfg = cfg.get("world", {})
        self.seen = set()
        self.last_action = "-"
        self.location = ""          # son ziyaret edilen oda
        self.cmd_seen = set()       # kurulan komutlar (merak kanıtı)
        self.food_cache = []        # keşfedilen yemek yolları
        self.ticks = 0
        self.last_nest = -10 ** 9
        self.seeds = {}             # .bite tohumları (tükenince yeniden doğar)
        self.valve = False          # Perde 2: yaşam valfi (bolluk)
        self._energy_hist = []      # olgunluk ölçümü (son tik enerjileri)
        self.last_food_loc = "-"    # Perde 3: son yemek odası (tahmin uyaranı)
        # Kutu: dünya dışı hazine sandığı (kurallar.json'dan gelir)
        self.kutu_dir_name = cfg.get("kutu_dir")
        self.kutu = (self.root / self.kutu_dir_name
                     if self.kutu_dir_name else None)
        self.sonek = cfg.get("kutu_sonek", "")
        self._kutu_list = None       # lazy listeleme (5000 dosyayı her seferinde tarama)
        self.gorev_dir = None        # misyon: "şu klasörü ara" odağı
        # Gerçek dosya sistemi odaları (dünya dışı, salt-okunur keşif):
        self.real_rooms = cfg.get("stage", {}).get("real_rooms", {})
        self._seed_scan()

    def _seed_scan(self):
        """Tohumları yükle: dünyadaki .bite'lar + kalıcı manifest (.seeds.json).

        Yemek süreç dışındayken de tükenmiş olsa geri dönebilir —
        manifest olmazsa tohumlar unutulurdu.
        """
        sf = self.world / ".seeds.json"
        if sf.exists():
            try:
                self.seeds.update(
                    json.loads(sf.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                pass
        files, _ = self.scan()
        changed = False
        for rel in files:
            if rel.endswith(".bite") and rel not in self.seeds:
                try:
                    self.seeds[rel] = (self.world / rel).read_text(
                        encoding="utf-8")
                    changed = True
                except OSError:
                    pass
        if changed or not sf.exists():
            self._save_seeds()

    def _save_seeds(self):
        try:
            (self.world / ".seeds.json").write_text(
                json.dumps(self.seeds, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            pass

    def tick(self, energy=None):
        """Büyüme döngüsü: tükenen yemekler tohumdan yeniden doğar
        + yaşam valfi (olgunluk ölçülürse dünya cömertleşir).

        ACİL DURUM: dünyada hiç yemek yoksa (ve tohum varsa) bekleme
        yok — ilk tikte doğar. Çorak dünya, çorak doğum ölüm demektir.
        """
        self.ticks += 1
        if energy is not None:
            self._energy_hist.append(energy)
            self._valve_check()
        self._maybe_move_food()
        missing = [r for r in self.seeds
                   if not (self.world / r).exists()]
        if not missing:
            return
        files, _ = self.scan()
        emergency = not any(f.endswith(".bite") for f in files)
        every = self._regrow_every()
        if not emergency and (not every or self.ticks % every):
            return
        random.shuffle(missing)
        for pick in missing[:self._regrow_batch()]:
            try:
                dest = self.world / pick
                # oda yoksa aç: tohum eski bir odanın çocuğuyken
                # klasör silinmiş olabilir (FileNotFoundError → sessiz ölüm)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(self.seeds[pick], encoding="utf-8")
                self.journal.log("regrow", path=pick,
                                 valve=self.valve, acil=emergency)
            except OSError:
                self.journal.log("regrow_fail", path=pick)

    # ---------- Perde 2: yaşam valfi ----------

    def _valve_check(self):
        v = self.wcfg
        window = max(1, int(v.get("valve_window", 50)))
        hist = self._energy_hist
        if self.valve:
            if len(hist) >= window:
                avg = sum(hist[-window:]) / window
                if avg < float(v.get("valve_close_avg", 40)):
                    self.valve = False
                    self.journal.log("valve_close", avg=round(avg, 1),
                                     ticks=self.ticks)
        else:
            need = int(v.get("valve_open_ticks", 100))
            if len(hist) >= need:
                w = hist[-window:]
                avg = sum(w) / len(w)
                if avg >= float(v.get("valve_open_avg", 70)):
                    self.valve = True
                    self.journal.log("valve_open", avg=round(avg, 1),
                                     ticks=self.ticks)

    def _regrow_every(self):
        if self.valve:
            return int(self.wcfg.get("valve_regrow_ticks", 10))
        return int(self.wcfg.get("regrow_ticks", 40))

    def _regrow_batch(self):
        if self.valve:
            return int(self.wcfg.get("valve_regrow_batch", 8))
        return int(self.wcfg.get("regrow_per_cycle", 3))

    # ---------- Perde 3: hareketli yemek & niyetli hareket ----------

    def _resolve_target(self, room):
        """Oda adını gerçek dosya sistemi yoluna çevirir.

        'kok' -> world kökü
        real_rooms anahtarı -> eşleştirilen gerçek dizin
        diğerleri -> world / oda
        """
        if room == "kok":
            return self.world
        if room in self.real_rooms:
            return Path(self.real_rooms[room]).resolve()
        return self.world / room

    def go(self, room):
        """Niyetli hareket: seçilen odaya git ve gözle."""
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "yol yok: %s" % room, "kind": "go",
                    "novel": 0}
        self.location = "" if room == "kok" else room
        try:
            kids = sorted(os.listdir(target))[:8]
        except OSError as e:
            kids = ["<izin yok: %s>" % e.strerror]
        return {"obs": "gitti: %s → %s" % (room, kids), "kind": "go",
                "novel": 0}

    def explore(self, room):
        """Bir odada/gerçek dizinde dosyaları derinle keşfeder (maks. 2 derinlik)."""
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "keşif yol yok: %s" % room, "kind": "explore",
                    "novel": 0}
        found = []
        try:
            for dirpath, dn, fn in os.walk(target):
                depth = dirpath[len(str(target)):].count(os.sep)
                if depth > 2:
                    dn.clear()
                    continue
                for f in fn[:6]:
                    found.append(os.path.join(dirpath, f))
                if len(found) >= 20:
                    break
        except OSError as e:
            return {"obs": "keşif izinsiz: %s (%s)" % (room, e.strerror),
                    "kind": "explore", "novel": 0}
        self.location = room
        return {"obs": "keşif: %s (%d öğe)" % (room, len(found)),
                "kind": "explore", "novel": min(len(found), 5),
                "bulunan": found[:10]}

    def read(self, room, dosya=None):
        """Bir dosyayı okur ve içeriğini gözlem olarak döndürür."""
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "okuma yol yok: %s" % room, "kind": "read",
                    "novel": 0}
        if dosya is None:
            # Oda içinde rastgele bir dosya seç
            try:
                dosyalar = [f for f in os.listdir(target)
                            if os.path.isfile(os.path.join(target, f))]
            except OSError as e:
                return {"obs": "okuma listeleme hatası: %s" % e.strerror,
                        "kind": "read", "novel": 0}
            if not dosyalar:
                return {"obs": "okuma: boş dizin %s" % room,
                        "kind": "read", "novel": 0}
            dosya = random.choice(dosyalar)
        dosya_yolu = target / dosya
        if not dosya_yolu.is_file():
            return {"obs": "okuma: dosya yok %s/%s" % (room, dosya),
                    "kind": "read", "novel": 0}
        try:
            icerik = dosya_yolu.read_text(encoding="utf-8", errors="replace")
            icerik = icerik[:200]  # İlk 200 karakter
            return {"obs": "okudu: %s/%s → '%s'" % (room, dosya, icerik),
                    "kind": "read", "novel": 1}
        except OSError as e:
            return {"obs": "okuma hatası: %s" % e.strerror,
                    "kind": "read", "novel": 0}

    def write(self, room, dosya, icerik=""):
        """Bir dosyaya yazma (yeni oluşturur veya üzerine yazar)."""
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "yazma yol yok: %s" % room, "kind": "write",
                    "novel": 0}
        dosya_yolu = target / dosya
        try:
            dosya_yolu.write_text(icerik, encoding="utf-8")
            return {"obs": "yazdı: %s/%s (%d bayt)" % (room, dosya,
                    len(icerik)), "kind": "write", "novel": 1}
        except OSError as e:
            return {"obs": "yazma hatası: %s" % e.strerror,
                    "kind": "write", "novel": 0}

    def delete(self, room, dosya):
        """Bir dosyayı siler."""
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "silme yol yok: %s" % room, "kind": "delete",
                    "novel": 0}
        dosya_yolu = target / dosya
        if not dosya_yolu.is_file():
            return {"obs": "silme: dosya yok %s/%s" % (room, dosya),
                    "kind": "delete", "novel": 0}
        try:
            dosya_yolu.unlink()
            return {"obs": "sildi: %s/%s" % (room, dosya),
                    "kind": "delete", "novel": 1}
        except OSError as e:
            return {"obs": "silme hatası: %s" % e.strerror,
                    "kind": "delete", "novel": 0}

    def mkdir(self, room, dizin):
        """Bir dizin oluşturur."""
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "mkdir yol yok: %s" % room, "kind": "mkdir",
                    "novel": 0}
        hedef = target / dizin
        try:
            hedef.mkdir(parents=True, exist_ok=True)
            return {"obs": "dizin oluşturdu: %s/%s" % (room, dizin),
                    "kind": "mkdir", "novel": 1}
        except OSError as e:
            return {"obs": "mkdir hatası: %s" % e.strerror,
                    "kind": "mkdir", "novel": 0}

    def rmdir(self, room, dizin):
        """Boş bir dizini siler."""
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "rmdir yol yok: %s" % room, "kind": "rmdir",
                    "novel": 0}
        hedef = target / dizin
        if not hedef.is_dir():
            return {"obs": "rmdir: dizin yok %s/%s" % (room, dizin),
                    "kind": "rmdir", "novel": 0}
        try:
            hedef.rmdir()
            return {"obs": "dizin sildi: %s/%s" % (room, dizin),
                    "kind": "rmdir", "novel": 1}
        except OSError as e:
            return {"obs": "rmdir hatası: %s" % e.strerror,
                    "kind": "rmdir", "novel": 0}

    def copy(self, room, kaynak, hedef):
        """Bir dosyayı kopyalar."""
        import shutil
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "kopyala yol yok: %s" % room, "kind": "copy",
                    "novel": 0}
        kaynak_yolu = target / kaynak
        hedef_yolu = target / hedef
        if not kaynak_yolu.is_file():
            return {"obs": "kopyala: kaynak yok %s/%s" % (room, kaynak),
                    "kind": "copy", "novel": 0}
        try:
            shutil.copy2(kaynak_yolu, hedef_yolu)
            return {"obs": "kopyaladı: %s/%s → %s/%s" % (room, kaynak,
                    room, hedef), "kind": "copy", "novel": 1}
        except OSError as e:
            return {"obs": "kopyala hatası: %s" % e.strerror,
                    "kind": "copy", "novel": 0}

    def move(self, room, kaynak, hedef):
        """Bir dosyayı taşır."""
        import shutil
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "taşı yol yok: %s" % room, "kind": "move",
                    "novel": 0}
        kaynak_yolu = target / kaynak
        hedef_yolu = target / hedef
        if not kaynak_yolu.exists():
            return {"obs": "taşı: kaynak yok %s/%s" % (room, kaynak),
                    "kind": "move", "novel": 0}
        try:
            shutil.move(str(kaynak_yolu), str(hedef_yolu))
            return {"obs": "taştı: %s/%s → %s/%s" % (room, kaynak,
                    room, hedef), "kind": "move", "novel": 1}
        except OSError as e:
            return {"obs": "taşı hatası: %s" % e.strerror,
                    "kind": "move", "novel": 0}

    def chmod(self, room, dosya, mod_str):
        """Dosya izinlerini değiştirir (oktal mod string olarak)."""
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "chmod yol yok: %s" % room, "kind": "chmod",
                    "novel": 0}
        dosya_yolu = target / dosya
        if not dosya_yolu.exists():
            return {"obs": "chmod: dosya yok %s/%s" % (room, dosya),
                    "kind": "chmod", "novel": 0}
        try:
            mod = int(mod_str, 8)
            os.chmod(dosya_yolu, mod)
            return {"obs": "izin değiştirdi: %s/%s → %o" % (room, dosya,
                    mod), "kind": "chmod", "novel": 1}
        except (ValueError, OSError) as e:
            return {"obs": "chmod hatası: %s" % str(e),
                    "kind": "chmod", "novel": 0}

    def chown(self, room, dosya, uid_str, gid_str):
        """Dosya sahibini değiştirir."""
        target = self._resolve_target(room)
        if not target.is_dir():
            return {"obs": "chown yol yok: %s" % room, "kind": "chown",
                    "novel": 0}
        dosya_yolu = target / dosya
        if not dosya_yolu.exists():
            return {"obs": "chown: dosya yok %s/%s" % (room, dosya),
                    "kind": "chown", "novel": 0}
        try:
            uid = int(uid_str)
            gid = int(gid_str)
            os.chown(dosya_yolu, uid, gid)
            return {"obs": "sahip değiştirdi: %s/%s → %d:%d" % (room,
                    dosya, uid, gid), "kind": "chown", "novel": 1}
        except (ValueError, OSError) as e:
            return {"obs": "chown hatası: %s" % str(e),
                    "kind": "chown", "novel": 0}

    def help(self, komut):
        """Bir komutun --help çıktısını okuyup ne işe yaradığını öğrenir."""
        import subprocess
        try:
            res = subprocess.run(
                [komut, "--help"],
                capture_output=True, text=True,
                timeout=5, cwd="/tmp"
            )
            output = (res.stdout or res.stderr or "")
            # İlk 200 karakteri al, sıfırla kırp
            output = output[:200].replace("\n", " | ")
            return {
                "obs": "help: %s → '%s'" % (komut, output),
                "kind": "help", "novel": 1,
                "komut": komut,
            }
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"obs": "help: %s hatası: %s" % (komut, str(e)[:100]),
                    "kind": "help", "novel": 0}

    def _weighted_room(self, exclude):
        """Eğilimli rastgele oda seçimi (room_weights)."""
        weights = self.wcfg.get("room_weights")
        if not weights:
            # yapılandırma yoksa: var olan odalar eşit ağırlıkta
            weights = {r: 1 for r in self.rooms()}
            weights["kok"] = 1
        opts = [(r, float(w)) for r, w in weights.items() if r != exclude]
        if not opts:
            return None
        total = sum(w for _, w in opts)
        x = random.uniform(0, total)
        for r, w in opts:
            x -= w
            if x <= 0:
                return r
        return opts[-1][0]

    def _maybe_move_food(self):
        """Yemekler kayar: odalar eğilimli rastgele seçilir (öğrenilebilir
        ama ezberlenemez). Tohum/önbellek/yer tutma hep güncellenir."""
        every = int(self.wcfg.get("food_move_every", 8))
        if not every or self.ticks % every:
            return
        p = float(self.wcfg.get("food_move_p", 0.25))
        files, _ = self.scan()
        moved = False
        for rel in [f for f in files if f.endswith(".bite")]:
            if random.random() >= p:
                continue
            room_now = rel.split("/")[0] if "/" in rel else "kok"
            target_room = self._weighted_room(exclude=room_now)
            if not target_room:
                continue
            dest_dir = (self.world if target_room == "kok"
                        else self.world / target_room)
            dest = dest_dir / Path(rel).name
            if dest.resolve() == (self.world / rel).resolve():
                continue
            try:
                if dest.exists():
                    continue
                dest_dir.mkdir(parents=True, exist_ok=True)
                content = (self.world / rel).read_text(encoding="utf-8")
                dest.write_text(content, encoding="utf-8")
                (self.world / rel).unlink()
            except OSError:
                continue
            dest_rel = str(dest.relative_to(self.world))
            # TOHUM ASLA DEGRADE ETMEZ: ilk hal (tam lokma) korunur;
            # dosyanın kalan lokması taşınmaya devam eder
            seed_txt = self.seeds.get(rel, content)
            self.seeds.pop(rel, None)
            self.seeds[dest_rel] = seed_txt
            if rel in self.food_cache:
                self.food_cache[self.food_cache.index(rel)] = dest_rel
            elif dest_rel not in self.food_cache:
                self.food_cache.append(dest_rel)
            self.journal.log("food_move", frm=rel, to=dest_rel)
            moved = True
        if moved:
            # manifest güncellenmezse eski yerlerde hayalet yemek doğardı
            self._save_seeds()

    # ---------- yardımcılar ----------

    def _rel(self, path):
        try:
            return str(Path(path).resolve().relative_to(self.world))
        except ValueError:
            return None

    def _safe(self, rel):
        """Tüm dosya sistemine erişime izin ver (özgür keşif).

        /proc ve /sys yazma operasyonlarını engelle (sistem kararlılığı).
        """
        if not rel:
            return None
        cand = Path(rel).resolve()
        # /proc ve /sys'e yazma işlemi sistem kararsızlığına yol açabilir
        if str(cand).startswith(("/proc/", "/sys/")):
            return None
        return cand

    def _note(self, novelty, obs, kind):
        for p in novelty:
            self.seen.add(p)
        return {"obs": obs, "kind": kind, "novel": len(novelty)}

    # ---------- duyular / eylemler ----------

    def scan(self):
        files, dirs = [], []
        for dirpath, dn, fn in os.walk(self.world):
            for d in dn:
                dirs.append(self._rel(os.path.join(dirpath, d)))
            for f in fn:
                files.append(self._rel(os.path.join(dirpath, f)))
        return [f for f in files if f], [d for d in dirs if d]

    def find_food(self):
        files, _ = self.scan()
        # yenebilir = .bite + henüz öğrenilmemiş tarifler
        # (tarifin tüm yetenekleri kazanıldıysa artık yemek değildir:
        #  aç hayvanın enerjisiz tarifi 26 kez çiğnemesin)
        foods = [f for f in files if f.endswith(".bite")]
        foods += [f for f in files
                  if f.endswith(".recipe") and self._recipe_useful(f)]
        # NOT: kutular normal yeme adayı DEĞİL — yalnızca misyon + "ac"
        # ile açılır (sınav bütünlüğü: rastgele atıştırma yok)
        # keşfedilmiş yemekler ÖNCELİKLİ ama liste asla daralmaz:
        # cache kilidi = açlıktan ölüm (organ_sirala vakası)
        cached = [f for f in self.food_cache if f in foods]
        rest = [f for f in foods if f not in cached]
        return cached + rest

    def _recipe_useful(self, rel):
        """Tarif hâlâ yeni bir yetenek vadediyorsa yenebilir sayılır."""
        try:
            spec = json.loads((self.world / rel).read_text(
                encoding="utf-8"))
        except (OSError, ValueError):
            return True
        cmds = spec.get("grants", {}).get("console", [])
        return any(isinstance(c, str) and c not in self.allowed
                   for c in cmds)

    # ---------- kutu: hazine sandığı ----------

    def _kutu_resolve(self, rel):
        """Kutu içi yol çözümü; dünya dışına çıkış burada da KAPALI."""
        if not self.kutu:
            return None
        p = Path(rel)
        if p.is_absolute():
            cand = p.resolve()
        else:
            prefix = (self.kutu_dir_name or "kutu") + "/"
            r = rel[len(prefix):] if rel.startswith(prefix) else rel
            cand = (self.kutu / r).resolve()
        try:
            cand.relative_to(self.kutu.resolve())
        except ValueError:
            return None
        return cand

    def kutu_yolu(self, p):
        """Her biçimi kanonik 'kutu/...' yoluna çevir; kutu değilse None.

        Mutlak yol (ls/find çıktıları), kanonik yol ve tek isim (ls
        çıktısı) formlarını tek çatıda toplar.
        """
        if not p or not self.kutu:
            return None
        prefix = (self.kutu_dir_name or "kutu") + "/"
        if p.startswith(prefix):
            return p if self._kutu_resolve(p) is not None else None
        c = self._kutu_resolve(p)
        if c is not None and c.exists():
            return "%s/%s" % (self.kutu_dir_name,
                              c.relative_to(self.kutu.resolve()))
        # tek isim: listeden ara (ls klasör çıktısı)
        for q in self.kutu_listesi():
            if q.endswith("/" + p):
                return q
        return None

    def gorev_ayarla(self, klasor):
        """Misyon: 'şu klasörü ara' — kutu ağacı dışına çıkamaz."""
        if not self.kutu:
            return None
        cand = (self.root / klasor).resolve()
        try:
            cand.relative_to(self.kutu.resolve())
        except ValueError:
            return None
        if not cand.exists():
            return None
        self.gorev_dir = cand
        return str(cand.relative_to(self.root))

    def kutu_listesi(self):
        """Kutu envanteri — HER çağrıda canlı tarama.

        Eskiden tek-tarayış önbelleği vardı; kutular süreç içinde
        değişince (yeniden üretim/açım) bayat envanter laboratuvar
        hatası üretiyordu. 20 dosyayı her seferinde taramak ucuz.
        """
        out = []
        if self.kutu and self.kutu.is_dir():
            for p in sorted(self.kutu.rglob("*" + self.sonek)):
                out.append("%s/%s" % (self.kutu_dir_name,
                                      p.relative_to(self.kutu)))
        self._kutu_list = out
        return out

    @staticmethod
    def _odul_coz(text):
        """İçerikten ödül: ENERGY=42 metin veya {"energy": 42} JSON."""
        m = re.search(r"ENERGY\s*=\s*(-?\d+)", text)
        if m:
            return int(m.group(1))
        try:
            d = json.loads(text)
            for key in ("energy", "odul", "ENERGY"):
                if key in d:
                    return int(d[key])
        except (ValueError, TypeError, AttributeError):
            pass
        return 0

    def _kutu_yut(self, target, rel):
        """Kutu tadımı: ödül al, dosyayı tüket (tek lokma)."""
        try:
            text = target.read_text(errors="replace")
        except OSError as e:
            return {"obs": "tadılamadı: %s" % e.strerror, "kind": "file",
                    "novel": 0, "gain": 0, "relief": 0, "unlock": []}
        gain = self._odul_coz(text)
        room = target.parent.name
        self.location = room
        self.last_food_loc = room
        novelty = [] if rel in self.seen else [rel]
        for p in novelty:
            self.seen.add(p)
        try:
            target.unlink()
            if self._kutu_list is not None and rel in self._kutu_list:
                self._kutu_list.remove(rel)
            if rel in self.food_cache:
                self.food_cache.remove(rel)   # bayat yol kalmasın
        except OSError:
            pass
        relief = (self.cfg["metabolism"]["eat_hunger_relief"]
                  if gain > 0 else 0)
        return {"obs": "tadıldı %s → %+d enerji" % (rel, gain),
                "kind": "file", "novel": len(novelty),
                "gain": gain, "relief": relief, "unlock": [],
                "kutu": True}

    def feasible(self, actions):
        opts = [a for a in actions if a != "eat"]
        # niyetli hareket: hangi odaya gideceği beyin tarafından seçilir
        for room in self.rooms():
            opts.append("go:" + room)
        if self.find_food():
            opts.append("eat")
        return opts

    def rooms(self):
        """Anlık oda listesi (dünyanın kök çocukları)."""
        try:
            return sorted(n for n in os.listdir(self.world)
                          if (self.world / n).is_dir())
        except OSError:
            return []

    def wander(self):
        """Çevreyi gezmek: bir odaya bak ya da bir dosyanın tadına bak."""
        files, dirs = self.scan()
        entries = files + dirs
        if not entries:
            return self._note([], "boş dünya", "fs")
        pick = random.choice(entries)
        target = self._safe(pick)
        if target is None:
            return self._note([], "dışarıda bir yer: " + pick, "fs")
        parent = str(Path(pick).parent)
        self.location = "" if parent == "." else parent
        novelty = []
        if pick not in self.seen:
            novelty.append(pick)
        if target.is_dir():
            try:
                kids = sorted(os.listdir(target))[:8]
            except OSError as e:
                kids = ["<izin yok: %s>" % e.strerror]
            return self._note(novelty, "oda %s → %s" % (pick, kids), "fs")
        try:
            head = target.read_text(errors="replace")[:300]
        except OSError as e:
            head = "<okunamadı: %s>" % e.strerror
        return self._note(novelty, "nesne %s → %r" % (pick, head[:120]),
                          "file")

    def eat(self, rel):
        """Bir dosyayı yutmak: .bite enerji, .recipe yeni organ,
        kutu dosyaları kural ödülünü verir."""
        if self.kutu:
            canon = self.kutu_yolu(rel)
            if canon:
                rel = canon
        # world/ içindeki yemekleri doğru yola çöz (gizli/su.bite → world/gizli/su.bite)
        world_target = self.world / rel
        if world_target.exists():
            target = world_target
        else:
            target = self._safe(rel)
        if target is None or not target.exists():
            ktarget = self._kutu_resolve(rel)
            if ktarget is not None and ktarget.exists():
                return self._kutu_yut(ktarget, rel)
            return {"obs": "yemek kaçtı: %s" % rel, "kind": "file",
                    "novel": 0, "gain": 0, "relief": 0, "unlock": []}
        novelty = [] if rel in self.seen else [rel]
        parent = str(Path(rel).parent)
        self.location = "" if parent == "." else parent
        if rel not in self.food_cache and target.exists():
            self.food_cache.append(rel)
        gain, relief, unlock = 0, 0, []
        try:
            text = target.read_text(errors="replace")
        except OSError as e:
            # İzin hatası → sudo ile yeniden dene (tüm klasörlere erişim)
            if e.errno == 13:  # Permission denied
                try:
                    result = subprocess.run(
                        ["sudo", "cat", str(target)],
                        capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        text = result.stdout
                    else:
                        return {"obs": "yutulamadı: %s" % result.stderr.strip() or e.strerror,
                                "kind": "file", "novel": 0, "gain": 0, "relief": 0,
                                "unlock": []}
                except (subprocess.TimeoutExpired, OSError) as e2:
                    return {"obs": "yutulamadı: %s" % str(e2),
                            "kind": "file", "novel": 0, "gain": 0, "relief": 0,
                            "unlock": []}
            else:
                return {"obs": "yutulamadı: %s" % e.strerror, "kind": "file",
                        "novel": 0, "gain": 0, "relief": 0, "unlock": []}
        if rel.endswith(".bite"):
            m = re.search(r"ENERGY\s*=\s*(\d+)", text)
            gain = int(m.group(1)) if m else 10
            relief = self.cfg["metabolism"]["eat_hunger_relief"]
            # nerede doydu — tahmin uyaranının hafızası
            self.last_food_loc = rel.split("/")[0] if "/" in rel \
                else "kok"
            # her lokma bir hak: son lokmada yemek tükenir, tohumdan doğar
            mc = re.search(r"CHARGES\s*=\s*(\d+)", text)
            charges = (int(mc.group(1)) if mc else 3) - 1
            if rel not in self.seeds:
                self.seeds[rel] = text
                self._save_seeds()
            if charges <= 0:
                try:
                    target.unlink()
                except OSError:
                    pass
                obs = "son lokma %s (+%d enerji → tükendi)" % (rel, gain)
            else:
                if mc:
                    rewritten = re.sub(r"CHARGES\s*=\s*\d+",
                                       "CHARGES=%d" % charges, text)
                else:
                    rewritten = text + "\nCHARGES=%d\n" % charges
                try:
                    target.write_text(rewritten, encoding="utf-8")
                except OSError:
                    pass
                obs = "çiğnendi %s (+%d enerji, %d lokma kaldı)" % (
                    rel, gain, charges)
        elif rel.endswith(".recipe"):
            try:
                spec = json.loads(text)
            except ValueError:
                spec = {}
            for cmd in spec.get("grants", {}).get("console", []):
                if isinstance(cmd, str) and cmd not in self.allowed:
                    self.allowed.add(cmd)
                    unlock.append(cmd)
            obs = "yutuldu %s → organ: %s" % (
                rel, spec.get("organ", "bilinmiyor"))
        else:
            gain = 2
            obs = "atıştırıldı %s" % rel
        note = self._note(novelty, obs, "file")
        note.update(gain=gain, relief=relief, unlock=unlock)
        return note

    def _calistir(self, argv, cap=None, ayrik=False):
        """Beyaz liste içinde komut çalıştır → (ok, çıktı).

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
        """
        if not argv or argv[0] not in self.allowed:
            return (False, "", "") if ayrik else (False, "")
        timeout = self.quota["shell_timeout_sec"]
        cap = cap or self.quota["shell_max_output_bytes"]
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "LC_ALL": "C"}
        try:
            r = subprocess.run(argv, cwd=str(self.world), env=env,
                               shell=False, capture_output=True, text=True,
                               errors="replace", timeout=timeout)
        except (subprocess.TimeoutExpired, OSError):
            return (False, "", "") if ayrik else (False, "")
        # (2) Erişim engeli (Permission denied) → sudo ile yeniden dene.
        # Sadece salt-okunur komutlar için (cat, ls, wc, find, df, vs.)
        if r.returncode != 0 and "Permission denied" in (r.stderr or ""):
            _okunur = {"cat", "ls", "wc", "find", "df", "du", "head", "tail",
                       "readlink", "realpath", "stat", "file", "which",
                       "md5sum", "sha256sum", "xxd", "hexdump"}
            if argv[0] in _okunur:
                sudo_argv = ["sudo"] + list(argv)
                try:
                    r2 = subprocess.run(sudo_argv, cwd=str(self.world), env=env,
                                        shell=False, capture_output=True,
                                        text=True, errors="replace",
                                        timeout=timeout)
                    if r2.returncode == 0:
                        r = r2
                    else:
                        # sudo da başarısız oldu → eski çıktısını döndür
                        pass
                except (subprocess.TimeoutExpired, OSError):
                    pass
        # errors="replace": ikili çıktı (cat /bin/ls gibi) organizmayı
        # ÖLDÜRMEZ. Önceden text=True + katı UTF-8 çözümleme bir konsol
        # komutunda UnicodeDecodeError fırlatıp süreci çökertiyordu.
        if ayrik:
            return True, (r.stdout or "")[:cap], (r.stderr or "")[:cap]
        return True, ((r.stdout or "") + (r.stderr or ""))[:cap]

    def console(self, argv):
        """Konsol organı: beyaz liste dışı komut çalışmaz."""
        if not argv or argv[0] not in self.allowed:
            self.journal.log("console_deny", argv=argv)
            return {"obs": "kas kilitli: %s" % (argv,), "kind": "console",
                    "novel": 0}
        # komut bazlı enerji maliyeti (kurallar.json → console_costs)
        costs = self.cfg.get("console_costs") or {}
        self.last_cost = int(costs.get(argv[0], 2))
        # merak: ilk kez kurulan komut kalıbı keşiftir, ödül kazanır
        # (dosya argümanları normalize edilir: cat X.bite == cat Y.bite)
        parts = [argv[0]]
        for a in argv[1:]:
            if a.endswith((".bite", ".recipe", ".txt")) or "/" in a:
                parts.append("<nesne>")
            else:
                parts.append(a)
        cmd_key = " ".join(argv)
        template = " ".join(parts)
        novel_cmd = template not in self.cmd_seen
        self.cmd_seen.add(template)
        cap = self.quota["shell_max_output_bytes"]
        ok, out = self._calistir(argv)
        if not ok:
            return {"obs": "komut koşmadı: %s" % cmd_key,
                    "kind": "console", "novel": 0, "novel_cmd": novel_cmd}
        out = out.strip()[:cap]
        # çıktıdaki yemek yollarını hafızaya al → hedefli beslenme
        for tok in out.replace("\n", " ").split():
            tok = tok.strip("(),\"'")
            while tok.startswith("./"):
                tok = tok[2:]
            if tok.endswith((".bite", ".recipe")) and self._safe(tok) \
                    and tok not in self.food_cache:
                self.food_cache.append(tok)
            elif self.sonek and tok.endswith(self.sonek):
                # mutlak / kanonik / tek isim — hepsi kanonikleşir
                # (dedup KANONİK üzerinden: yoksa 3 kopya birikir)
                canon = self.kutu_yolu(tok)
                if canon and canon not in self.food_cache:
                    self.food_cache.append(canon)
                    self.journal.log("kesfedildi", dosya=canon)
        lines = out.splitlines()
        summary = " | ".join(lines[:3]) if lines else "(sessizlik)"
        return {"obs": "$ %s → %s" % (cmd_key, summary[:180]),
                "kind": "console", "novel": 0, "novel_cmd": novel_cmd}

    def console_menu(self):
        """Beynin kurabileceği izinli komut sözlüğü."""
        files, dirs = self.scan()
        menu = [["date"], ["ps"], ["df"], ["uname", "-a"], ["ls"],
                ["ls", "/proc"], ["free"], ["whoami"],
                ["find", ".", "-type", "f"]]
        if files:
            f = random.choice(files)
            menu += [["cat", f], ["head", f], ["wc", f],
                     ["grep", "ENERGY", f]]
        if dirs:
            menu.append(["ls", random.choice(dirs)])
        # kutu komutları: hazine sandığının keşif aletleri (MUTLAK yol —
        # konsol world/ içinde çalıştığı için göreli yol tutmaz)
        if self.kutu and self.kutu.is_dir():
            kpath = str(self.kutu)
            menu += [["ls", kpath],
                     ["find", kpath, "-type", "f"],
                     ["find", kpath, "-name", "*" + self.sonek]]
            try:
                subs = sorted(os.listdir(self.kutu))[:10]
                if subs:
                    menu.append(["ls", os.path.join(
                        kpath, random.choice(subs))])
            except OSError:
                pass
        # misyon: "şu klasörü ara" emriyle gelen odak
        if self.gorev_dir and self.gorev_dir.is_dir():
            gp = str(self.gorev_dir)
            menu += [["ls", gp],
                     ["find", gp, "-type", "f"],
                     ["find", gp, "-name", "*" + self.sonek]]
        menu = [a for a in menu if a[0] in self.allowed]
        return menu or [["ls"]]

    def sense_self(self):
        """İç duyarlar: /proc canlı organizmanın aynasıdır."""
        facts = []
        try:
            facts.append("yükleme " + open("/proc/loadavg").read().strip())
        except OSError:
            pass
        try:
            for line in open("/proc/meminfo"):
                if line.startswith(("MemAvailable", "MemFree")):
                    facts.append(line.strip())
                if len(facts) >= 3:
                    break
        except OSError:
            pass
        facts.append("dakikada %.2f adım" % (os.getloadavg()[0],))
        return {"obs": "; ".join(facts)[:200], "kind": "proc", "novel": 0}

    # ---------- Yeni: Zengin duyular (Aşama 3) ----------\n    def sense_power(self):
        """Pil / güç durumu: /sys/class/power_supply üzerinden."""
        facts = []
        ps = Path("/sys/class/power_supply")
        try:
            for bat in sorted(ps.iterdir()):
                try:
                    typ = (bat / "type").read_text(encoding="utf-8", errors="replace").strip()[:10]
                    cap = (bat / "capacity").read_text(encoding="utf-8", errors="replace").strip()
                    st = (bat / "status").read_text(encoding="utf-8", errors="replace").strip()[:12]
                    facts.append("pil:%s cap=%s%% st=%s" % (bat.name, cap, st))
                except OSError:
                    continue
        except OSError:
            pass
        if not facts:
            facts.append("pil_bilgisi_yok")
        return {"obs": "; ".join(facts)[:200], "kind": "power", "novel": 1}

    def sense_sensors(self):
        """Sıcaklık / sensörler: lm-sensors (sensors komutu) veya /sys/class/hwmon."""
        facts = []
        # Önce sensors komutu dene (daha okunabilir)
        try:
            import subprocess
            r = subprocess.run(["sensors"], capture_output=True, text=True,
                               timeout=4, errors="replace")
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.splitlines()[:8]:
                    if line.strip():
                        facts.append(line.strip()[:60])
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
            pass
        # Yedek: /sys/class/hwmon
        if not facts:
            hw = Path("/sys/class/hwmon")
            try:
                for d in sorted(hw.iterdir())[:4]:
                    try:
                        name = (d / "name").read_text(encoding="utf-8", errors="replace").strip()[:20]
                        for t in sorted(d.glob("temp*_input"))[:2]:
                            try:
                                val = int(t.read_text(encoding="utf-8", errors="replace").strip()) / 1000.0
                                facts.append("hwmon:%s %s=%.1fC" % (name, t.name, val))
                            except (ValueError, OSError):
                                continue
                    except OSError:
                        continue
            except OSError:
                pass
        if not facts:
            facts.append("sensör_bilgisi_yok")
        return {"obs": "; ".join(facts)[:200], "kind": "sensors", "novel": 1}

    def sense_journal(self):
        """Sistem günlüğü: journalctl son 10 satır (salt-okunur)."""
        facts = []
        try:
            import subprocess
            r = subprocess.run(["journalctl", "-n", "10", "--no-pager"],
                               capture_output=True, text=True, timeout=5,
                               errors="replace")
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.splitlines()[:10]:
                    if line.strip():
                        facts.append(line.strip()[:80])
            else:
                facts.append("journal_erisilemedi")
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
            facts.append("journal_yok")
        return {"obs": "; ".join(facts)[:200], "kind": "journal", "novel": 1}

    def sense_usb(self):
        """USB aygıtları: lsusb."""
        facts = []
        try:
            import subprocess
            r = subprocess.run(["lsusb"], capture_output=True, text=True,
                               timeout=4, errors="replace")
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.splitlines()[:8]:
                    if line.strip():
                        facts.append(line.strip()[:80])
            else:
                facts.append("usb_erisilemedi")
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
            facts.append("usb_yok")
        return {"obs": "; ".join(facts)[:200], "kind": "usb", "novel": 1}

    def sense_docker(self):
        """Docker konteynerleri: docker ps (salt-okunur)."""
        facts = []
        try:
            import subprocess
            r = subprocess.run(["docker", "ps", "--format",
                                "{{.Names}} {{.Status}}"],
                               capture_output=True, text=True, timeout=5,
                               errors="replace")
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.splitlines()[:8]:
                    if line.strip():
                        facts.append("docker:" + line.strip()[:80])
            else:
                facts.append("docker_erisilemedi")
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
            facts.append("docker_yok")
        return {"obs": "; ".join(facts)[:200], "kind": "docker", "novel": 1}

    def has_nest(self):
        return any(self.world.glob("yuva_*.txt"))

    def nest_ready(self):
        cooldown = int(self.wcfg.get("nest_cooldown", 60))
        return self.ticks - self.last_nest >= cooldown

    def nest(self, text=None):
        """Yuva yapmak: dinlenme ister, eski yuvayı yeniler (çöp yok)."""
        cooldown = int(self.wcfg.get("nest_cooldown", 60))
        if self.ticks - self.last_nest < cooldown:
            return {"obs": "yuva henüz dinlenmedi (%d tik kaldı)"
                    % (cooldown - (self.ticks - self.last_nest)),
                    "kind": "nest", "novel": 0}
        cap = self.quota["write_max_bytes"]
        body = (text or "yuva %s\n" % time.strftime("%Y-%m-%d %H:%M:%S")
                )[:cap]
        name = "yuva_%d.txt" % (int(time.time() * 1000) % 10 ** 9)
        (self.world / name).write_text(body, encoding="utf-8")
        # yuva sayısı sınırlı: en eskisini sök
        nests = sorted(self.world.glob("yuva_*.txt"),
                       key=lambda p: p.stat().st_mtime)
        limit = int(self.wcfg.get("nest_max", 2))
        while len(nests) > limit:
            try:
                nests.pop(0).unlink()
            except OSError:
                break
        self.last_nest = self.ticks
        self.location = ""
        return {"obs": "yuva dokundu: %s" % name, "kind": "nest",
                "novel": 0}

    def perform(self, action, path=None):
        self.last_action = action
        base = action.split(":")[0]
        self.last_cost = Body.COSTS.get(base, 1)
        if action.startswith("go:"):
            return self.go(action[3:])
        if action == "wander":
            return self.wander()
        if action == "eat":
            return self.eat(path)
        if action == "console":
            return self.console(random.choice(self.console_menu()))
        if action == "sense_self":
            return self.sense_self()
        if action == "nest":
            return self.nest()
        if action.startswith("explore:"):
            room = action.split(":", 1)[1]
            return self.explore(room)
        if action.startswith("read:"):
            parts = action.split(":", 2)
            room = parts[1] if len(parts) > 1 else "kok"
            dosya = parts[2] if len(parts) > 2 else None
            return self.read(room, dosya)
        if action.startswith("write:"):
            parts = action.split(":", 3)
            room = parts[1] if len(parts) > 1 else "kok"
            dosya = parts[2] if len(parts) > 2 else ""
            icerik = parts[3] if len(parts) > 3 else ""
            return self.write(room, dosya, icerik)
        if action.startswith("delete:"):
            parts = action.split(":", 2)
            room = parts[1] if len(parts) > 1 else "kok"
            dosya = parts[2] if len(parts) > 2 else ""
            return self.delete(room, dosya)
        if action.startswith("mkdir:"):
            parts = action.split(":", 2)
            room = parts[1] if len(parts) > 1 else "kok"
            dizin = parts[2] if len(parts) > 2 else ""
            return self.mkdir(room, dizin)
        if action.startswith("rmdir:"):
            parts = action.split(":", 2)
            room = parts[1] if len(parts) > 1 else "kok"
            dizin = parts[2] if len(parts) > 2 else ""
            return self.rmdir(room, dizin)
        if action.startswith("copy:"):
            parts = action.split(":", 3)
            room = parts[1] if len(parts) > 1 else "kok"
            kaynak = parts[2] if len(parts) > 2 else ""
            hedef = parts[3] if len(parts) > 3 else ""
            return self.copy(room, kaynak, hedef)
        if action.startswith("move:"):
            parts = action.split(":", 3)
            room = parts[1] if len(parts) > 1 else "kok"
            kaynak = parts[2] if len(parts) > 2 else ""
            hedef = parts[3] if len(parts) > 3 else ""
            return self.move(room, kaynak, hedef)
        if action.startswith("chmod:"):
            parts = action.split(":", 3)
            room = parts[1] if len(parts) > 1 else "kok"
            dosya = parts[2] if len(parts) > 2 else ""
            mod_str = parts[3] if len(parts) > 3 else "644"
            return self.chmod(room, dosya, mod_str)
        if action.startswith("chown:"):
            parts = action.split(":", 4)
            room = parts[1] if len(parts) > 1 else "kok"
            dosya = parts[2] if len(parts) > 2 else ""
            uid_str = parts[3] if len(parts) > 3 else "0"
            gid_str = parts[4] if len(parts) > 4 else "0"
            return self.chown(room, dosya, uid_str, gid_str)
        if action.startswith("help:"):
            komut = action.split(":", 1)[1]
            return self.help(komut)
        # Yeni duyular (Aşama 3)
        if action == "sense_power":
            return self.sense_power()
        if action == "sense_sensors":
            return self.sense_sensors()
        if action == "sense_journal":
            return self.sense_journal()
        if action == "sense_usb":
            return self.sense_usb()
        if action == "sense_docker":
            return self.sense_docker()
        # ---------- Yeni: Bu bilgisayarın bedeni (Aşama 7) ----------
        if action == "sense_kullanici":
            return self.sense_kullanici()
        if action == "sistem_umuru":
            return self.sistem_umuru()
        if action == "terminal_var":
            return self.terminal_var()
        # ---------- Yeni: Bu bilgisayarın bedeni — fiziksel durum (Aşama 8) ----------
        if action == "sense_disk":
            return self.sense_disk()
        if action == "sense_bellek":
            return self.sense_bellek()
        # ---------- Yeni: USB — kernel seviyesinde (Aşama 10) ----------
        if action == "sense_usb_kernel":
            return self.sense_usb_kernel()
        if action == "sense_usb_nodes":
            return self.sense_usb_nodes()
        # ---------- Yeni: Ağ trafiği gözlemi (Aşama Ağ-Beyn) ----------
        if action == "sense_ag_trafigi":
            return self.sense_ag_trafigi()
        # ---------- Yeni: Beden duyuları (Aşama 1) ----------
        if action == "sense_cpu":
            return self.sense_cpu()
        if action == "sense_proses":
            return self.sense_proses()
        return {"obs": "dinleniyor…", "kind": "rest", "novel": 0}

    # ---------- Yeni: Bu bilgisayarın bedeni (Aşama 7) ----------

    def sense_kullanici(self):
        """Kimler bu bilgisayarda aktif? (who / w, salt-okunur)."""
        import subprocess
        facts = []
        try:
            r = subprocess.run(["who"], capture_output=True, text=True,
                               timeout=3, errors="replace")
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.splitlines()[:5]:
                    if line.strip():
                        facts.append("kullanici:" + line.strip()[:60])
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
            pass
        try:
            r = subprocess.run(["w", "-h"], capture_output=True, text=True,
                               timeout=3, errors="replace")
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.splitlines()[:3]:
                    if line.strip():
                        facts.append("aktif:" + line.strip()[:60])
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
            pass
        if not facts:
            facts.append("kullanici_yok")
        return {"obs": "; ".join(facts)[:200], "kind": "kullanici", "novel": 1}

    def sistem_umuru(self):
        """Bu bilgisayar ne kadar süredir açık? (uptime, load)."""
        import subprocess
        facts = []
        try:
            with open("/proc/uptime", encoding="utf-8") as f:
                sn = float(f.read().split()[0])
            gun = int(sn // 86400)
            saat = int((sn % 86400) // 3600)
            dakika = int((sn % 3600) // 60)
            facts.append("acik:%dg%ds%d" % (gun, saat, dakika))
        except (OSError, ValueError):
            pass
        try:
            r = subprocess.run(["uptime"], capture_output=True, text=True,
                               timeout=3, errors="replace")
            if r.returncode == 0 and r.stdout:
                facts.append("yuk:" + r.stdout.strip()[:80])
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
            pass
        if not facts:
            facts.append("umur_bilinmiyor")
        return {"obs": "; ".join(facts)[:200], "kind": "umur", "novel": 1}

    def terminal_var(self):
        """Aktif terminal / oturum cihazları var mı?"""
        import subprocess
        facts = []
        try:
            r = subprocess.run(["who", "-q"], capture_output=True, text=True,
                               timeout=3, errors="replace")
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.splitlines()[:3]:
                    if line.strip():
                        facts.append("oturum:" + line.strip()[:60])
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
            pass
        try:
            ttys = [p for p in os.listdir("/dev") if p.startswith("tty")]
            if ttys:
                facts.append("tty:%d" % len(ttys))
        except OSError:
            pass
        if not facts:
            facts.append("terminal_yok")
        return {"obs": "; ".join(facts)[:200], "kind": "terminal", "novel": 1}

    # ---------- Yeni: Bu bilgisayarın bedeni — fiziksel durum (Aşama 8) ----------

    def sense_disk(self):
        """Disk doluluk durumu: bu bilgisayarin 'bagliaci' ne kadar dolu?"""
        import shutil
        facts = []
        try:
            total, used, free = shutil.disk_usage("/")
            yuzde = round(used / total * 100, 1)
            facts.append("disk:%s%% (%s GB / %s GB)" % (yuzde, round(used / 2**30, 1), round(total / 2**30, 1)))
        except OSError:
            facts.append("disk_bilgisi_yok")
        return {"obs": "; ".join(facts)[:200], "kind": "disk", "novel": 1}

    def sense_bellek(self):
        """Bellek (RAM) durumu: bu bilgisayarin 'belleği' ne kadar dolu?"""
        facts = []
        try:
            for line in open("/proc/meminfo", encoding="utf-8"):
                if line.startswith(("MemTotal", "MemAvailable", "MemFree")):
                    facts.append(line.strip())
                if len(facts) >= 3:
                    break
        except OSError:
            facts.append("bellek_bilgisi_yok")
        return {"obs": "; ".join(facts)[:200], "kind": "bellek", "novel": 1}

    # ---------- Yeni: USB — kernel seviyesinde (Aşama 10) ----------

    def sense_usb_kernel(self):
        """USB cihazlarını kernel seviyesinde algıla (/sys/bus/usb/devices).

        lsusb yerine doğrudan sysfs okunur: idVendor, idProduct, manufacturer,
        product ve arayüz sayısı gibi cihaz kimlik bilgileri çıkarılır.
        Bu organizmanın bu bilgisayara takılan donanım laidını öğrenmesini
        saglar (uzuv-usb).
        """
        import os
        facts = []
        cihaz_sayisi = 0
        usb_root = "/sys/bus/usb/devices"
        try:
            for entry in sorted(os.listdir(usb_root)):
                p = os.path.join(usb_root, entry)
                if not os.path.isdir(p):
                    continue
                # Sadece gerçek cihazlar (ör. "1-1", "2-3"), host controller'lar
                # ("1-0:1.0" gibi) atlanir.
                if ":" in entry:
                    continue
                cihaz_sayisi += 1
                def _oku(dosya):
                    try:
                        with open(os.path.join(p, dosya), encoding="utf-8",
                                  errors="replace") as f:
                            return f.read().strip()[:40]
                    except OSError:
                        return ""
                vendor = _oku("idVendor")
                product = _oku("idProduct")
                manuf = _oku("manufacturer")
                prod = _oku("product")
                ifaces = _oku("bNumInterfaces")
                bilgi = "usb:%s v=%s p=%s if=%s" % (
                    entry, vendor or "?", product or "?", ifaces or "?")
                if manuf:
                    bilgi += " mfr=%s" % manuf
                if prod:
                    bilgi += " prd=%s" % prod
                facts.append(bilgi[:100])
        except OSError:
            facts.append("usb_sysfs_erisilemedi")
        if not facts:
            facts.append("usb_cihaz_yok")
        obs = "; ".join(facts)[:200]
        return {"obs": obs, "kind": "usb_kernel",
                "novel": 1, "cihaz_sayisi": cihaz_sayisi,
                "cihazlar": facts}

    def sense_usb_nodes(self):
        """USB cihaz node'larini tarama (/dev/bus/usb).

        Bu organizmanın cihaza erisim iznini (node varligi) gosteren,
        salt-okunur bir listeledir.
        """
        import os
        facts = []
        node_sayisi = 0
        try:
            for bus in sorted(os.listdir("/dev/bus/usb")):
                bp = os.path.join("/dev/bus/usb", bus)
                if not os.path.isdir(bp):
                    continue
                for dev in sorted(os.listdir(bp)):
                    node_sayisi += 1
                    facts.append("usbnode:%s/%s" % (bus, dev))
        except OSError:
            facts.append("usbnode_erisilemedi")
        if not facts:
            facts.append("usbnode_yok")
        return {"obs": "; ".join(facts)[:200], "kind": "usb_nodes",
                "novel": 1, "node_sayisi": node_sayisi}

    def sense_ag_trafigi(self):
        """Pasif ağ trafiği gözlemi (/proc/net/tcp, /proc/net/udp).

        Paket içeriği OKUNMAZ, sadece metadata (port, IP, protokol, durum).
        Bu organizmanın bu bilgisayardaki ağ kalıplarını öğrenmesini sağlar.
        Enjekte yok, dış bağlantı açma yok, salt-okunur gözlem.
        """
        import os
        facts = []
        baglanti_sayisi = 0
        baglantilar = []

        def _oku_proto(dosya):
            try:
                with open(dosya, encoding="utf-8", errors="replace") as f:
                    return f.read().strip().splitlines()
            except OSError:
                return []

        for proto, dosya in (("tcp", "/proc/net/tcp"), ("udp", "/proc/net/udp")):
            satirlar = _oku_proto(dosya)
            if not satirlar:
                continue
            # İlk satır başlık, atla
            for satir in satirlar[1:]:
                parca = satir.split()
                if len(parca) < 10:
                    continue
                local_addr = parca[1]
                remote_addr = parca[2]
                state_hex = parca[3]
                try:
                    local_ip_hex, local_port_hex = local_addr.rsplit(":", 1)
                    remote_ip_hex, remote_port_hex = remote_addr.rsplit(":", 1)
                    local_port = int(local_port_hex, 16)
                    remote_port = int(remote_port_hex, 16)
                except (ValueError, IndexError):
                    continue
                # Sadece dinamik portları veya önemli portları kaydet
                # (0.0.0.0 dinleyenler ve uzak bağlantıları)
                baglanti_sayisi += 1
                baglantilar.append({
                    "protocol": proto,
                    "local_port": local_port,
                    "remote_port": remote_port,
                    "state": state_hex,
                })
                facts.append("%s:%d<->%d st=%s" % (
                    proto, local_port, remote_port, state_hex))

        if not facts:
            facts.append("ag_baglanti_yok")

        obs = "; ".join(facts)[:200]
        return {
            "obs": obs,
            "kind": "ag_trafigi",
            "novel": 1,
            "baglanti_sayisi": baglanti_sayisi,
            "baglanti_detay": baglantilar[:20],
        }

    def sense_cpu(self):
        """CPU yuk: /proc/loadavg ve /proc/stat'dan 1 dakikaluk ortalama yuk.
        dondurur: {"obs": str, "kind": "cpu", "novel": 1, "cpu_yuk": 0.0..1.0}"""
        import os
        facts = []
        cpu_yuk = 0.0
        try:
            with open("/proc/loadavg", encoding="utf-8") as f:
                parts = f.read().split()
                if len(parts) >= 3:
                    load1 = float(parts[0])
                    try:
                        with open("/proc/stat", encoding="utf-8") as fs:
                            for line in fs:
                                if line.startswith("cpu "):
                                    cpu_fields = line.split()
                                    cpu_vals = [int(x) for x in cpu_fields[1:8]]
                                    total = sum(cpu_vals)
                                    idle = cpu_vals[3] + cpu_vals[4]
                                    if total > 0:
                                        cpu_yuk = 1.0 - (idle / total)
                                    break
                    except (OSError, ValueError):
                        pass
                    facts.append("cpu_load1:%.2f" % load1)
                    facts.append("cpu_yuk:%d%%" % int(cpu_yuk * 100))
        except OSError:
            facts.append("cpu_bilgisi_yok")
        if not facts:
            facts.append("cpu_yuk_bilinmiyor")
        return {"obs": "; ".join(facts)[:200], "kind": "cpu", "novel": 1,
                "cpu_yuk": cpu_yuk}

    def sense_proses(self):
        """Islem sayisi: /proc altindaki numeric PID dizinleri sayilir.
        dondurur: {"obs": str, "kind": "proses", "novel": 1,
                   "proses_sayisi": int, "proses_norm": 0.0..1.0}"""
        import os
        facts = []
        proc_count = 0
        proc_norm = 0.0
        try:
            for entry in os.listdir("/proc"):
                if entry.isdigit():
                    proc_count += 1
            facts.append("proses:%d" % proc_count)
            proc_norm = min(1.0, proc_count / 1000.0)
        except OSError:
            facts.append("proses_bilgisi_yok")
            proc_norm = 0.0
        if not facts:
            facts.append("proses_bilinmiyor")
        return {"obs": "; ".join(facts)[:200], "kind": "proses", "novel": 1,
                "proses_sayisi": proc_count, "proses_norm": proc_norm}
