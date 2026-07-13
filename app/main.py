import time
import logging
from prometheus_client import start_http_server, REGISTRY

# Importáljuk a beállításokat és az osztályokat a struktúrának megfelelően
from .config import settings
from .client import ForpsiClient
from .collector import ForpsiCollector

# Logger beállítása
logging.basicConfig(level=settings.LOGGING_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    # Kliens inicializálása környezeti változókból
    client = ForpsiClient(
        admin_site=settings.FORPSI_SITE,
        username=settings.FORPSI_USER,
        password=settings.FORPSI_PASS,
    )

    # Collector regisztrálása (az időzítést a settingsből olvassuk)
    collector = ForpsiCollector(client, cache_ttl_seconds=settings.CACHE_TTL)
    REGISTRY.register(collector)

    # Szerver indítása
    start_http_server(settings.EXPORTER_PORT)
    logger.info(f"--- Forpsi Exporter elindult ---")
    logger.info(f"Logging: {settings.LOGGING_LEVEL}")
    logger.info(f"Célpont: {settings.FORPSI_SITE}")
    logger.info(f"Port: {settings.EXPORTER_PORT}")
    logger.info(f"Cache TTL: {settings.CACHE_TTL} másodperc")
    logger.info(f"URL: http://localhost:{settings.EXPORTER_PORT}/metrics")

    # Főszál életben tartása
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Leállítás folyamatban...")

if __name__ == "__main__":
    main()
