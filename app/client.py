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

    @staticmethod
    def _looks_like_login_page(text: str) -> bool:
        """
        Azt nézi, hogy a válasz konkrétan egy LOGIN oldalnak tűnik-e
        (session lejárt -> visszairányítás az index.php login formra).
        Ezt olyan végpontoknál használjuk, amik normál esetben is HTML-t
        adnak vissza (pl. domains-list.php), ezért ott az általános
        "<html>" jelenlét nem árulkodó - a login form mezői viszont igen.
        """
        if not text or not text.strip():
            return True
        snippet = text.strip()[:2000].lower()
        login_markers = ('name="user_name"', 'name="password"', "client_login")
        return any(marker in snippet for marker in login_markers)

    @staticmethod
    def _looks_like_html(text: str) -> bool:
        """
        Azt nézi, hogy a válasz HTML-nek tűnik-e olyan végpontoknál, ahol
        KIZÁRÓLAG sima CSV/szöveg választ várunk (export végpontok). Ott
        bármilyen HTML jelenléte (login oldal, hibaoldal, stb.) azt jelenti,
        hogy valami elromlott - tipikusan lejárt szerver oldali session.
        """
        if not text or not text.strip():
            return True
        snippet = text.strip()[:1000].lower()
        html_markers = ('<!doctype', '<html', '<head', '<body', '<script')
        return any(marker in snippet for marker in html_markers)

    def _fetch_with_reauth(self, method: str, url: str, expect: str = 'csv', **kwargs) -> "requests.Response":
        """
        Elvégzi a kérést, és megkülönbözteti a kétféle hibalehetőséget:

        1. HTTP-szintű hiba (pl. 404, 500, ...) - ezt egy elgépelt URL, rossz
           domain_id, vagy szerver oldali probléma okozza. Ezen egy
           újra-bejelentkezés NEM segít, ezért ilyenkor nem is próbálkozunk
           vele - egyből hibát dobunk, hogy ne generáljunk felesleges login
           kéréseket a Forpsi felé (ami sok domain esetén könnyen rate
           limit/tiltás kockázatával járna).

        2. A válasz 200-as, de a TARTALMA login oldalnak / HTML-nek tűnik a
           várt CSV/adat helyett - ez a tényleges "lejárt szerver oldali
           session" tünete (a self._authenticated flag ugyanis csak a
           kezdeti bejelentkezéskor állítódik be, ezt közben nem érzékelnénk
           magától). Csak EBBEN az esetben próbálunk egyszer friss
           bejelentkezést, és ismételjük meg a kérést.

        expect='csv'   -> tiszta CSV/szöveg várt (export végpontok); bármilyen
                           HTML jelenléte hibának számít.
        expect='html'  -> maga a végpont is HTML-t ad normál esetben (pl.
                           domains-list.php); csak a konkrét login form
                           jelenléte számít hibának.
        """
        is_invalid_content = self._looks_like_html if expect == 'csv' else self._looks_like_login_page
        do_request = self.session.get if method == 'get' else self.session.post

        response = do_request(url, **kwargs)

        if response.status_code != 200:
            # HTTP hiba - elgépelt URL, rossz ID, szerver hiba, stb.
            # Újra-hitelesítés ezen nem segítene, ezért nem is próbáljuk.
            raise RuntimeError(
                f"HTTP hiba ({response.status_code}) a következő URL-en: {url}"
            )

        if is_invalid_content(response.text):
            logger.warning(
                f"Gyanús válasz érkezett ({url}) - a session valószínűleg lejárt, "
                f"újra-hitelesítés megkísérlése..."
            )
            self._authenticated = False
            self.session.cookies.clear()
            self._authenticate()
            response = do_request(url, **kwargs)

            if response.status_code != 200:
                raise RuntimeError(
                    f"HTTP hiba ({response.status_code}) újra-hitelesítés után a következő URL-en: {url}"
                )

            if is_invalid_content(response.text):
                raise ConnectionError(
                    f"A Forpsi nem adott vissza érvényes választ újra-hitelesítés után sem ({url}) "
                    f"- session/hitelesítési probléma."
                )

        return response

    def _get_domain_ids(self) -> Dict[str, int]:
        """
        A domain lista CSV exportja nem tartalmaz domain ID-t (csak a DNS
        exporthoz szükséges id=... paraméterhez kellene), ezért ezt egy
        könnyű regex-szel kiolvassuk a sima domains-list.php oldalról,
        és domain név -> id szótárrá alakítjuk.

        Ha a regex egyetlen egyezést sem talál (pl. mert időközben lejárt a
        session, vagy megváltozott az oldal HTML formátuma), azt NEM
        hallgatjuk el egy csendes üres dict visszaadásával - az ugyanis azt
        eredményezné, hogy MINDEN domain id=0-t kapna a get_domains_info()-ban,
        ami minden DNS exportot ugyanarra a (hibás) URL-re küldene. Helyette
        egyszer megpróbálunk friss bejelentkezéssel újra próbálkozni, és ha
        az is üres eredményt ad, hibát dobunk.
        """
        pattern = r'id=(\d+)&amp;[^>]*>([^<]+)</a>'

        def fetch_and_parse() -> Dict[str, int]:
            resp = self._fetch_with_reauth('get', f"{self.base_url}/domain/domains-list.php", expect='html')
            matches = re.findall(pattern, resp.text)
            return {name.strip(): int(d_id) for d_id, name in matches}

        domain_ids = fetch_and_parse()

        if not domain_ids:
            logger.warning(
                "A domains-list.php oldalon egyetlen domain ID sem található - "
                "session probléma vagy megváltozott oldalformátum gyanús, "
                "újra-hitelesítés megkísérlése..."
            )
            self._authenticated = False
            self.session.cookies.clear()
            self._authenticate()
            domain_ids = fetch_and_parse()

            if not domain_ids:
                raise RuntimeError(
                    "Nem sikerült domain ID-kat kinyerni a domains-list.php oldalról "
                    "újra-hitelesítés után sem - lehet, hogy megváltozott az oldal HTML "
                    "formátuma (a regex már nem illik rá)."
                )

        return domain_ids

    def get_domains_info(self) -> List[Dict[str, any]]:
        self._authenticate()

        try:
            domain_ids = self._get_domain_ids()

            url = f"{self.base_url}/domain/domains-list-csv-export.php"
            response = self._fetch_with_reauth('get', url, expect='csv')

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

            # Konzisztencia-ellenőrzés: ha VAN kinyert ID-lista (domain_ids nem
            # üres, tehát a domains-list.php oldal maga rendben volt), de a CSV
            # exportból egyetlen domain neve sem illeszkedik rá (mind id=0
            # lenne), az arra utal, hogy a két forrás domain-nevei valamiért
            # nem egyeznek (pl. whitespace, kis/nagybetű, encoding). Ezt NEM
            # publikáljuk csendben - inkább hibaként kezeljük, és megtartjuk a
            # régi (érvényes ID-jú) cache-elt adatokat.
            if domain_ids and parsed_domains and all(d['id'] == 0 for d in parsed_domains):
                raise RuntimeError(
                    "A domains-list.php-ből kinyert domain ID-k egyike sem illeszkedik "
                    "a CSV export domain neveire (minden domain id=0 lenne) - a domain "
                    "lista frissítése megszakítva, a régi cache-elt adatok megmaradnak."
                )

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

        response = self._fetch_with_reauth(
            'post', url, expect='csv',
            data={'ak': 'export', 'export_type': 'csv'}, headers=headers
        )

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
            response = self._fetch_with_reauth('get', url, expect='csv')
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
                    
                # --- Logika a description felbontására ---
                raw_description = row[1].strip()
                service_name = ""
                service_code = raw_description

                # Regex keresés: "Bármi (KÓD)" formátum
                match = re.search(r'^(.*?)\s*\(([^)]+)\)$', raw_description)
                if match:
                    service_name = match.group(1).strip()
                    service_code = match.group(2).strip()
                # --------------------------------------------

                invoices.append({
                    'service_type': row[0].strip(),
                    'description': raw_description, # Érdemes meghagyni az eredetit is, ha kellene
                    'service_name': service_name,
                    'service_code': service_code,
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
