import os
import time
import threading
import logging
from typing import List, Dict
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
        self.cached_invoices: List[Dict] = []
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
            # --- Domain infók lekérése ---
            domainek = self.client.get_domains_info()

            if not domainek:
                # Ha a lekérés üres/hibás eredményt adott (pl. átmeneti parse hiba),
                # NEM töröljük a meglévő cache-t - inkább megtartjuk a régi adatokat.
                logger.warning("A domain lista lekérése üres eredményt adott - a meglévő cache-elt adatok megmaradnak.")
                with self.lock:
                    self.last_scrape_success = 0
                return

            # --- Számlák lekérése ---
            try:
                szamlak = self.client.get_invoices()
                logger.info(f"Számlák sikeresen lekérve ({len(szamlak)} db).")
            except Exception as inv_err:
                logger.error(f"Számlák letöltési hibája (marad a cache): {inv_err}")
                szamlak = self.cached_invoices  # Hiba esetén megtartjuk a régit

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
                self.cached_invoices = szamlak
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
            szamlak = list(self.cached_invoices)
            last_scrape_success = self.last_scrape_success
            last_scrape_time = self.last_scrape_time
            refreshing = self.refresh_in_progress

        age = time.time() - last_scrape_time if last_scrape_time else -1
        logger.info(
            f"Metrikák kiszolgálása a cache-ből (kor: {age:.0f}s, "
            f"utolsó frissítés sikeres: {bool(last_scrape_success)}, frissítés folyamatban: {refreshing})"
        )

        # --- AGGREGÁCIÓ ---
        # Összesítjük az adatokat valuta szerint (HUF, EUR)
        stats = {} 
        for inv in szamlak:
            curr = inv['currency']
            if curr not in stats:
                stats[curr] = {'paid_count': 0, 'unpaid_count': 0, 'paid_sum': 0.0, 'unpaid_sum': 0.0}
            
            if inv['is_paid']:
                stats[curr]['paid_count'] += 1
                stats[curr]['paid_sum'] += inv['amount']
            else:
                stats[curr]['unpaid_count'] += 1
                stats[curr]['unpaid_sum'] += inv['amount']

        if stats:
            logger.info(f"Számla metrikák generálva ({len(szamlak)} db összesen)")
        else:
            logger.info("Számla metrikák generálva: nincs számla adat a cache-ben.")

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
        dns_record_metric = GaugeMetricFamily(
            'forpsi_domain_dns_record',
            'DNS records configured in Forpsi DNS zone management',
            labels=['domain', 'hostname', 'type', 'value', 'ttl']
        )
        domains_total_metric = GaugeMetricFamily(
            'forpsi_domains_total',
            'Total number of domains in the Forpsi account'
        )
        dns_records_total_metric = GaugeMetricFamily(
            'forpsi_domain_dns_records_total',
            'Total number of DNS records for a given domain',
            labels=['domain', 'domain_id']
        )

        # --- SZÁMLA METRIKÁK ---       
        invoice_status_metric = GaugeMetricFamily(
            'forpsi_invoice_paid_status',
            '1 if the invoice is PAID, 0 if UNPAID',
            labels=['service_type', 'service_name', 'service_code', 'proforma_id', 'tax_id', 'issue_date', 'payment_date']
        )
        invoice_amount_metric = GaugeMetricFamily(
            'forpsi_invoice_amount',
            'Amount of the invoice',
            labels=['service_type', 'service_name', 'service_code', 'proforma_id', 'currency', 'status']
        )
        invoice_count_metric = GaugeMetricFamily(
            'forpsi_invoices_total',
            'Number of invoices by status and currency',
            labels=['currency', 'status']
        )
        invoice_sum_metric = GaugeMetricFamily(
            'forpsi_invoices_amount_total',
            'Total amount of invoices by status and currency',
            labels=['currency', 'status']
        )
        # -----------------------------
        
        scrape_success_metric = GaugeMetricFamily(
            'forpsi_scrape_success',
            '1 if the last scrape to Forpsi admin was successful, 0 otherwise'
        )
        refresh_in_progress_metric = GaugeMetricFamily(
            'forpsi_exporter_refresh_in_progress',
            '1 if a background refresh is currently running, 0 otherwise'
        )
        cache_age_metric = GaugeMetricFamily(
            'forpsi_exporter_cache_age_seconds',
            'Age in seconds of the currently served cached data'
        )

        # 1. Teljes domain szám beállítása
        domains_total_metric.add_metric([], len(domainek))

        # --- DOMAIN CIKLUS ---
        for d in domainek:
            expiry_days_metric.add_metric(
                [d['domain'], str(d['id']), d['expiry_date'], d['nameservers']],
                d['days_remaining']
            )

            status_value = 1.0 if d.get('is_active', False) else 0.0
            status_metric.add_metric(
                [d['domain'], str(d['id']), d['label'], d['status_text'], d['nameservers']],
                status_value
            )

            # 2. DNS rekordok száma az adott domainhez
            dns_records = d.get('dns_records', [])
            dns_records_total_metric.add_metric([d['domain'], str(d['id'])], len(dns_records))
            
            # DNS rekordok részletezése
            for r in dns_records:
                dns_record_metric.add_metric(
                    [d['domain'], r['hostname'], r['type'], r['value'], r['ttl']],
                    1.0 
                )

        # --- SZÁMLA CIKLUS ---
        for inv in szamlak:
            invoice_status_metric.add_metric(
                [
                    inv['service_type'], 
                    inv['service_name'],  # ÚJ MEZŐ
                    inv['service_code'],  # ÚJ MEZŐ
                    inv['proforma_id'], 
                    inv['tax_id'], 
                    inv['issue_date'], 
                    inv['payment_date']
                ],
                1.0 if inv['is_paid'] else 0.0
            )
            
            invoice_amount_metric.add_metric(
                [
                    inv['service_type'], 
                    inv['service_name'],  # ÚJ MEZŐ
                    inv['service_code'],  # ÚJ MEZŐ
                    inv['proforma_id'], 
                    inv['currency'], 
                    inv['status_text']
                ],
                inv['amount']
            )

        # --- METRIKÁK FELTÖLTÉSE ---
        for curr, data in stats.items():
            # Paid metrikák
            invoice_count_metric.add_metric([curr, 'PAID'], data['paid_count'])
            invoice_sum_metric.add_metric([curr, 'PAID'], data['paid_sum'])
            
            # Unpaid metrikák
            invoice_count_metric.add_metric([curr, 'UNPAID'], data['unpaid_count'])
            invoice_sum_metric.add_metric([curr, 'UNPAID'], data['unpaid_sum'])

        scrape_success_metric.add_metric([], last_scrape_success)
        refresh_in_progress_metric.add_metric([], 1.0 if refreshing else 0.0)
        cache_age_metric.add_metric([], age if age >= 0 else -1.0)

        yield expiry_days_metric
        yield status_metric
        yield dns_record_metric
        yield dns_records_total_metric
        yield domains_total_metric
        yield invoice_status_metric
        yield invoice_count_metric
        yield invoice_amount_metric
        yield invoice_sum_metric
        yield scrape_success_metric
        yield refresh_in_progress_metric
        yield cache_age_metric
