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
             "konum": 2, "nedir": 2, "atolye": 1}

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

    def go(self, room):
        """Niyetli hareket: seçilen odaya git ve gözle."""
        target = self.world if room == "kok" else self.world / room
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
        """Dünya dışında okuma/yazma yok (sahne kilidi)."""
        # rel None/boş olabilir (ör. yemek seçilemediğinde "eat"
        # eylemi yol bilmeden çağrılır) — patlamak yerine güvenli
        # biçimde None döner; çağıran taraf "bulunamadı" diye işler.
        if not rel:
            return None
        cand = (self.world / rel).resolve()
        rp = self._rel(cand)
        return cand if rp is not None else None

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
        return {"obs": "dinleniyor…", "kind": "rest", "novel": 0}
