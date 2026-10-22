import os
import subprocess
import json

# PATH dizinlerini al
path_dirs = os.environ.get("PATH", "").split(":")

# 1. Tüm benzersiz çalıştırılabilir komutları topla
komutlar = set()
for dizin in path_dirs:
    if os.path.isdir(dizin):
        try:
            for dosya in os.listdir(dizin):
                tam_yol = os.path.join(dizin, dosya)
                if os.path.isfile(tam_yol) and os.access(tam_yol, os.X_OK):
                    komutlar.add(dosya)
        except Exception:
            continue

komut_listesi = sorted(list(komutlar))
print(f"Toplam {len(komut_listesi)} benzersiz komut bulundu. Sınıflandırılıyor...")

# 2. Kategorizasyon kuralları (Komut adı veya açıklamasına göre)
kategoriler = {
    "Ağ ve Güvenlik (Network)": ["nmap", "ssh", "ping", "ip", "curl", "wget", "netstat", "ss", "ftp", "tcpdump", "iptables", "ufw"],
    "Sistem Yönetimi ve İzleme": ["ps", "top", "htop", "kill", "systemctl", "journalctl", "df", "du", "free", "uname", "uptime", "lsof", "chown", "chmod", "sudo"],
    "Metin ve Dosya İşleme": ["cat", "grep", "sed", "awk", "wc", "head", "tail", "find", "ls", "cp", "mv", "rm", "mkdir", "touch", "tar", "gzip", "zcat"],
    "Geliştirme ve Derleme (Dev)": ["python", "pip", "gcc", "g++", "make", "git", "perl", "lua", "dpkg", "apt"],
    "Kabuk ve Ortam Araçları": ["bash", "sh", "env", "alias", "export", "history", "clear", "sleep", "xargs", "seq"]
}

rapor = {k: [] for k in kategoriler.keys()}
rapor["Diğer / Sınıflandırılamayan"] = []

# 3. Her komutun açıklamasını al ve sınıflandır
for index, cmd in enumerate(komut_listesi):
    # whatis ile kısa açıklama al
    try:
        proc = subprocess.run(["whatis", cmd], capture_output=True, text=True, timeout=1)
        acıklama = proc.stdout.split("-")[-1].strip() if proc.returncode == 0 else "Açıklama bulunamadı."
    except Exception:
        acıklama = "Açıklama alınamadı."

    # Sınıflandırma mantığı
    yerlestirildi = False
    cmd_lower = cmd.lower()
    desc_lower = acıklama.lower()

    for kategori, anahtar_kelimeler in kategoriler.items():
        if any(kw in cmd_lower for kw in anahtar_kelimeler) or (kategori == "Ağ ve Güvenlik (Network)" and "network" in desc_lower):
            rapor[kategori].append(f"- **{cmd}**: {acıklama}")
            yerlestirildi = True
            break
    
    if not yerlestirildi:
        rapor["Diğer / Sınıflandırılamayan"].append(f"- **{cmd}**: {acıklama}")

# 4. Sonucu Markdown dosyası olarak kaydet
with open("/tmp/debian_komut_raporu.md", "w", encoding="utf-8") as f:
    f.write("# 📋 Debian Sistem Komutları Sınıflandırma Raporu\n\n")
    for kat, maddeler in rapor.items():
        f.write(f"## 📂 {kat} ({len(maddeler)} Komut)\n")
        if maddeler:
            f.write("\n".join(maddeler) + "\n")
        else:
            f.write("*Bu kategoride komut saptanmadı.*\n")
        f.write("\n" + "-"*40 + "\n\n")

print("İşlem tamamlandı! Sonuçlar '/tmp/debian_komut_raporu.md' dosyasına yazıldı.")
