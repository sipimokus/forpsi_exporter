# Forpsi Prometheus Exporter - Metrics

Metrics are available at:

```text
http://localhost:9123/metrics
```

The exporter exposes Forpsi domain, DNS, invoice and exporter health metrics in Prometheus format.

---

# Domain metrics

## `forpsi_domains_total`

Total number of domains available in the Forpsi account.

Example:

```text
forpsi_domains_total 5
```

---

## `forpsi_domain_expiry_days`

Number of days remaining until domain expiration.

Labels:

- `domain`
- `domain_id`
- `expiry_date`
- `nameservers`

Example:

```text
forpsi_domain_expiry_days{
  domain="example.hu",
  domain_id="123456",
  expiry_date="2027-01-01",
  nameservers="ns.forpsi.cz,ns.forpsi.it"
} 180
```

---

## `forpsi_domain_status`

Current domain registration status.

Values:

- `1` - active / OK
- `0` - warning or non-active state

Labels:

- `domain`
- `domain_id`
- `label`
- `status_text`
- `nameservers`

Example:

```text
forpsi_domain_status{
  domain="example.hu",
  domain_id="123456",
  label="ACTIVE",
  status_text="Registered, OK",
  nameservers="ns.forpsi.cz,ns.forpsi.it"
} 1
```

---

## `forpsi_domain_dns_record`

Exports DNS records configured in Forpsi DNS management.

Supported record types:

- A
- AAAA
- CNAME
- MX
- TXT
- SRV

Labels:

- `domain`
- `hostname`
- `type`
- `value`
- `ttl`

Example:

```text
forpsi_domain_dns_record{
  domain="example.hu",
  hostname="www.example.hu",
  type="A",
  value="192.0.2.10",
  ttl="600"
} 1
```

---

## `forpsi_domain_dns_records_total`

Total number of DNS records configured for each domain.

Labels:

- `domain`
- `domain_id`

Example:

```text
forpsi_domain_dns_records_total{
  domain="example.hu",
  domain_id="123456"
} 10
```

---

# Invoice metrics

## `forpsi_invoices_total`

Number of invoices grouped by status and currency.

Labels:

- `currency`
- `status`

Statuses:

- `PAID`
- `UNPAID`

Example:

```text
forpsi_invoices_total{
  currency="HUF",
  status="PAID"
} 20
```

---

## `forpsi_invoice_paid_status`

Invoice payment status.

Values:

- `1` - paid
- `0` - unpaid

Labels:

- `description`
- `issue_date`
- `payment_date`
- `proforma_id`
- `service_type`
- `tax_id`

Example:

```text
forpsi_invoice_paid_status{
  description="example.hu (DOMAIN)",
  issue_date="2027-01-01",
  payment_date="2027-01-02",
  proforma_id="0000000000",
  service_type="Domain",
  tax_id="PAID"
} 1
```

---

## `forpsi_invoice_amount`

Invoice amount.

Labels:

- `currency`
- `description`
- `proforma_id`
- `service_type`
- `status`

Example:

```text
forpsi_invoice_amount{
  currency="HUF",
  description="example.hu (DOMAIN)",
  proforma_id="0000000000",
  service_type="Domain",
  status="PAID"
} 2500
```

---

## `forpsi_invoices_amount_total`

Total invoice amount grouped by status and currency.

Example:

```text
forpsi_invoices_amount_total{
  currency="HUF",
  status="PAID"
} 50000
```

---

# Exporter health metrics

## `forpsi_scrape_success`

Result of the latest Forpsi data refresh.

Values:

- `1` - successful scrape
- `0` - failed scrape

Example:

```text
forpsi_scrape_success 1
```

---

## `forpsi_exporter_refresh_in_progress`

Shows whether a background refresh is currently running.

Values:

- `1` - refresh running
- `0` - idle

Example:

```text
forpsi_exporter_refresh_in_progress 0
```

---

## `forpsi_exporter_cache_age_seconds`

Age of the currently served cached data in seconds.

Example:

```text
forpsi_exporter_cache_age_seconds 30
```

---

# Python runtime metrics

The exporter also exposes standard Python Prometheus metrics.

Available metrics:

- `python_gc_objects_collected_total`
- `python_gc_objects_uncollectable_total`
- `python_gc_collections_total`
- `python_info`

Example:

```text
python_info{
  implementation="CPython",
  major="3",
  minor="11",
  patchlevel="15"
} 1
```

---

# Process metrics

Standard process metrics are available:

- `process_cpu_seconds_total`
- `process_resident_memory_bytes`
- `process_virtual_memory_bytes`
- `process_start_time_seconds`
- `process_open_fds`
- `process_max_fds`

Example:

```text
process_resident_memory_bytes 100000000
```

---

# Grafana Dashboard

A ready-to-import Grafana dashboard is included:

```text
grafana/forpsi-exporter-dashboard.json
```

The dashboard provides:

- domain expiration overview
- domains close to expiration
- domain registration status
- DNS record overview
- DNS record count per domain
- invoice status overview
- unpaid invoice alerts
- invoice totals
- exporter health
- cache freshness
- Python runtime metrics
- process resource usage

## Import

1. Open:

```text
Grafana → Dashboards → Import
```

2. Upload:

```text
forpsi-exporter-dashboard.json
```

3. Select your Prometheus datasource.

---

# Example alerts

## Domain expiring soon

```promql
forpsi_domain_expiry_days < 30
```

Triggers when a domain expires within 30 days.

---

## Unpaid invoices

```promql
forpsi_invoice_paid_status == 0
```

Triggers when unpaid invoices exist.

---

## Exporter failure

```promql
forpsi_scrape_success == 0
```

Triggers when the Forpsi refresh fails.

---

## Old cache data

```promql
forpsi_exporter_cache_age_seconds > 3600
```

Triggers when cached data is older than one hour.
