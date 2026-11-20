"""Regression coverage for periodic lifecycle journal archiving."""
import tempfile
from pathlib import Path
from types import SimpleNamespace

import journal
from lifecycle import LifecycleManager


def test_periodic_archiving_uses_journal_module_api():
    with tempfile.TemporaryDirectory(prefix="core_lifecycle_archive_") as tmp:
        root = Path(tmp)
        journal_path = root / "journal.jsonl"
        shadow_path = root / "golge_log.jsonl"
        journal_path.write_text('{"kind":"act"}\n', encoding="utf-8")
        shadow_path.write_text('{"kind":"command"}\n', encoding="utf-8")

        manager = LifecycleManager.__new__(LifecycleManager)
        manager.journal = journal.Journal(journal_path, quiet=True)
        manager.golge_yolu = str(shadow_path)
        manager.journal_azami_mb = 0
        manager.golge_azami_mb = 0
        manager.arsivle_gunlukler(200, None)
        assert journal_path.exists()
        assert shadow_path.exists()

        manager.journal_azami_mb = 0.000001
        manager.golge_azami_mb = 0.000001
        manager.arsivle_gunlukler(200, None)

        archive_dir = root / "arsiv"
        archived = sorted(p.name for p in archive_dir.iterdir())
        assert len(archived) == 2, archived
        assert any(name.startswith("journal_") for name in archived), archived
        assert any(name.startswith("golge_log_") for name in archived), archived
        assert journal_path.exists()
        assert not shadow_path.exists()
        assert "journal_arsiv" in journal_path.read_text(encoding="utf-8")
        assert "golge_arsiv" in journal_path.read_text(encoding="utf-8")
        with shadow_path.open("a", encoding="utf-8") as shadow:
            shadow.write('{"kind":"continued"}\n')
        assert shadow_path.exists()


if __name__ == "__main__":
    test_periodic_archiving_uses_journal_module_api()
    print("Lifecycle periodic journal archiving OK")
