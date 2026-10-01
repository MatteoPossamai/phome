# phome — phone home server

Guides and scripts for turning an old Android phone into a home server using
Termux, OpenSSH and Tailscale, with remote access through `ssh phone`.

The phone runs services independently. Routine deployment from this repository:

```sh
python scripts/deploy-monitoring
```

See [Operations](docs/operations.md) for what runs where, startup/recovery,
deployment and remaining checks. Initial phone setup uses the guides below.

**Continuing with another agent? Read [the handover](docs/handover.md)** for the
current installed state, Grafana incident/mitigation, tested results and next steps.

- [Setup guide](docs/setup.md): reproducible installation and verification.
- [SSH boot script](scripts/start-sshd): automatic startup through Termux:Boot.
- [Monitoring](docs/monitoring.md): five-second phone metrics, Grafana, scheduled commands, deployment and seven-day retention.
- [Repository instructions](AGENTS.md): scope and conventions for future work.
- [Android access](docs/android-access.md): ADB pairing, Termux permissions and system memory diagnostics.

Monitoring samples every five seconds and retains seven days. SSH is supervised
by runit; the phone scheduler also ensures it is up every 30 seconds. Grafana
includes top-row RAM stats and memory use by monitoring service. `CLAUDE.md`
links to `AGENTS.md` so repository instructions have one source.

Further memory cleanup is paused. Next: smart-plug charging, then app hosting;
those features are not implemented yet.
