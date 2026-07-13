import logging
import csv
import io
import re
import requests
from datetime import date
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)

class ForpsiClient:
    def __init__(self, admin_site: str, username: str, password: str) -> None:
        self.admin_site = admin_site
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.base_url = f"https://{admin_site}"
        self._authenticated = False

    def _authenticate(self) -> None:
        if self._authenticated:
            return

        logger.info(f"Bejelentkezés kezdeményezése a Forpsi-ra: {self.admin_site}")
        try:
            headers = {
                'Origin': f'https://{self.admin_site}',
                'Referer': f'https://{self.admin_site}/index.php',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/139.0'
            }
            
            self.session.get(f"{self.base_url}/index.php", headers=headers)

            login_data = {
                'login_action': 'client_login',
                'user_name': self.username,
                'password': self.password,
                'otp_code': ''
            }

            self.session.post(f"{self.base_url}/index.php", data=login_data, headers=headers)
            
            if not any(cookie.name == 'FAUTH' for cookie in self.session.cookies):
                raise ValueError("Sikertelen Forpsi login. Hibás hitelesítési adatok!")
                    
            logger.info("Sikeresen bejelentkezve.")
            self._authenticated = True
            
        except requests.RequestException as e:
            raise ConnectionError(f"Hálózati hiba az azonosítás során: {e}")

    def _get_domain_ids(self) -> Dict[str, int]:
        """
        A domain lista CSV exportja nem tartalmaz domain ID-t (csak a DNS
        exporthoz szükséges id=... paraméterhez kellene), ezért ezt egy
        könnyű regex-szel kiolvassuk a sima domains-list.php oldalról,
        és domain név -> id szótárrá alakítjuk.
        """
        response = self.session.get(f"{self.base_url}/domain/domains-list.php")
        if response.status_code != 200:
            raise RuntimeError(f"Nem sikerült letölteni a domain listát az ID-khez: {response.status_code}")

        pattern = r'id=(\d+)&amp;[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, response.text)
        return {name.strip(): int(d_id) for d_id, name in matches}

    def get_domains_info(self) -> List[Dict[str, any]]:
        self._authenticate()

        try:
            domain_ids = self._get_domain_ids()

            url = f"{self.base_url}/domain/domains-list-csv-export.php"
            response = self.session.get(url)
            if response.status_code != 200:
                raise RuntimeError(f"Nem sikerült letölteni a domain lista CSV exportot: {response.status_code}")

            reader = csv.reader(io.StringIO(response.text))
            rows = list(reader)

            today = date.today()
            parsed_domains = []

            for row in rows:
                if len(row) < 5:
                    continue

                label, d_name, status_text, nameservers_raw, expiry_str = [c.strip() for c in row[:5]]

                # Dátum: a CSV export már yyyy-mm-dd formátumban adja
                formatted_date = expiry_str if expiry_str else "unknown"
                days_remaining = -1
                if expiry_str:
                    try:
                        expiry_date_obj = datetime.strptime(expiry_str, '%Y-%m-%d').date()
                        days_remaining = (expiry_date_obj - today).days
                    except ValueError:
                        formatted_date = "unknown"

                # Névszerverek: szóközzel elválasztva jönnek, vesszős stringgé alakítjuk
                nameservers_str = ",".join(ns for ns in nameservers_raw.split() if ns)

                is_active = label.upper() == "OK"

                parsed_domains.append({
                    "id": domain_ids.get(d_name, 0),
                    "domain": d_name,
                    "label": label,
                    "status_text": status_text,
                    "nameservers": nameservers_str,
                    "expiry_date": formatted_date,
                    "days_remaining": days_remaining,
                    "is_active": is_active
                })

            return parsed_domains

        except requests.RequestException as e:
            raise ConnectionError(f"Hiba a domain lista letöltésekor: {e}")

    def get_dns_records(self, domain_id: int) -> list:
        """
        Lekéri a megadott domain azonosítóhoz tartozó DNS rekordokat a
        dns-edit.php CSV exportján keresztül (POST ak=export&export_type=csv).
        """
        self._authenticate()

        url = f"{self.base_url}/domain/domains-dns.php?id={domain_id}"
        logger.info(f"DNS rekordok CSV exportjának letöltése innen: {url}")

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': f"{url}&new=1",
            'Origin': f'https://{self.admin_site}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/139.0'
        }

        try:
            response = self.session.post(url, data={'ak': 'export', 'export_type': 'csv'}, headers=headers)
        except requests.RequestException as e:
            logger.error(f"Hálózati hiba a(z) {domain_id} DNS exportjának letöltésekor: {e}")
            return []

        if response.status_code != 200:
            logger.error(f"Nem sikerült letölteni a DNS exportot az alábbi ID-hoz: {domain_id} ({response.status_code})")
            return []

        reader = csv.reader(io.StringIO(response.text), delimiter=';')
        rows = list(reader)

        if not rows:
            return []

        records = []
        for row in rows[1:]:  # fejléc (Hostname;TTL;Type;Value) kihagyása
            if len(row) < 4:
                continue

            records.append({
                'hostname': row[0].strip(),
                'ttl': row[1].strip(),
                'type': row[2].strip(),
                'value': row[3].strip()
            })

        return records


    def get_invoices(self) -> List[Dict[str, any]]:
        self._authenticate()
        url = f"{self.base_url}/billing/invoices-csv-export.php"

        try:
            response = self.session.get(url)
            reader = csv.reader(io.StringIO(response.text))
            rows = list(reader)

            if not rows:
                return []

            data_rows = rows[1:]  # fejléc kihagyása

            def parse_date(value: str) -> str:
                value = value.strip()
                if not value:
                    return ''
                try:
                    return datetime.strptime(value, '%Y. %m. %d.').strftime('%Y-%m-%d')
                except ValueError:
                    return ''

            invoices = []
            for row in data_rows:
                if len(row) < 8:
                    continue

                issue_date = parse_date(row[4])
                payment_date = parse_date(row[5])
                is_paid = len(payment_date) > 0

                raw_amount = row[6].replace(',', '.').replace(' ', '')
                try:
                    amount = float(raw_amount)
                except ValueError:
                    amount = 0.0

                invoices.append({
                    'service_type': row[0].strip(),
                    'description': row[1].strip(),
                    'proforma_id': row[2].strip(),
                    'tax_id': row[3].strip(),
                    'is_paid': is_paid,
                    'status_text': 'PAID' if is_paid else 'UNPAID',
                    'amount': amount,
                    'currency': row[7].strip(),
                    'issue_date': issue_date,
                    'payment_date': payment_date
                })

            return invoices

        except Exception as e:
            logger.error(f"Hiba a CSV feldolgozásakor: {e}")
            return []
