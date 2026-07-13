# Forpsi Prometheus Exporter

Ez az alkalmazás a Forpsi adminisztrációs felületéről gyűjt adatokat (domainek állapota, lejárati idő, DNS rekordok), majd Prometheus metrikákként teszi elérhetővé azokat.

## Funkciók
* **Aszinkron frissítés:** A hálózati kérések a háttérben futnak, így a `/metrics` végpont sosem kap timeoutot.
* **Konfigurálható:** ENV változókkal testreszabható (port, frissítési gyakoriság).
* **Docker-ready:** Könnyen konténerizálható és futtatható.

## Konfiguráció
Hozz létre egy `.env` fájlt a gyökérkönyvtárban az alábbi mintával:

```env
LOGGING_LEVEL=INFO
FORPSI_USER=felhasználónév
FORPSI_PASS=jelszó
FORPSI_SITE=admin.forpsi.hu
EXPORTER_PORT=9123
CACHE_TTL=3600
```


## Futtatás Dockerrel
Buildelés:
`docker build -t forpsi-exporter .`

Futtatás:
```
docker run -d \
  --name forpsi-exporter \
  -p 9123:9123 \
  --env-file .env \
  forpsi-exporter
```