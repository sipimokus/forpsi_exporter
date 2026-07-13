# Forpsi Prometheus Exporter

A Prometheus exporter that collects information from the Forpsi administration interface and exposes it as Prometheus metrics.


> [!WARNING]
> This project is **unofficial** and is **not affiliated with, endorsed by, or supported by Forpsi**.
>
> It relies on the current structure of the Forpsi administration interface. Changes made by Forpsi may temporarily break the exporter until it is updated.
>
> 🚧 This project is under active development. Features, metrics, and compatibility may change between releases.


## Features
| Service                    | `forpsi.hu` | `forpsi.com` | `forpsi.cz` | `forpsi.sk` | `forpsi.pl` |
|----------------------------|:-----------:|:------------:|:-----------:|:-----------:|:-----------:|
| Invoices monitoring        | ✅ | ⏳ | ⏳ | ⏳ | ⏳ |
| Domains monitoring         | ✅ | ⏳ | ⏳ | ⏳ | ⏳ |
| Domains expiration dates   | ✅ | ⏳ | ⏳ | ⏳ | ⏳ |
| DNS hosting records        | ✅ | ⏳ | ⏳ | ⏳ | ⏳ |

## Planned Features
| Service                    | `forpsi.hu` | `forpsi.com` | `forpsi.cz` | `forpsi.sk` | `forpsi.pl` |
|----------------------------|:-----------:|:------------:|:-----------:|:-----------:|:-----------:|
| VPS monitoring             | 💡 | 💡 | 💡 | 💡 | 💡 |
| Webhosting monitoring      | 💡 | 💡 | 💡 | 💡 | 💡 |
| WebBuilder monitoring      | 💡 | 💡 | 💡 | 💡 | 💡 |
| Mail service monitoring    | 💡 | 💡 | 💡 | 💡 | 💡 |
| SSL certificate monitoring | 💡 | 💡 | 💡 | 💡 | 💡 |

**Legend**
- ✅ Supported and tested
- ⏳ Planned / not tested yet
- 💡 Planned for future releases
- ❌ Not supported

The Forpsi platforms are expected to be similar, but differences in localization, HTML structure, or available features may require additional adjustments.

## Configuration

The exporter is configured using environment variables.

| Variable | Description | Default |
|---|---|---|
| `LOGGING_LEVEL` | Application log level | `INFO` |
| `FORPSI_USER` | Forpsi account username | - |
| `FORPSI_PASS` | Forpsi account password | - |
| `FORPSI_SITE` | Forpsi admin hostname | `admin.forpsi.hu` |
| `EXPORTER_PORT` | Metrics HTTP port | `9123` |
| `CACHE_TTL` | Background refresh interval in seconds | `3600` |

You can either provide them directly through your container runtime or create a `.env` file and reference it using `--env-file` or Docker Compose.

## Docker

A pre-built container image is available on GitHub Container Registry:

```bash
docker pull ghcr.io/sipimokus/forpsi_exporter:latest
```

Run the exporter:

```bash
docker run -d \
  --name forpsi_exporter \
  -p 9123:9123 \
  --env-file .env \
  ghcr.io/sipimokus/forpsi_exporter:latest
```

## Docker Compose

```yaml
services:
  forpsi-exporter:
    image: ghcr.io/sipimokus/forpsi_exporter:latest
    container_name: forpsi-exporter
    restart: unless-stopped
    env_file:
      - .env
    ports:
      - "9123:9123"
```

## Metrics

See [README_metrics.md](README_metrics.md) for dashboard usage, available panels, and metric reference.

### Prometheus

Metrics are available at:

```
http://localhost:9123/metrics
```


## Grafana Dashboard

A ready-to-import Grafana dashboard is included:

```
grafana/forpsi-exporter-dashboard.json
```

## Prometheus configuration example

```yaml
scrape_configs:
  - job_name: forpsi_exporter
    static_configs:
      - targets:
          - localhost:9123
```


## Security

The exporter requires your Forpsi account credentials to access the administration interface.

Credentials are used only for authentication and are never exposed as Prometheus metrics or logs.


## License

This project is licensed under the MIT License. See the `LICENSE` file for details.


## Acknowledgements

This project was inspired by [certbot-dns-forpsi](https://github.com/roshek/certbot-dns-forpsi) and [domain_exporter](https://github.com/caarlos0/domain_exporter).

The initial implementation was developed with the assistance of AI tools and was manually reviewed, tested, and adapted.
