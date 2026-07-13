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

    def get_domains_info(self) -> List[Dict[str, any]]:
        self._authenticate()
        
        try:
            response = self.session.get(f"{self.base_url}/domain/domains-list.php")
            if response.status_code != 200:
                raise RuntimeError(f"Nem sikerült letölteni a listát: {response.status_code}")
            
            pattern = (
                r'id=(\d+)&amp;[^>]*>([^<]+)</a>'
                r'.*?class="group_label[^>]*>([^<]+)</div>'
                r'.*?<td[^>]*>(.*?)</td>'
                r'.*?<td>(.*?)</td>'
                r'.*?<strong>(.*?)</strong>'
            )
            
            matches = re.findall(pattern, response.text, re.DOTALL)
            parsed_domains = []
            
            today = date.today()

            for d_id, d_name, label, status, ns, expiry in matches:
                # Dátum formázás yyyy-mm-dd alakra
                date_parts = [p.strip() for p in expiry.split('.') if p.strip()]
                formatted_date = "unknown"
                days_remaining = -1
                
                if len(date_parts) == 3:
                    formatted_date = f"{date_parts[0]}-{date_parts[1]}-{date_parts[2]}"
                    expiry_date_obj = date(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
                    days_remaining = (expiry_date_obj - today).days

                # Státusz tisztítás
                clean_status = status.replace('<br>', ' ').replace('<br/>', ' ').strip()
                clean_status = re.sub(r'\s+', ' ', clean_status)
                clean_label = label.strip()

                # Névszerverek tisztítása és összefűzése
                ns_clean = ns.replace('<br/>', '<br>')
                ns_list = [item.strip() for item in ns_clean.split('<br>') if item.strip()]
                nameservers_str = ",".join(ns_list)

                # --- MULTILANG STÁTUSZ ELLENŐRZÉS ---
                # A képen látható, hogy a cseh nyelvű verzióban a label "OK", a szöveg "v pořádku".
                # Itt egyszerre vizsgáljuk a magyar, angol és cseh kulcsszavakat.
                is_active = (
                    clean_label.upper() in ["AKTÍV", "ACTIVE", "OK"] or 
                    "v pořádku" in clean_status.lower()
                )

                parsed_domains.append({
                    "id": int(d_id),
                    "domain": d_name.strip(),
                    "label": clean_label,
                    "status_text": clean_status,
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
        Lekéri a megadott domain azonosítóhoz tartozó DNS rekordokat HTML parsolással.
        """
        if not self._authenticated:
            self.login()
            
        url = f"{self.base_url}/domain/domains-dns.php?id={domain_id}"
        logger.info(f"DNS rekordok letöltése innen: {url}")

        response = self.session.get(url)
        if response.status_code != 200:
            logger.error(f"Nem sikerült letölteni a DNS oldat az alábbi ID-hoz: {domain_id}")
            return []
            
        html = response.text
        records = []

        # 1. Kettévágjuk a HTML-t a táblázat sorai mentén, így biztonságosabb dolgozni
        # Csak azokat a sorokat nézzük, amik az 'editable' osztályba tartoznak
        rows = re.findall(r'<tr[^>]*class="[^"]*editable[^"]*".*?>.*?</tr>', html, re.DOTALL | re.IGNORECASE)

        for row in rows:
            # Kigyűjtjük a soron belüli összes cellát (<td>...</td>)
            # Elsősorban a 'title' attribútumból dolgozunk, mert a Forpsi ott tárolja a teljes, vágatlan értéket!
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
            
            if len(cells) >= 4:
                # Segédfüggvény a title="..." vagy a tiszta belső szöveg kinyerésére
                def get_clean_value(cell_html):
                    title_match = re.search(r'title="([^"]+)"', cell_html, re.IGNORECASE)
                    if title_match:
                        return title_match.group(1).strip()
                    # Ha nincs title, kipucoljuk a HTML tageket és entitásokat
                    text_only = re.sub(r'<[^>]+>', '', cell_html)
                    return text_only.replace('&nbsp;', ' ').strip()

                hostname = get_clean_value(cells[0])
                ttl = get_clean_value(cells[1])
                rtype = get_clean_value(cells[2])
                value = get_clean_value(cells[3])

                # --- SRV REKORDOK TISZTÍTÁSA (MULTILANG) ---
                if rtype.upper() == 'SRV':
                    # Töröljük a címkéket (betűk, ékezetes magyar/cseh karakterek, amiket kettőspont követ)
                    val_clean = re.sub(r'[a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰěščřžýáíéóúůďťňĚŠČŘŽÝÁÍÉÓÚŮĎŤŇ]+:\s*', '', value)
                    # A megmaradt vesszőket szóközre cseréljük
                    val_clean = val_clean.replace(',', ' ')
                    # Eltávolítjuk a felesleges dupla szóközöket, így egy tiszta "weight port target" stringet kapunk
                    value = re.sub(r'\s+', ' ', val_clean).strip()

                records.append({
                    'hostname': hostname,
                    'ttl': ttl,
                    'type': rtype,
                    'value': value
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
