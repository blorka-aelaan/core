# Systemd Servis Kurulumu

Organizma ve ag gözlemcisi makine restart'ından sonra otomatik başlasın.

## Kurulum

```bash
# Servis dosyalarını systemd'ye kopyala
sudo cp core-ag.service /etc/systemd/system/
sudo cp core.service    /etc/systemd/system/

# systemd'yi yenile
sudo systemctl daemon-reload

# İlk başlatma
sudo systemctl start core-ag    # ag gözlemcisi (root gerektirir)
sudo systemctl start core       # organizma (emrah kullanıcısı)

# Her boot'ta otomatik başlat
sudo systemctl enable core-ag
sudo systemctl enable core
```

## İzleme

```bash
# Canlı log (organizma)
journalctl -u core -f

# Canlı log (ag gözlemcisi)
journalctl -u core-ag -f

# Durum
systemctl status core
systemctl status core-ag

# Organizma kapısını izle
python3 door.py watch
python3 door.py send status   # anlık durum (JSON)
```

## Token Güvenliği (isteğe bağlı)

Kapı token'ını ortam değişkeniyle ilet — body.json'a yazma:

```bash
# /home/emrah/Genel/core/.env dosyası oluştur
echo "CORE_TOKEN=gizlisifre" > /home/emrah/Genel/core/.env
chmod 600 /home/emrah/Genel/core/.env

# core.service içindeki şu satırın başındaki # işaretini kaldır:
# EnvironmentFile=/home/emrah/Genel/core/.env
sudo systemctl daemon-reload
sudo systemctl restart core
```

## Durdurma / Yeniden Başlatma

```bash
sudo systemctl restart core     # organizmayı yeniden başlat
sudo systemctl stop core        # uyku moduna al (Ctrl+C = SIGINT)
sudo systemctl stop core-ag     # ag gözlemcisini durdur
```
