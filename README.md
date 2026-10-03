# phome — phone home server

Guides and scripts for turning an Android phone into a home server with
Termux, OpenSSH and Tailscale.

The phone runs services independently. Routine deployment from this repository:

```sh
python scripts/deploy-monitoring
```

Start with [phone setup](docs/setup.md). For daily use, see
[operations](docs/operations.md). Initial setup is separate from routine deploy.

**Continuing work? Read [the handover](docs/handover.md)** for the installed
state and open checks. It includes a detailed dated change record.

- [Setup guide](docs/setup.md): reproducible installation and verification.
- [SSH boot script](scripts/start-sshd): automatic startup through Termux:Boot.
- [Monitoring](docs/monitoring.md): metrics, Grafana, scheduled commands and configuration.
- [Charging](docs/charging.md): phone-controlled WiZ charger, with 40–80% thresholds and recovery limits.
- [Public HTTPS](docs/funnel.md): phone-hosted Tailscale Funnel setup and current verification status.
- [Telegram alerts](docs/alerting.md): Prometheus outage rules, Alertmanager and private bot setup.
- [posserver recovery copy](docs/posserver-backup.md): encrypted off-phone copy of posserver runtime config and restore steps.
- [Repository instructions](AGENTS.md): scope and conventions for future work.
- [Android access](docs/android-access.md): ADB pairing, Termux permissions and system memory diagnostics.

### Common settings

- Battery charge thresholds: `config/charging.json`.
- Scheduled command intervals and timeouts: `config/scheduler.json`.
- Scrape targets and intervals: `config/prometheus.yml`.
- Grafana access and display settings: `config/grafana.ini`.

These files are tracked defaults. Device identity, passwords and runtime state
belong under ignored `data/`; see the relevant guide before changing them.

`CLAUDE.md` links to `AGENTS.md`, the single repository instruction file.

WiZ charging control is implemented. App hosting is the next planned feature.
See the handover for current verification status.
