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
