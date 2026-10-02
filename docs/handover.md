# Agent handover — 2026-10-02

Read [AGENTS.md](../AGENTS.md) first. This is the current state and continuation
context; the other guides describe reproducible setup. The user subsequently
reported sparse metrics after several hours; see the reliability investigation
below. Do not restart services or continue memory cleanup just to re-check this record.

## User intent and preferences

- Old Android phone as an always-on home server, accessible outside home.
- Everything hosted on the phone. Prometheus, Grafana and exporter consistently
  inside Debian PRoot; the Android collector lives in Termux for real host values.
- Concise explanations; take authorized work through deployment and verification.
- Keep setup, scripts, configuration and operational knowledge reproducible here.
- WiZ charging is now implemented and deployed, explicitly requested by the user.
  Socket app name `phome-1`; verified identity and local control are recorded below.
  Next feature: a framework for hosting apps. Enclosure/3D-printing work remains deferred.
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
| `charging-control` | 30 seconds | Local WiZ control: ON at <=40%, OFF at >=80%, hold actual state between |
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

## Sparse metrics investigation — later on 2026-10-01

The user reported sparse graphs after several hours. Raw six-hour samples had
169 scrapes/target (expected ~4,320); Prometheus self-scrapes had no failed values
but gaps near ten minutes. Phone snapshots had a two-hour gap and 48 failed
scrapes. The supervisor PID remained 11485; repeated whole-stack restarts were
not supported by this evidence. The phone was unplugged, Dozing, Battery Saver
on and missing its Termux partial wake lock, despite existing Doze exemptions.
PowerManager recorded repeated acquire/release pairs about two seconds apart.

ADB reconnected at the recorded port. Battery Saver was disabled using `cmd
power set-mode 0`; this alone did not restore the lock. Disabling Doze was an
unsuccessful diagnostic trial and was undone (deep/light enabled again). Briefly
waking the screen, releasing/reacquiring Termux's lock and sleeping the screen
restored a surviving lock. The exact realme policy remains unconfirmed.

`ensure-wake-lock` now checks again three seconds after renewal and reports
failure when the lock disappears. Copied this script directly to the phone;
no services restarted. Battery Saver remains **off**. Recovery commands and
evidence are in [Monitoring](monitoring.md#sparse-data-investigation--2026-10-01).
Further unattended/overnight verification is required; historical gaps are lost.
Recovery check: 64 samples/target over 315 seconds, zero failed scrapes, maximum
spacing 5.009 seconds; continuous phone snapshots and lock held >5 minutes with
screen off. ADB was disconnected for the final portion. Same supervisor PID.
Shell syntax, four mocked guard paths, documentation links and 11 tests passed.

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

Tests cover charging thresholds/failure handling/UDP retries/health, exporter freshness/corruption, process-memory aggregation, supervisor
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
- Charging is installed and running. Observe a complete natural discharge/recharge
  cycle and overnight screen-off operation; no physical reboot was performed.
- App hosting framework comes afterward. No private registry/GHCR workflow,
  rootless container stack or app deployment framework is implemented.

## WiZ charging implementation — later on 2026-10-01

User confirmed WiZ and app label `phome-1`, requested implementation and all
verification. Phone LAN discovery found one socket: MAC `6c2990aed172`, current
IP `192.168.0.202`, broadcast `192.168.0.255`, module `ESP10_SOCKET_06`, firmware
`1.33.1`. Retail model number remains unconfirmed; working protocol verified on
this unit. An actual OFF/ON test changed Android from plugged/charging to
unplugged/not charging and back, confirming it supplies the phone.

Initial status reads worked but `setPilot` returned `-32602 Invalid params`.
User changed WiZ Security to allow local controls, after which switching worked.
Local communication is unauthenticated on this LAN; no cloud credentials/home
security keys were obtained or stored. Do not publish raw protocol responses,
which include WiZ home/room identifiers and signing metadata.

Installed via `python scripts/deploy-monitoring`: `control-charging.py`, thresholds
in `config/charging.json`, one 30-second scheduler job with 25-second timeout,
collector status metrics and three Grafana charging panels. Deployment intentionally
restarted monitoring once (new supervisor PID 12460); SSH stayed under its own
runit service with PID 12003. No device reboot, memory tuning or app cleanup.
Phone `data/charging-device.json` is enabled, mode 600, ignored by Git; deployment
preserves it. Default thresholds are inclusive 40/80, maximum snapshot age 60s.
Controller requires the configured MAC before switching, uses bounded UDP retries,
checks acknowledgements and actual state, and rediscovers a changed IP by MAC.
File locking covers manual/scheduled overlap. Initially actual plug state supplied
band memory; the 2026-10-02 correction below replaces that with persistent cycle
memory and direct battery reads before the safety power-ON fallback.
Status is atomic `data/charging-status.json`; Grafana health is zero for failed or
>90-second-old automatic checks. See [Charging](charging.md) for setup/recovery.

Verified locally: **23 automated tests passed**, Python/shell/JSON syntax and
local documentation links checked. Live tests used isolated temporary snapshots
(production battery data untouched): 80 -> OFF, 60 -> hold OFF, 40 -> ON,
60 -> hold ON, 80 -> OFF, stale -> ON with error status. Every physical state
was checked against Android external-power status. Deliberately wrong cached IP
recovered the configured MAC through broadcast and persisted the correct address.
Temporary acceptance files were removed. These are controlled threshold tests,
not an observed natural 40–80% cycle.

Normal scheduler then read the actual **97%** battery and switched the charger
OFF, with status `ok=true`. Collector reported enabled/healthy, plug OFF, Android
unplugged/not charging. Grafana API confirmed all three provisioned panels and
their real Prometheus query values; all three scrape targets were up. Phone
PowerManager showed **Dozing**, unplugged, with Termux partial wake lock held.
The user left the phone untouched for screen-off observation.

Final 180-second observation while unplugged/Dozing: six distinct successful
automatic checks, maximum check spacing 30.209s, maximum observed check age
30.174s, maximum battery-snapshot age 1.136s. All three targets stayed up, with
37 unique samples each and maximum scrape spacing phone 5.003s, Prometheus
5.005s, Grafana 5.007s. Termux partial wake lock remained held at the end.
Battery fell from 97% to 96%; plug remained OFF. This is short verification,
not proof of overnight stability or a completed natural charging cycle.

A final malformed-data validation fix was Python-compiled on the phone and
installed atomically without another restart; each scheduler invocation loads
the controller script afresh. Supervisor and service PIDs remained unchanged.

**Limit:** no independently verified socket-side watchdog or automatic return-to-ON
timer is configured. If Android kills Termux or Wi-Fi fails while OFF, the phone
can eventually drain; recover using the socket button or WiZ app. The software
cannot guarantee uninterrupted power or a hard 80% ceiling. Existing wake-lock
guard remains active and the earlier realme sleep issue remains relevant. Longer
observation and the full natural cycle/reboot recovery are outstanding.

## Recurring gaps and charge-cycle correction — 2026-10-02

User reported gappy charts and apparent 79–80% charge cycling. Raw 24-hour data
contained only ~3,159 Prometheus self-scrapes, with 390 gaps >15s; self-scrapes
were successful when executed. Phone battery had 3,039 samples and 284 gaps,
including older gaps of nearly two hours. These are real missing measurements,
not solely Grafana display settings. Counts include the previous investigation.
Retained scheduler logs contained **13 stale-reading safety ON switches**, and
no ON switch caused by a <=40% reading. Recent battery data repeatedly showed
78/79 ->80 after safety ON. The previous safety fallback and use of actual plug
state as band memory caused the observed premature recharging.

Battery Saver was still OFF, Doze exemptions included Termux and Termux:API,
and Termux's foreground service remained present. PowerManager history showed
repeated lock releases, with Oplus `WakeLockCheck` messages at the same times as
05:41:44 and 06:14:13 releases. Exact vendor policy remains unconfirmed. The user
reports checking/enabling background activity and auto-launch, disabling sleep
standby optimisation and locking Termux in Recents.

Correction deployed using `python scripts/deploy-monitoring`, intentionally
restarting monitoring (supervisor PID 21304), preserving SSH PID 12003 and device
configuration. Stale snapshots now trigger a direct eight-second Termux battery
request. Safety ON is used only if both sources fail. `data/charging-cycle.json`
stores the threshold cycle by MAC independently of safety overrides/actual plug
state. Fresh data restores OFF until 40%, or ON until 80%, across restarts and
external plug changes. An initial run without memory uses actual plug state in
the band. Manual ON is temporary; disable automation for a lasting override.

The wake-lock guard proactively renews a lock aged >=4 minutes and checks again
after three seconds. This is a workaround to test, not a proven vendor-policy
fix. Ordinary Doze remains enabled; no apps disabled, memory tuning or reboot.
Wireless ADB reconnected using existing pairing at `100.108.243.40:39581`, then
was disconnected before screen-off observation.

**28 automated tests passed**, including persistent cycle recovery after safety
ON, stale-snapshot direct reads at 79%, bounded API validation, and eight mocked
wake-guard paths. Shell syntax, documentation links and installed script hashes
checked. An isolated stale snapshot on the live phone recovered a direct 79%
reading and left the physical socket OFF; production snapshot was untouched.
Current production cycle is OFF, battery 78%, reading source snapshot.

The attempted ten-minute screen-off validation **did not complete**: after
three minutes of continuous snapshots, at **06:52:29** realme GuardElf/Athena
killed Termux and every child, including SSH, supervisor, Prometheus and Grafana.
`dumpsys activity exit-info com.termux` recorded reason 13 OTHER KILLS BY SYSTEM,
subreason 2006; logcat explicitly recorded `kill persistent app by guardelf`.
No OOM or application crash was established. Prior awake/Dozing observation does
not prove reliable operation; proactive renewal alone is not validated as a fix.

After this kill, the Doze whitelist retained Termux:API but no longer Termux or
Boot (these were present before the user's settings checks). Restored explicit
exemptions for Termux, API, Boot and Tailscale using existing paired wireless ADB.
RUN_ANY_IN_BACKGROUND was already `allow`; RUN_IN_BACKGROUND defaulted to allow.
An ADB launch of Termux was blocked behind secure keyguard; requested that the
user unlock and open Termux so services can be recovered. Do not describe the
chart-gap problem as fixed based on the interrupted test.

User unlocked and Termux/services recovered: supervisor PID 23800, SSH PID 23807.
Charging cycle persisted OFF; fresh production battery fell to 77% and controller
remained healthy. Five-minute recovery query had 50 samples per scrape target,
zero failed values, but maximum spacing ~15–16.4s: collection remains imperfect.
This check was with ADB connected and is not unattended verification.

Background/auto-launch settings were already reported allowed. Investigated the
separate realme **Optimize battery use** policy, which offers Auto optimize,
Don't optimize and Always ask in the vendor battery UI. A reference decompilation
was inspected under `/tmp/phome-antithermal` (HBYShyw/AntiThermal; different firmware,
use as a lead, not proof of this unit's per-app state). The battery provider's
policy list is protected by `oplus.permission.OPLUS_COMPONENT_SAFE`; ADB cannot
read it. Direct activity launch is also protected. Requested the user leave the
phone unlocked to inspect this UI; auto-lock blocked inspection. No battery/Athena
packages were disabled and no vendor policy status was guessed or overwritten.

Historical gaps remain unrecoverable; keep them visible. Long unattended operation
and a complete natural 40–80% cycle still require observation. All battery-source
failure can still request safety ON, and an entirely stopped app/unreachable plug
cannot be rescued by this controller.

## Screen-on workaround and CPU/network access — 2026-10-02

User reports that vendor Optimize battery use was already **Don't optimize**;
do not present changing that setting as the established fix. User enabled Termux
long-press → More → Keep screen on. PowerManager confirmed Awake and a
SCREEN_BRIGHT_WAKE_LOCK attributed to Termux UID 10128. Battery was 75%, plug
OFF and controller healthy. This is not an overnight stability guarantee. A
five-minute query overlapping the first minutes of screen-on operation had 49
samples/target, zero failed values, maximum spacing ~16.6–17.4s; older gaps remain.

Read-only access tests: ordinary phone/Termux still gets permission denied for
`/proc/stat`, `/proc/net/dev` and wlan0 sysfs byte counters. `dumpsys cpuinfo`
is hidden from this app context; `dumpsys netstats` reports missing
READ_DEVICE_CONFIG. Existing DUMP and app-op grants do not solve these paths.
**ADB shell can read `/proc/stat` and `/proc/net/dev`**, including real per-core
CPU ticks and wlan0 RX/TX byte totals. Two real readings ~2.11s apart produced
8.5% CPU busy excluding idle/iowait, and nonzero Wi-Fi traffic deltas. Sysfs wlan0
statistics files remain denied even to ADB; use the verified proc interfaces.
Diagnostic network rates include the traffic generated by SSH/ADB themselves.

No CPU/network collector or panels were installed. Integrating this without a
laptop would require a phone-local ADB client and verified pairing/reconnect/boot
handling (Wireless debugging's port can change). Alternatively an Android helper
could use public TrafficStats APIs for network totals, but this has not been
tested on this unit. Keep current dashboard source labels until a real autonomous
collection path is implemented and verified.

## Public hosting setup — 2026-10-02

User requested Tailscale Funnel for Grafana and future server code, with a fixed
public address and no purchased domain. User explicitly chose anonymous public
Grafana viewing. Android's existing Tailscale app supplies no CLI. Installed
checksum-verified official ARM64 Tailscale 1.102.4 in ignored `data/funnel-bin/`.
Direct Termux invocation hit Android SIGSYS at faccessat2; Debian PRoot invocation
works. Added `run-funnel`, `funnel-cli`, `install-funnel`, and optional `funnel`
service to the existing supervisor, enabled by private `data/funnel/enabled`.
It uses userspace networking, separate private state/socket, no TUN and no
replacement of the existing Android VPN. See [Funnel](funnel.md).

Deployed using the routine deployment command (intentional monitoring restart,
supervisor PID 9518); SSH remained PID 23807. The new daemon responds to the local
CLI and reports NeedsLogin. Requested user run `funnel-cli up` on the phone and
sign in locally; no auth link/key was printed or committed. **No public route
is enabled yet.** Await account sign-in, HTTPS/Funnel permission, final Grafana
forwarding configuration, public external checks and restart persistence checks.
Grafana still binds the private Tailscale IP, so verify support for that backend
target or provide a loopback proxy before publishing it. Do not claim the public
URL or unattended operation is verified. All 28 existing tests pass; new scripts
compile and shell syntax passes. No phone reboot or memory/app tuning.

First user sign-in attempt failed `checkprefs access denied`: PRoot fake root
does not change Unix socket peer credentials. Fixed both wrappers to run with
the actual Termux UID/GID. PRoot had imported UID 10128 as `aid_u0_a128` with
`/sbin/nologin`; changed only that Debian account's shell to `/bin/sh`, and
made the installer reproduce this. No Android root/sudo is needed. Funnel-only
restart applies this without another monitoring restart.

User subsequently completed sign-in. Filtered status should be used on future
checks (full JSON includes personal account/peer metadata). Node is Running,
hostname `phome-public`, DNS `phome-public.tail1b8023.ts.net`, IP 100.74.106.20,
MagicDNS enabled, key expiry 2027-03-31. HTTPS cert domains currently absent.
Attempted `funnel --bg --https=8443 http://100.108.243.40:3000`, redirecting all
output into private `data/funnel/setup-output`; CLI waits for account owner to
enable Funnel. User asked to open that file's setup link locally. No serve config
exists yet. Laptop exec session 18117 remains waiting. Modern CLI supports remote
proxy destinations (legacy localhost-only restriction may no longer apply);
test this backend after permission enablement before adding any extra proxy.

User enabled Funnel/HTTPS. The waiting command completed and saved port 8443
proxying directly to the existing Grafana private address. First TLS request
failed `no TailscaleVarRoot`; added explicit `--statedir=/opt/phome/data/funnel`
to `run-funnel`, copied it to the phone and restarted only Funnel. Graceful
daemon TERM hung in PRoot; terminated its whole process group, which the
supervisor restarted. Certificate issuance then succeeded and is cached in
private `data/funnel/certs/`. State mode 600 and directory mode 700 verified.

Active URL: `https://phome-public.tail1b8023.ts.net:8443/d/phome-phone`.
Private-tailnet HTTPS tests passed: database health OK, dashboard HTML/API 200,
two CSS/JS assets 200, live Prometheus `up` query shows all three targets 1,
admin settings API 403 without authentication. A second controlled Funnel-only
process-group restart restored the route, same address and working cached
certificate; monitoring/SSH did not restart. Public DNS is still propagating
(no A answer from Google/Cloudflare as of 06:57 UTC, enabled about 06:49:52).
**External relay access is not yet verified.** Do not confuse local MagicDNS
100.74.106.20 access with public DNS/relay access. Current status Running,
online true, health empty. Node key expiry remains 2027-03-31 and needs account
owner action for indefinite unattended operation; no account API is available.
No public service runs on 443, leaving it for future applications. Syntax,
Python compilation and local documentation links pass; no reboot performed.

Public verification completed about 06:58 UTC: Cloudflare DNS now returns
176.58.88.82, 176.58.88.108 and 176.58.92.199. Curl forced to public relay IPs,
with proxies bypassed and normal HTTPS/SNI verification, passed health on two
relays. Through 176.58.88.82, dashboard HTML/API and CSS loaded, the Grafana
Prometheus query returned all three targets up, and admin settings returned
403 anonymously. JavaScript loaded through 176.58.88.108. This proves actual
public relay access. No extra proxy or Grafana configuration change was needed.
Setup is installed and public, persistence after Funnel restart verified.
Remaining long-term step: owner disable `phome-public` key expiry in admin
Machines page; current expiry 2027-03-31 remains enabled. Physical reboot and
overnight Android stability are not established by these checks.

## Telegram alerting — 2026-10-02

User explicitly requested Prometheus outage alerts through Alertmanager to
Telegram, hosted on the phone. Installed Debian prometheus-alertmanager
0.28.1+ds-1, binaries `/usr/bin/prometheus-alertmanager` and `/usr/bin/amtool`.
Added supervised `alertmanager` child, loopback HTTP 9093, clustering disabled,
persistent ignored `data/alertmanager/storage`. Debian installer includes its
package; deploy validates its template with amtool. Added one TargetDown rule
(`up == 0` for 1m), Alertmanager notification endpoint and its scrape job.
Tracked grouping config: first wait 15s, group changes 1m, ongoing repeats 4h,
resolved notifications enabled. No public Alertmanager/Funnel route added.

User supplied a bot token in the conversation; do not repeat it or read/print
its private file. Validated via Telegram, saved `data/telegram/bot-token` mode
600 under mode 700 directory; discovered exactly one private chat after user
sent `/start`, saved ID in private `chat.json`. Neither secret is tracked.
`configure-telegram.py` prompts with getpass for fresh setup, renders a private
JSON/YAML runtime config using `bot_token_file`, validates and reloads AM.
Without chat configuration it renders an unconfigured receiver: no delivery.
Alertmanager supervisor log lines redact tokens including Bot API URL patterns.
Two routine deployments restarted monitoring intentionally, last PID 20833;
SSH remained 23807. Existing Funnel restored after monitoring restart.

31 Python tests passed, including private file modes, no token embedded in
runtime config, secret-safe network errors and log URL redaction. Promtool rule
tests passed on phone for pending, firing, recovery and brief-failure suppression.
Live production scrape targets prometheus/phone/grafana/alertmanager all up.
Prometheus API reports loaded rule and active Alertmanager endpoint.

Live acceptance used a temporary `alerting-acceptance-test` scrape target on
127.0.0.1:19199, added only to phone production config with backup in ignored
`data/alerting-acceptance/prometheus.yml`. TargetDown fired via real Prometheus
rule; AM accepted it and Telegram notification count became 1, all failure
counters zero. User confirms receipt and requested improved presentation.
Added Telegram HTML template with red/green headings, service names, target
and explanation; tested both states and escaping malicious label text with
actual amtool renderer. Template/config/helper copied directly and AM reloaded,
no restart. Started temporary loopback HTTP metrics server to recover test
target, PID recorded in `data/alerting-acceptance/server.pid`; Prometheus alert
cleared. Telegram notification count then became 2, all failure counters zero,
verifying accepted firing and recovery notifications. User confirmed the firing
message arrived; mobile receipt of the recovery message was not separately
confirmed. Restored exact production config from backup after checking no other
edits intervened, reloaded Prometheus, stopped test server and removed acceptance
runtime directory. Installed rules/template/helper/launcher/supervisor and config
hashes match repository. Private Telegram/runtime config modes 600 verified.
Final Python run: 31 tests passed. No real service stopped for acceptance.

Limit: if phone/Termux/Prometheus or internet is down, this phone-local stack
cannot independently report the whole outage. External monitoring would be
required. See [Alerting](alerting.md) for setup and recovery.

## Repository state

The repository now has baseline commit `e00f524` (First commit and first artifacts).
This investigation changes documentation and `ensure-wake-lock`; no new commit
was created. `CLAUDE.md` remains a relative symlink to `AGENTS.md`. Do not duplicate
the instruction file, discard files or publish/commit without considering scope.
