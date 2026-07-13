import os
import time
import threading
import logging
from prometheus_client.core import GaugeMetricFamily
from app.client import ForpsiClient

logger = logging.getLogger(__name__)


class ForpsiCollector(object):
    """
    Egyedi Prometheus Collector, amely a Forpsi adatokat egy /metrics
    lekérdezés által kiváltott háttérszálon, aszinkron módon frissíti.
    NINCS automatikus/időzített (interval alapú) frissítés: csak akkor indul
    új lekérés, ha lejárt a cache_ttl ÉS jön egy /metrics hívás. A collect()
    metódus SOHA nem végez hálózati hívást és sosem várja meg a frissítést,
    mindig azonnal a legutóbb sikeresen lekért (cache-elt) adatokat adja
    vissza -> a /metrics lekérdezés nem tud timeoutolni a Forpsi felé
    irányuló lassú kérések miatt.
    """
    def __init__(self, client: ForpsiClient, cache_ttl_seconds: int = 300):
        self.client = client
        self.cache_ttl = cache_ttl_seconds

        self.lock = threading.Lock()
        self.cached_domains: List[Dict] = []
        self.last_scrape_time = 0.0
        self.last_scrape_success = 0  # amíg nincs első sikeres frissítés, 0
        self.refresh_in_progress = False

    def _maybe_trigger_refresh(self) -> None:
        """
        Csak akkor indít háttérfrissítést, ha:
          - lejárt a cache (vagy még sosem volt sikeres frissítés), ÉS
          - épp nem fut már egy másik frissítés a háttérben.
        NINCS automatikus/időzített frissítés - kizárólag egy /metrics
        lekérdezés válthatja ki, de maga a collect() sosem várja meg.
        """
        with self.lock:
            now = time.time()
            cache_expired = (now - self.last_scrape_time) >= self.cache_ttl
            if not cache_expired or self.refresh_in_progress:
                return
            self.refresh_in_progress = True

        thread = threading.Thread(
            target=self._background_refresh,
            name="forpsi-refresh",
            daemon=True,
        )
        thread.start()

    def _background_refresh(self) -> None:
        try:
            self._refresh_once()
        finally:
            with self.lock:
                self.refresh_in_progress = False

    def _refresh_once(self) -> None:
        logger.info("Háttérfrissítés indítása a Forpsiról (metrics lekérdezés váltotta ki)...")
        try:
            # 1. Alap domain infók lekérése
            domainek = self.client.get_domains_info()

            if not domainek:
                # Ha a lekérés üres/hibás eredményt adott (pl. átmeneti parse hiba),
                # NEM töröljük a meglévő cache-t - inkább megtartjuk a régi adatokat.
                logger.warning("A domain lista lekérése üres eredményt adott - a meglévő cache-elt adatok megmaradnak.")
                with self.lock:
                    self.last_scrape_success = 0
                return

            # Az előző cache-ből kinyerjük az egyes domainekhez tartozó, korábban
            # már lekért DNS rekordokat, hogy frissítés közben NE tűnjenek el
            # (ne látszódjon "nulláról töltődik" a lista), amíg az újak be nem érnek.
            with self.lock:
                old_dns_by_id = {d['id']: d.get('dns_records', []) for d in self.cached_domains}

            for d in domainek:
                d['dns_records'] = old_dns_by_id.get(d['id'], [])

            # Publikáljuk a cache-be -> a /metrics már ezután rögtön látja a
            # friss domain listát (expiry/status), a DNS rekordok pedig egyelőre
            # a korábbi (még érvényes) értékeket mutatják, amíg felül nem íródnak.
            with self.lock:
                self.cached_domains = domainek
                self.last_scrape_time = time.time()
                self.last_scrape_success = 1
            logger.info(f"Domain lista publikálva a cache-be ({len(domainek)} domain, a régi DNS adatok egyelőre megtartva), a DNS rekordok frissítése folytatódik...")

            # 2. DNS rekordok lekérése (csak ha Forpsi DNS-t használ), domainenként.
            #    Minden egyes domainhez tartozó DNS rekordokat azonnal beírjuk
            #    a cache-be, amint megérkeztek -> a metrics fokozatosan frissül,
            #    nem kell megvárni az összes domain DNS-ét.
            for d in domainek:
                nameservers = d.get('nameservers', '')
                if not nameservers or 'forpsi' not in nameservers.lower():
                    continue
                try:
                    dns_records = self.client.get_dns_records(d['id'])
                    logger.info(f"Sikeresen beolvasva {len(dns_records)} db DNS rekord a(z) {d['domain']} domainhez.")
                except Exception as dns_err:
                    logger.error(f"Hiba a(z) {d['domain']} DNS rekordjainak lekérése közben: {dns_err} - a korábbi DNS adatok megmaradnak ennél a domainnél.")
                    continue

                with self.lock:
                    # Megkeressük a domaint az AKTUÁLIS cache-ben (elképzelhető, hogy
                    # időközben már egy új teljes lista is publikálódott, ilyenkor
                    # csak akkor írjuk be, ha a domain még mindig szerepel benne)
                    for cached_d in self.cached_domains:
                        if cached_d['id'] == d['id']:
                            cached_d['dns_records'] = dns_records
                            break

            with self.lock:
                self.last_scrape_time = time.time()
            logger.info("Minden DNS adat sikeresen frissítve és elmentve a cache-be (háttérszál).")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Hiba történt a háttérfrissítés közben: {e}")
            
            # Ha a hiba tartalmazza a kulcsszót, leállítjuk az egész appot
            if "login" in error_msg.lower() or "hitelesítési" in error_msg.lower():
                logger.critical("Kritikus hiba: Hitelesítési probléma. Az alkalmazás leáll.")
                os._exit(1)  # Az egész processz azonnali leállítása
            
            self.client._authenticated = False
            with self.lock:
                self.last_scrape_success = 0
            # A régi cache-elt adatokat megtartjuk, nem töröljük

    def collect(self):
        # Ha kellene, elindítunk egy háttérfrissítést - ez a hívás azonnal visszatér,
        # NEM várja meg a frissítés végét.
        self._maybe_trigger_refresh()

        # Csak olvasunk a cache-ből, hálózati hívás itt SOHA nem történik
        with self.lock:
            domainek = list(self.cached_domains)
            last_scrape_success = self.last_scrape_success
            last_scrape_time = self.last_scrape_time
            refreshing = self.refresh_in_progress

        age = time.time() - last_scrape_time if last_scrape_time else -1
        logger.info(
            f"Metrikák kiszolgálása a cache-ből (kor: {age:.0f}s, "
            f"utolsó frissítés sikeres: {bool(last_scrape_success)}, frissítés folyamatban: {refreshing})"
        )

        # === METRIKÁK GENERÁLÁSA ===
        expiry_days_metric = GaugeMetricFamily(
            'forpsi_domain_expiry_days', 
            'Days remaining until the domain expires', 
            labels=['domain', 'domain_id', 'expiry_date', 'nameservers']
        )
        status_metric = GaugeMetricFamily(
            'forpsi_domain_status', 
            'Status of the domain (1 = AKTÍV/OK, 0 = egyéb)', 
            labels=['domain', 'domain_id', 'label', 'status_text', 'nameservers']
        )
        # ÚJ: DNS rekord metrika család (Info minta)
        dns_record_metric = GaugeMetricFamily(
            'forpsi_domain_dns_record',
            'DNS records configured in Forpsi DNS zone management',
            labels=['domain', 'hostname', 'type', 'value', 'ttl']
        )
        
        scrape_success_metric = GaugeMetricFamily(
            'forpsi_scrape_success',
            '1 if the last scrape to Forpsi admin was successful, 0 otherwise'
        )

        # ÚJ: exporter állapot metrika - mutatja, hogy fut-e éppen háttérfrissítés,
        # és milyen régi a jelenleg kiszolgált cache-elt adat.
        refresh_in_progress_metric = GaugeMetricFamily(
            'forpsi_exporter_refresh_in_progress',
            '1 if a background refresh (domain list and/or DNS records) is currently running, 0 if data is idle/fresh'
        )
        cache_age_metric = GaugeMetricFamily(
            'forpsi_exporter_cache_age_seconds',
            'Age in seconds of the currently served cached data (time since last successful (partial) update)'
        )

        for d in domainek:
            expiry_days_metric.add_metric(
                [d['domain'], str(d['id']), d['expiry_date'], d['nameservers']],
                d['days_remaining']
            )
            status_value = 1.0 if d['label'] == "AKTÍV" else 0.0
            status_metric.add_metric(
                [d['domain'], str(d['id']), d['label'], d['status_text'], d['nameservers']],
                status_value
            )
            
            # ÚJ: DNS rekordok hozzáfűzése a metrikákhoz
            for r in d.get('dns_records', []):
                dns_record_metric.add_metric(
                    [d['domain'], r['hostname'], r['type'], r['value'], r['ttl']],
                    1.0  # Fix érték, a lényeg a label állományban van
                )
            
        scrape_success_metric.add_metric([], last_scrape_success)
        refresh_in_progress_metric.add_metric([], 1.0 if refreshing else 0.0)
        cache_age_metric.add_metric([], age if age >= 0 else -1.0)

        yield expiry_days_metric
        yield status_metric
        yield dns_record_metric  # ÚJ
        yield scrape_success_metric
        yield refresh_in_progress_metric  # ÚJ
        yield cache_age_metric  # ÚJ
