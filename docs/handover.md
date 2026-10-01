# Agent handover — 2026-10-01

Read [AGENTS.md](../AGENTS.md) first. This is the current state and continuation
context; the other guides describe reproducible setup. The user accepted the
current Grafana mitigation and asked to stop work here, document it, and hand off.
Do not restart services or continue memory cleanup just to re-check this record.

## User intent and preferences

- Old Android phone as an always-on home server, accessible outside home.
- Everything hosted on the phone. Prometheus, Grafana and exporter consistently
  inside Debian PRoot; the Android collector lives in Termux for real host values.
- Concise explanations; take authorized work through deployment and verification.
- Keep setup, scripts, configuration and operational knowledge reproducible here.
- Current next steps: smart-plug charging, then a framework for hosting apps.
  Charging is not implemented; the user says a “smart qiz plug” is available.
  Exact brand/model and local API support are **unknown**. Confirm before choosing
  a protocol or adding control code. Enclosure/3D-printing work remains deferred.
- Further memory cleanup is paused. Python-to-Rust rewriting was discussed but
  not implemented; steady Python memory is small relative to Grafana.

## Device and access

| Item | Current value |
| --- | --- |
| Phone | realme GT Master Edition, RMX3363, Android 13 |
| Termux user | `u0_a128` |
| Tailscale IP | `100.108.243.40` |
| Initial LAN IP | `192.168.0.143` (may change) |
| SSH | `ssh phone`, port 8022, key authentication |
| Laptop | Omarchy; repo `/home/mpossamai/repos/phome_srvr` |
| Phone repository files | `~/phome/config/`, `~/phome/scripts/` |
| Same files in Debian | `/opt/phome/`, via explicit PRoot bind |
| Dashboard | [Grafana phone health](http://100.108.243.40:3000/d/phome-phone) |

Laptop SSH configuration is in `~/.ssh/config`, with dedicated key
`~/.ssh/phone_ed25519`. Do not read/print the private key or overwrite it.
Grafana anonymous access is Viewer, bound only to the Tailscale address.
Admin credentials are in phone `~/phome/data/grafana.env`, mode 600, ignored by
Git. Do not print, copy into docs or commit this file.

## What runs and why

1. Termux:Boot runs `~/.termux/boot/start-sshd` and `start-monitoring` after boot.
2. Termux runit supervises **sshd** and **phome-monitoring**, independently.
3. `monitoring-supervisor.py` is one persistent Python process containing the
   Android collector and interval scheduler as threads. It manages three PRoot
   service children: Python exporter, Prometheus and Grafana.
4. Collector reads battery via Termux:API, actual Android `/proc/meminfo`, storage,
   CPU frequency and monitoring process PSS/RSS. It overwrites one atomic JSON
   snapshot every five seconds. Prometheus does **not** trigger collection.
5. Debian exporter serves that snapshot at `127.0.0.1:9101/metrics`; snapshots
   older than 90 seconds yield HTTP 503.
6. Prometheus at `127.0.0.1:9090` scrapes itself, the exporter and Grafana every
   five seconds, with four-second scrape timeout and seven-day retention.
7. Grafana (13.2.3 installed) queries Prometheus and renders the provisioned
   dashboard. Prometheus is Debian package 2.53.3. No Docker/Podman is configured;
   unrooted PRoot does not supply container-kernel privileges.

`scripts/` contains installers, startup/launch scripts, daemons, scheduler and
diagnostics. Copying a script onto the phone does not run every script. Routine
deployment is the laptop command `python scripts/deploy-monitoring`; the laptop
is not needed for ongoing operation. Initial setup, ADB grants and optional
diagnostics are separate operations. No extra cron/Ansible has been installed.

## Scheduler and SSH recovery

Jobs in `config/scheduler.json` are hot-reloaded; invalid configuration leaves
the previous valid schedule running. Bash commands run from phone `~/phome`.
Jobs have timeouts, skip overlapping runs of themselves and use elapsed-time
intervals. Missed runs are not replayed. Calendar cron expressions are unsupported.

| Job | Interval | Action |
| --- | --- | --- |
| `prometheus-reload` | 60 seconds | POST localhost `/-/reload`; lifecycle API enabled |
| `grafana-reload` | 60 seconds | Fingerprint provisioning YAML; reload changed resources only |
| `sshd-ensure-running` | 30 seconds | `sv up "$PREFIX/var/service/sshd"` |
| `wake-lock-check` | 60 seconds | Restore missing Termux CPU wake lock |

Grafana dashboard JSON is independently polled every five seconds. Do **not**
restore unconditional Grafana admin reloads every minute: that performs needless
work. Successful provisioning fingerprints are saved in ignored
`data/grafana-provisioning-state.json`; failed requests are not marked applied.

SSH initially ran outside runit while its packaged service was disabled. It is
now migrated to the existing foreground runit service (`sshd -D -e`). Existing
keys, configuration and sessions were preserved; previous boot file was backed
up in `data/start-sshd.bak`. Crash restart and scheduled recovery from `sv down`
were both tested using fresh laptop SSH connections. Avoid starting a second
standalone listener. The watchdog overrides planned `sv down` unless its job is
removed first.

## Memory changes and Grafana incident

Initial PSS measurements: Python supervisor/collector/scheduler ~15–16 MiB,
exporter plus PRoot ~17 MiB, Prometheus ~75 MiB, Grafana/plugin/PRoot ~340 MiB.
These are resident snapshots, not peak requirements; summed RSS double-counts
shared pages. The phone has ~5,283 MiB RAM. Around 2 GiB available is a current
reading, not a fixed ceiling. Transient scheduled subprocesses add memory too.

Google Search/Assistant (`com.google.android.googlequicksearchbox`) and realme
Search (`com.oppo.quicksearchbox`) were disabled using ADB after identifying
~296.5 MiB combined resident PSS. Subsequent reports showed those processes gone.
Their features are disabled. Undo commands and measured before/after limitations
are in [Android access](android-access.md). No launcher/core-system cleanup or
custom ROM/rooting was performed.

The user later reported Grafana down and near 1 GiB. Measured ~700 MiB including
plugin, with ~457 MiB allocated Go heap. Logs confirmed the latest restart was
the deployment script's intentional clean shutdown; the reported earlier crash
or peak was not independently captured. Do not claim a proven OOM or leak cause.

Installed mitigation:

- `run-grafana`: `GOMEMLIMIT=256MiB`, `GOGC=50`, `GOMAXPROCS=2` and
  `GODEBUG=asyncpreemptoff=1`. Go's memory budget is **soft**, not a total-RAM cap;
  code/file mappings and plugin memory are additional. More GC trades CPU for RAM.
- Unused unified alerting disabled. Most unused built-in data-source plugins
  were already disabled; the Prometheus plugin remains required.
- `reload-grafana.py`: reload only changed provisioning resources. This reduces
  churn; its role in the prior memory growth is unproven.
- Restarted **Grafana only** for mitigation; SSH, Prometheus and supervisor remained
  running. Do not redeploy solely to test the already-live settings.

Validation after mitigation: 60 full dashboard query batches at five-second
intervals over five minutes, no query failures/restarts. Main Grafana RSS ranged
311–354 MiB, ending at 323 MiB; combined Grafana/plugin/PRoot later ~380 MiB.
Final handover snapshot: supervisor ~15 MiB, exporter ~16 MiB, Prometheus ~96 MiB,
Grafana group ~380 MiB, total ~507 MiB PSS, MemAvailable ~2,023 MiB; Grafana health
reported database `ok`. All **11 local tests** passed. This is not an overnight
stability guarantee. Keep the resource graph to detect future growth.

## Android access and power-policy limitations

Wireless ADB paired successfully after realme's Developer options restriction
was disabled (**Disable permission monitoring ON**). Granted supported Termux
diagnostic/log/settings/usage/media/storage permissions and relevant app ops.
The exact reproducible grants are in `scripts/grant-termux-access`, executed
through **ADB shell**, not SSH. Full `dumpsys meminfo` and some settings commands
still need ADB because app permissions do not bypass Binder/SELinux/user checks.
Activity process reports and `dumpsys procstats --hours 1` work over SSH.

Google platform-tools were downloaded temporarily to
`/tmp/phome-adb/platform-tools/adb`; not installed as a permanent laptop package.
Last ADB connection was `100.108.243.40:39581`; this port may change. Discover
with `adb mdns services` or the phone's Wireless debugging screen. Pairing codes
are temporary and deliberately absent from docs. ADB keys remain outside the repo.

Android was observed releasing Termux's CPU wake lock while the Termux app still
ran. An ordinary acquisition request did not reliably restore it; explicit
`termux-wake-unlock` then `termux-wake-lock` did. `ensure-wake-lock` checks the
**current** PowerManager list (not historical log lines) with DUMP permission and
renews missing locks. Without DUMP it uses the ordinary acquisition request.
The scheduled guard was observed restoring the lock successfully with exit 0.

**Unresolved:** vendor release cause. Suspended Android can stretch nominal
five-/30-/60-second intervals in wall time because elapsed-time waits stop during
CPU sleep. The guard cannot guarantee exact cadence or revive a killed Termux
app, a failed VPN, an unpowered phone or recovery before first unlock.

## Deployment, data and checks

`deploy-monitoring` stages `config/` and `scripts/` under phone `data/deploy.*`,
validates Python, shell, JSON/scheduler and Prometheus syntax, copies validated
files, runs Termux/SSH installation and **restarts the whole monitoring service**.
Expect brief Grafana downtime. It preserves data/secrets but is not transactional
rollback or package management, and does not delete obsolete phone files. Grafana
provisioning YAML is checked at service start/reload, not fully validated by deploy.

Keep runtime data in ignored `data/`; logs in `data/logs/SERVICE/current` are
rotated. SSH logs are `$PREFIX/var/log/sv/sshd/current`. Existing unrelated
cloudflared/ssh-agent service definitions were preserved; do not remove them
without establishing their purpose.

Useful checks (read-only):

```sh
ssh phone 'sv status "$PREFIX/var/service/sshd" "$PREFIX/var/service/phome-monitoring"'
ssh phone 'python ~/phome/scripts/memory-report.py'
curl -f http://100.108.243.40:3000/api/health
python -m unittest discover -s tests -v
```

Tests cover exporter freshness/corruption, process-memory aggregation, supervisor
recovery/shutdown, scheduler validation/hot reload/non-overlap/timeouts, and
Grafana provisioning reload skip/retry behavior. Do not re-run long load tests
or restart services unless the next task requires it.

The load-test scratch script/results were `/tmp/phome-grafana-load.py` and
`/tmp/phome-grafana-load.jsonl` on the laptop; temporary evidence, not dependencies.
The test POSTed all dashboard Prometheus expressions to Grafana `/api/ds/query`,
using a three-hour range and five-second refresh, and sampled `/metrics` between
batches. Temporary full Android dumps are also under `/tmp/`; do not publish raw
device/log dumps without reviewing their contents.

## Remaining verification and next task

- Latest SSH/monitoring boot setup has **not** been physically reboot-tested.
  Initial SSH/Tailscale boot setup was tested after reboot and first unlock.
- Overnight operation, external-network access and Tailscale key-expiry disabling
  remain unconfirmed. Do not silently reboot the phone.
- Longer Grafana memory stability, exact cadence under vendor power policy and
  Prometheus memory after a full retained week remain to observe.
- Next actionable task: identify the available smart plug and verify local
  control, then design charge thresholds/failure recovery using existing battery
  metrics. Do not assume a brand, cloud dependence or local protocol from “qiz”.
- App hosting framework comes afterward. No private registry/GHCR workflow,
  rootless container stack or app deployment framework is implemented.

## Repository state

All project files are currently **untracked**; no commit has been created during
this work. `CLAUDE.md` is a relative symlink to `AGENTS.md`, verified. Do not
interpret an empty `git diff` as no changes, duplicate the instruction file,
discard files or publish/commit without considering the user's task scope.
