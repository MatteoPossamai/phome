# Phone monitoring

Everything runs on the phone. Prometheus, Grafana and the HTTP exporter run in
Debian through PRoot. A small Termux collector reads Android's real battery/API
and host metrics, then shares an atomic snapshot with Debian. This collector
must run outside PRoot because PRoot can substitute synthetic `/proc` values.

## Architecture and defaults

- Android collector: samples every 5 seconds using Python and Termux:API.
- Debian exporter: `127.0.0.1:9101/metrics`; rejects snapshots older than 90 seconds.
- Prometheus: `127.0.0.1:9090`, 5-second scrapes, seven-day retention.
- Service checks: exporter, Prometheus and Grafana (`/metrics`); `up = 1` means
  Prometheus successfully scraped that service.
- Grafana: phone's Tailscale IP, port 3000; provisioned Prometheus source/dashboard.
- Runit via Termux services: starts at boot and restarts exited processes.
- Data: `~/phome/data/`; rotated service logs: `~/phome/data/logs/`.

Grafana has anonymous **Viewer** access over Tailscale so the dashboard opens
without a login. Editing requires the admin account. It listens only on the
configured Tailscale address; tailnet access rules decide who can reach it.
Prometheus and the exporter listen only on localhost.

## Install on a new phone

Complete [SSH/Tailscale setup](setup.md) first. Install Termux:API from the same
source as Termux, open it and allow requested permissions.

**Phone / Termux:**

```sh
pkg install python termux-api termux-services proot-distro
termux-battery-status
proot-distro install debian
```

Skip Debian installation if already installed. Battery status must return JSON.

**Laptop / repository root:**

```sh
ssh phone 'mkdir -p ~/phome'
scp -r config scripts phone:phome/
```

**Phone / Termux:**

```sh
proot-distro login --bind "$HOME/phome:/opt/phome" debian -- \
  sh /opt/phome/scripts/install-monitoring-debian
proot-distro login --bind "$HOME/phome:/opt/phome" debian -- \
  /usr/bin/promtool check config /opt/phome/config/prometheus.yml
sh ~/phome/scripts/install-monitoring-termux PHONE_TAILSCALE_IP
```

Replace `PHONE_TAILSCALE_IP` with this phone's Tailscale IPv4 address. The Debian
installer uses Debian packages and Grafana's signed official stable APT repository.
The Termux installer preserves existing services, creates one `phome-monitoring` service
and installs `~/.termux/boot/start-monitoring`. It also enables the existing runit
SSH service, migrating a standalone listener and backing up the SSH boot script.
SSH keys/configuration and unrelated services are preserved.
The service acquires a Termux wake lock at every start, including crash recovery;
without it Android sleep can delay samples by minutes.
It generates the Grafana admin password once into `data/grafana.env` (mode 600).
Never commit that file. Subsequent installs preserve it; edit its IP on a replacement
phone or if the Tailscale address changes.

Open `http://PHONE_TAILSCALE_IP:3000/d/phome-phone` from a Tailscale-connected
computer. Initial Grafana database setup can take several minutes; subsequent
starts are faster. Allow a minute for the first sample. Graphs fill as data accumulates.

## Metrics and Android limitations

The dashboard includes battery percentage/temperature/voltage, external power,
charging state, data filesystem used/available space, total/available/cached RAM,
uptime, per-core CPU frequency, collection health and source availability.
Top-row RAM available/used tiles show current headroom. RAM used is total minus
MemAvailable, not the sum of app allocations. The monitoring RAM panel shows
`phome_process_memory_pss_bytes{service=...}` for the supervisor, exporter,
Prometheus, Grafana, Grafana plugins and PRoot wrappers; the collector measures
these through Android's real `/proc/*/smaps_rollup` every five seconds. RSS is
also exported, but PSS avoids double-counting shared pages. This covers monitoring
processes visible to Termux, not all Android apps or swapped-out pages.

Android on the tested realme blocks `/proc/stat` and `/proc/net/dev`. System CPU
utilization and network throughput panels are omitted to avoid empty graphs.
There is no ordinary Termux permission or PRoot setting that grants access.
ADB/Shizuku or root would require a separate privileged collector; Shizuku's
non-root startup must be repeated after reboot, so it is not part of this setup.
See the [Shizuku startup guide](https://shizuku.rikka.app/guide/setup/).
Frequency is not utilization. These
counters are collected automatically if readable on another phone. Battery
percentage/health does not measure remaining battery capacity or lifespan.
Filesystem metrics describe the filesystem backing Termux data, not one directory.

The collector omits failed metric sources rather than inventing values. Its
source availability gauges identify failures. If the collector stops entirely,
the exporter returns HTTP 503 after 90 seconds and Prometheus marks it down.

## Configuration and data

The laptop repo is the source copy. `scp -r config scripts phone:phome/` copies
those directories to `~/phome` on the phone; editing the laptop copy alone does
not change the running phone. Debian sees the same directory as `/opt/phome`.

| Script | Purpose | Runs in |
| --- | --- | --- |
| `install-monitoring-debian` | Installs Prometheus, Grafana and dependencies | Debian, during setup |
| `install-monitoring-termux` | Configures automatic startup and the admin secret | Termux, during setup |
| `install-sshd-service` | Enables supervised SSH and migrates a standalone listener | Termux, during setup/deploy |
| `start-sshd`, `start-monitoring` | Start SSH and monitoring at boot | Termux |
| `monitoring-supervisor.py` | Keeps the collector and three services running | Termux |
| `collect-phone-metrics.py` | Reads Android stats and writes a JSON snapshot | Termux, inside supervisor |
| `phone-exporter.py` | Turns that snapshot into Prometheus-readable metrics | Debian |
| `run-prometheus`, `run-grafana`, `run-phone-exporter` | Launch each service inside Debian | Called from Termux |
| `scheduler.py` | Runs interval jobs from `config/scheduler.json` | Termux, inside supervisor |
| `reload-grafana.py` | Reloads provisioned data sources and dashboards | Termux, scheduled |
| `deploy-monitoring` | Copies, validates and deploys monitoring updates | Laptop |
| `ensure-wake-lock` | Checks/restores the Android CPU wake lock | Termux, scheduled |
| `memory-report.py` | Reads monitoring process memory | Termux, optional diagnostic |
| `grant-termux-access` | Grants supported Android app permissions | ADB shell, one-time administration |

Data flows: Android → collector → JSON snapshot → exporter → Prometheus → Grafana.
All scripts are copied to the phone, but installers only run during setup and
updates; the supervisor runs the ongoing services. Debian provides their Linux
environment, not a container or a second machine.

- `config/prometheus.yml`: scraping and rule settings.
- `scripts/run-prometheus`: database directory, `7d` retention and localhost binding.
  It generates `data/grafana-targets.json` from the configured phone IP, so
  Prometheus can scrape Grafana on its Tailscale address.
- `config/grafana.ini`: Grafana settings.
- `config/grafana/provisioning/`: data source and dashboard provisioning.
- `config/grafana/dashboards/phone.json`: dashboard source of truth.

Unused built-in Grafana data source plugins are disabled to reduce background
processes. The Go services use two workers and disable asynchronous preemption
for PRoot compatibility.

Termux's `~/phome` is explicitly bound as `/opt/phome` inside Debian. Both refer
to the same files. Databases remain on the phone and are ignored by Git. Prometheus
expires whole blocks asynchronously; physical deletion is not an exact seven-day
cutoff. Grafana's database holds settings/dashboards, not a second metrics archive.

## Operations

Verified on the current realme: dashboard page and provisioned data source load,
live battery/RAM/storage/CPU frequency queries succeed, both scrape targets are
healthy, and samples continue after a service restart. Prometheus reports `1w`
retention. Five-second scrape intervals and successful scheduled Prometheus and
Grafana provisioning reloads are verified on the phone. Local tests cover child
restart/shutdown, scheduler config reload, non-overlap and timeout cancellation. Monitoring
startup after a physical phone reboot still needs a separate test after unlocking.

**Phone / Termux:**

```sh
sv status "$PREFIX"/var/service/phome-monitoring
sv -w 60 restart "$PREFIX"/var/service/phome-monitoring
curl -f http://127.0.0.1:9101/metrics
curl -f http://127.0.0.1:9090/-/ready
```

For logs, read `~/phome/data/logs/SERVICE/current`, where SERVICE is
`phone-collector`, `phone-exporter`, `prometheus` or `grafana`. Each log is rotated
at about 1 MB with up to five previous files. A single Python supervisor manages
the collector and three Debian processes, reducing Android background process use.

To deploy changes from the laptop repository root:

```sh
python scripts/deploy-monitoring
```

This stages files on the phone, checks Python/shell/JSON/scheduler settings and
Prometheus syntax, copies validated files into `~/phome`, then restarts monitoring
to apply code and all settings. It preserves databases and generated secrets.
Deployment briefly interrupts monitoring. It does not update OS packages or
delete files removed from the repo; use the Debian installer for package updates.
Grafana provisioning YAML is checked by Grafana itself when it reloads/starts.
Do not start a second Prometheus process using the same database.

To view the admin password privately, on the phone:

```sh
sed -n '/PHOME_GRAFANA_PASSWORD/p' ~/phome/data/grafana.env
```

It is the initial admin password; changing the admin password later in Grafana
means this file no longer describes the active password. Anonymous viewing can
be disabled in `grafana.ini` if login is preferred.

After a manual reboot and first unlock, check `sv status` and reopen the dashboard.
The boot file starts the existing Termux service supervisor. If Tailscale isn't
ready immediately, the monitoring supervisor retries until its address is available.
Android may still stop Termux; keep the background/wake-lock settings in the setup
guide. Recovery before first unlock and total battery depletion is device-dependent.

## Scheduled commands and configuration reload

`config/scheduler.json` is a list of Bash commands and intervals. For example, add
this object to its `jobs` array to run a command every five minutes:

```json
{
  "name": "example",
  "every_seconds": 300,
  "timeout_seconds": 20,
  "command": "date >> data/example.log"
}
```

Commands run in Termux with `~/phome` as their working directory. Use
`proot-distro login debian -- ...` explicitly for commands needing Debian.
The scheduler is a thread in the existing supervisor, not cron. Each job starts
after its first interval, runs without overlapping itself, and has its process
group stopped on timeout or supervisor shutdown. A slow job skips overlapping
ticks; missed runs during downtime are not replayed. Intervals use elapsed time,
not calendar/cron syntax. The wake lock keeps them running while the screen is off.

Scheduler config changes on the phone are detected within a second. Invalid
settings leave the last valid schedule running and record an error. Logs are in
`data/logs/scheduler/current`; only the last 8 KB of each command's output is logged.
Commands share the phone user's permissions; keep credentials out of commands
and command output.

Default jobs run every 60 seconds:

- Prometheus: POST `http://127.0.0.1:9090/-/reload`. The lifecycle API is enabled
  only on its localhost listener. Invalid Prometheus settings fail the job while
  Prometheus keeps its previous configuration.
- Grafana: checks provisioning YAML fingerprints every 60 seconds and POSTs
  its admin provisioning reload endpoints only for changed resources, using the
  private `data/grafana.env` credentials. Unchanged files are skipped; successful
  fingerprints are saved in `data/grafana-provisioning-state.json`. Failed reloads
  are retried next interval. Dashboard JSON uses Grafana's own five-second file
  polling, rather than repeated admin reloads. If you change the
  admin password in Grafana, update this file privately too.

A third job runs `sv up "$PREFIX/var/service/sshd"` every 30 seconds to ensure
SSH is running. Its runit service independently restarts crashes immediately.
For planned SSH downtime, remove that job first; otherwise the scheduler will
bring it back. The scheduler cannot recover a stopped Termux app or failed VPN.

`wake-lock-check` also runs every 60 seconds. With DUMP permission it checks
the current PowerManager wake-lock list and releases/reacquires Termux's lock
if absent. Without that permission it sends the standard acquisition request.
This is a recovery safeguard, not a bypass of Android/vendor power policy.

Grafana also checks dashboard JSON every five seconds. These reloads apply files
already deployed onto the phone; they do not pull from GitHub or the laptop.
`grafana.ini`, service scripts and Prometheus startup flags require a restart;
the deployment command performs that restart. Seven-day retention is unchanged.

## Memory footprint

Measure from Termux (not Debian, whose `/proc` is partially substituted):

```sh
python ~/phome/scripts/memory-report.py
```

Or from the laptop: `ssh phone 'python ~/phome/scripts/memory-report.py'`.
This includes each service's PRoot wrapper and Grafana's plugin descendants.
PSS apportions shared pages between processes; summed RSS double-counts shared
pages. See the [kernel memory documentation](https://cdn.kernel.org/doc/html/latest/filesystems/proc.html).
These are current resident measurements, not maximum memory requirements.

Three samples on the realme on 2026-10-01, with five-second collection/scrapes:

| Component | PSS, MiB |
| --- | ---: |
| Supervisor, collector and scheduler (one Python process) | 15–16 |
| Python exporter plus PRoot | 17 |
| Prometheus plus PRoot | 75–76 |
| Grafana, Prometheus data source plugin and PRoot | 334–340 |
| Total | 442–447 |

Android reported about 2,290–2,308 MiB available out of 5,283 MiB total.
The monitoring stack explains about 0.44 GiB of the phone's occupied memory;
the report cannot attribute Android/system/other-app memory outside Termux.
Available memory is the useful headroom estimate, including reclaimable cache;
raw free memory alone is misleading. It is not a guarantee for future workloads.

The supervisor's collector and scheduler already share one interpreter, and
unused Grafana backend plugins are disabled. Python's persistent contribution
is about 32 MiB (under 1% of phone RAM); Rust cannot save more than that baseline
and would still need memory itself. Grafana is the main optimization candidate.
These initial measurements predate the Grafana mitigation below. Lower Go GC
limits trade memory for CPU and do not cap total process memory, including file
mappings; see the [Go GC guide](https://go.dev/doc/gc-guide).
Retest under real workloads and after Prometheus has accumulated a full week.

### Grafana memory-growth investigation, 2026-10-01

After deployment, Grafana grew to roughly 700 MiB resident memory including its
plugin; Go metrics showed about 457 MiB allocated heap. Short health checks had
not established steady-state memory behavior. Logs showed the latest restart
was a deployment's clean shutdown, not a proven crash/OOM. The user's reported
earlier outage/peak was not independently captured, so no crash cause is claimed.

Mitigation installed:

- `run-grafana`: `GOMEMLIMIT=256MiB`, `GOGC=50`, keeping two Go workers.
  This is a **soft Go-runtime budget**, not a 256 MiB total-RAM cap. Grafana's
  executable/file mappings and plugin process add resident memory beyond it.
- Unused unified alerting disabled in `grafana.ini`.
- Provisioning admin reloads changed from unconditional requests every minute
  to requests only when provider/data-source files change. This removes needless
  work; it is not proof that reloads caused a memory leak.

Grafana alone was deliberately restarted to apply these settings. Prometheus,
SSH and the monitoring supervisor were kept running. The automatic collector
and Prometheus sampling intervals remain five seconds. Reload tests verify that
unchanged files cause no HTTP requests and failed reloads are not marked applied.

Validation: 60 complete dashboard query batches at five-second intervals over
five minutes, with no query failures or Grafana restart. Main-process RSS varied
between 311 and 354 MiB, ending at 323 MiB; Grafana plus its plugin/PRoot measured
about 380 MiB afterward. All 11 local tests passed. This short load test shows
an improvement, not an overnight stability guarantee or proof of a leak's cause.

PowerManager inspection additionally showed Android had released Termux's CPU
wake lock despite prior acquisition requests. Explicit release/reacquire restored
the live lock, and the scheduled check above was added. Sleep can delay timers
and requests; the precise vendor release cause remains unconfirmed.

## References

- [Prometheus configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)
- [Prometheus retention](https://prometheus.io/docs/prometheus/latest/storage/)
- [Grafana Debian installation](https://grafana.com/docs/grafana/latest/setup-grafana/installation/debian/)
- [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Termux services](https://github.com/termux/termux-services)
