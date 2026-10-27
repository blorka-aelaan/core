"""CORE training — kendi-kendine eğitim motoru.

Journal'dan toplanan (sinyal_vektörü, komut_idx, ödül) tripleleriyle
MLP'yi tekrarlayan (batch) eğitir. Door/ağ mesajları da eğitim
girdisi olarak kullanılır; komut artık el ile yazılmıyor, öğreniliyor.

Çalışma şekli:
  1. main.py, ust.sec() çağrısında (sinyal, komut, kaynak) bilgisini
     'ust_beyn_sec' olarak journal'a yazar.
  2. Komut uygulandığında 'kullan' kaydıyla ödül gelir.
  3. SelfTrainer journal'ı okur, (sinyal, komut_idx, ödül) tripleleri
     derler ve MLP'yi tekrar tekrar eğitir (batch epochs).
  4. Door mesajları journal'da 'door_inbox' olarak kalır; sonraki
     sec() çağrısı sinyalde bu bağlamı içerdiği zaman AI,
     door mesajına göre komut seçmeyi öğrenir.
"""
import json
import threading
import time
import numpy as np
from pathlib import Path


class SelfTrainer:
    """Journal tabanlı kendi-kendine eğitim."""

    def __init__(self, ust, journal_path,
                 batch_size=32, epochs=3,
                 interval=30.0, min_samples=10,
                 max_samples=5000):
        self.ust = ust
        self.journal_path = Path(journal_path)
        self.batch_size = batch_size
        self.epochs = epochs
        self.interval = interval
        self.min_samples = min_samples
        self.max_samples = max_samples

        self._stop = threading.Event()
        self._thread = None
        self._offset = 0
        # Bellekteki eğitim havuzu: (sinyal_list, komut_idx, odul)
        self._samples = []
        self._cmd_to_idx = None  # main'dan set edilecek

    def set_cmd_resolver(self, resolver):
        """komut_adı -> indeks dönen callable."""
        self._cmd_to_idx = resolver

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self):
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            self.train()

    def train(self):
        """Yeni journal kayıtlarını derleyip MLP'yi eğitir."""
        new_samples = self._collect()
        if len(new_samples) < self.min_samples:
            return
        self._samples.extend(new_samples)
        if len(self._samples) > self.max_samples:
            self._samples = self._samples[-self.max_samples:]

        rng = np.random.RandomState(int(time.time()) % 2**31)
        for _ in range(self.epochs):
            rng.shuffle(self._samples)
            for i in range(0, len(self._samples), self.batch_size):
                batch = self._samples[i:i + self.batch_size]
                for x, idx, odul in batch:
                    self.ust.ogren(np.asarray(x, dtype=float), idx, odul)

    def _collect(self):
        """Journal'dan yeni (sinyal, komut_idx, ödül) örnekleri çıkarır."""
        samples = []
        if not self.journal_path.exists():
            return samples
        # Önceki sec() kararlarını ve sonraki kullan() kayıtlarını eşleştir.
        # Anahtar: (tick, komut_adı)
        sec_decision = {}   # (tick, komut) -> sinyal_vektor
        kullan_records = []  # (tick, komut, odul, dogru)

        with open(self.journal_path, "r", encoding="utf-8") as f:
            f.seek(self._offset)
            while True:
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                kind = rec.get("kind")
                tick = rec.get("t")

                if kind == "ust_beyn_sec":
                    sec_decision[(tick, rec.get("komut"))] = rec.get("sinyal")
                elif kind == "kullan":
                    kullan_records.append((tick, rec.get("komut"),
                                           rec.get("odul", 0.0),
                                           rec.get("dogru", False)))

                elif kind == "ust_ogren":
                    # Offline replay: (sinyal, komut_idx, ödül) üçlüsü.
                    _s = rec.get("sinyal")
                    _i = rec.get("idx")
                    if _s is not None and _i is not None:
                        samples.append((_s, _i, rec.get("odul", 0.0)))


            self._offset = f.tell()

        # Eşleştir: aynı komut adına sahip sec+kullan çiftleri
        used_keys = set()
        for tick, komut, odul, dogru in kullan_records:
            idx = self._cmd_to_idx(komut) if self._cmd_to_idx else None
            if idx is None:
                continue
            # En yakın sec() kararını bul (aynı komut, aynı tick civarı)
            best_key = None
            best_dist = float("inf")
            for key in sec_decision:
                if key in used_keys:
                    continue
                if key[1] == komut:
                    dist = abs(key[0] - tick)
                    if dist < best_dist:
                        best_dist = dist
                        best_key = key
            if best_key is not None and best_dist < 10.0:  # 10 saniye pencere
                used_keys.add(best_key)
                sinyal = sec_decision[best_key]
                if sinyal is not None:
                    samples.append((sinyal, idx, odul))

        return samples

    def stats(self):
        return {
            "samples": len(self._samples),
            "offset": self._offset,
        }