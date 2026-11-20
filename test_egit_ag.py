"""Verified task-context filtering for AG replay."""
from egit_ag import tekrar_oynat


class FakeMind:
    def __init__(self):
        self.samples = []

    def learn(self, stim, action, reward):
        self.samples.append((stim, action, reward))


def test_replay_accepts_only_verified_task_commands():
    valid = {
        "kind": "learn",
        "tick": 12,
        "hedef": "AG_TARA",
        "stim": "e:2|gorev:AG_TARA|deneme:1",
        "action": "cmd:nmap",
        "dogru": False,
        "dogrulanmis": True,
        "R": -2.25,
    }
    records = [
        valid,
        dict(valid),
        dict(valid, tick=13, hedef="BENI_TARA",
             stim="e:2|gorev:BENI_TARA", action="cmd:ss", dogru=True),
        dict(valid, dogru=None),
        dict(valid, action="help:nmap"),
        dict(valid, hedef="DOSYA_BUL"),
        dict(valid, stim="e:2|gorev:BENI_TARA"),
        dict(valid, R=True),
        dict(valid, dogrulanmis=False),
    ]
    mind = FakeMind()
    played, candidates = tekrar_oynat(mind, records)
    assert (played, candidates) == (2, 2)
    assert mind.samples == [
        (valid["stim"], "cmd:nmap", -2.25),
        ("e:2|gorev:BENI_TARA", "cmd:ss", float(valid["R"])),
    ]


if __name__ == "__main__":
    test_replay_accepts_only_verified_task_commands()
    print("AG replay task/kanıt filtresi OK")
