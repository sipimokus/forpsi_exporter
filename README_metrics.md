# Forpsi Prometheus Exporter - Metrics

Metrics are available at:
```
http://localhost:9123/metrics
```


### Domain metrics

#### `forpsi_domain_expiry_days`

Days remaining until domain expiration.

Example:

```text
forpsi_domain_expiry_days{
  domain="example.hu",
  expiry_date="2027-01-01"
} 180
```

#### `forpsi_domain_status`

Current domain registration status.

Values:

- `1` - active / OK
- `0` - warning or non-active state

Additional information is available through labels:

- domain
- domain_id
- label
- status_text
- nameservers

#### `forpsi_domain_dns_record`

Exports DNS records configured in Forpsi.

Supported record types include:

- A
- AAAA
- CNAME
- MX
- TXT
- SRV

Labels:

- domain
- hostname
- type
- value
- ttl


## Exporter health metrics

The exporter also provides:

| Metric | Description |
|---|---|
| `forpsi_scrape_success` | Last Forpsi refresh result (`1` = success) |
| `forpsi_exporter_refresh_in_progress` | Background refresh status |
| `forpsi_exporter_cache_age_seconds` | Age of currently served cached data |

Standard Python process metrics are also available:

- `process_cpu_seconds_total`
- `process_resident_memory_bytes`
- `process_virtual_memory_bytes`
- `process_open_fds`
- `python_gc_*`



## Grafana Dashboard

A ready-to-import Grafana dashboard is included:

```
grafana/forpsi-exporter-dashboard.json
```

The dashboard provides:

- domain expiration overview
- domains close to expiration
- domain status overview
- DNS record count
- exporter health
- cache freshness
- resource usage

Import:

1. Open **Grafana → Dashboards → Import**
2. Upload `forpsi-exporter-dashboard.json`
3. Select your Prometheus datasource
