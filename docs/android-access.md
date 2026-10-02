# Android administration access

SSH runs as Termux's Android app user; it does not grant ADB-shell or root
privileges. Termux requests diagnostic and settings permissions which can be
granted once using ADB. Not all Android permissions are grantable to ordinary
apps, and app permissions do not remove SELinux filesystem restrictions.

## Pair from the laptop

Install Google's [SDK Platform Tools](https://developer.android.com/tools/releases/platform-tools).
On the phone enable Developer options and Wireless debugging. Open **Pair device
with pairing code** and keep it open while pairing.

**Laptop:**

```sh
adb pair PHONE_IP:PAIRING_PORT
# Enter the temporary pairing code when prompted; never save it in this repo.
adb connect PHONE_IP:CONNECTION_PORT
adb devices -l
```

The pairing dialog's port differs from the main Wireless debugging screen's
connection port. Both may change. `adb mdns services` can discover them on the
same LAN. The current realme was paired successfully using its Tailscale IP;
other devices/network configurations may require the LAN IP.

## Grant administrative app permissions

Use `adb -s PHONE_IP:CONNECTION_PORT` if multiple devices are connected.

```sh
adb shell pm grant com.termux android.permission.DUMP
adb shell pm grant com.termux android.permission.READ_LOGS
adb shell pm grant com.termux android.permission.WRITE_SECURE_SETTINGS
adb shell pm grant com.termux android.permission.PACKAGE_USAGE_STATS
adb shell appops set com.termux GET_USAGE_STATS allow
adb shell appops set com.termux MANAGE_EXTERNAL_STORAGE allow
adb shell dumpsys deviceidle whitelist +com.termux
```

These enable diagnostic dumps, system-log access, settings writes, usage
statistics, shared-storage access and a battery exemption respectively. They
do not grant access to other apps' private directories or unrestricted process
control. Only permissions requested by the installed APK can be granted.
Termux:API has separate runtime permissions for individual Android APIs.

To reproduce the broader access granted on this server (also notifications,
media permissions, overlays and permission to request APK installs), from the
laptop repository root:

```sh
adb -s PHONE_IP:CONNECTION_PORT shell sh < scripts/grant-termux-access
```

The script reports any unsupported grants on other Android/Termux versions.
It is intended for ADB shell, not routine monitoring deployment. APK installs
may still need Android confirmation. `READ_LOGS` can be subject to additional
Android/vendor consent restrictions.

On some realme/ColorOS firmware, ADB permission grants fail with missing
`GRANT_RUNTIME_PERMISSIONS` or `MANAGE_APP_OPS_MODES`. Check Developer options
for **Permission monitoring** (turn off) or **Disable permission monitoring**
(turn on); confirm the actual label before changing it. This is a vendor
restriction described in the [Shizuku documentation](https://shizuku.rikka.app/guide/setup/).

## Verify and inspect RAM

**Laptop, after granting DUMP:**

```sh
ssh phone '/system/bin/dumpsys activity processes'
ssh phone '/system/bin/dumpsys procstats --hours 1'
```

Full memory reports still use `adb shell dumpsys meminfo`: on the tested realme,
the `meminfo` Binder service remains hidden from Termux even after these grants.
The full report includes
system/native processes that Termux's `/proc` access cannot enumerate. Its totals
and per-process accounting differ from the Developer options RAM summary; do
not add RSS, PSS, kernel, graphics and swap figures as if they were disjoint.

## Current verification

2026-10-01: wireless ADB pairing and connection succeeded. After disabling the
vendor permission-monitoring restriction, all permissions and app-op changes
listed in `scripts/grant-termux-access` succeeded. Package state confirmed
`DUMP`, `READ_LOGS` and `WRITE_SECURE_SETTINGS` granted for the primary user.
Permission changes restarted Termux processes; SSH and monitoring were restored.
Activity process and process-statistics reports were verified over SSH. Despite
`WRITE_SECURE_SETTINGS` being granted, this firmware's `settings` CLI performs
additional user-management permission checks which Termux cannot pass; use
`adb shell settings ...` for settings administration.

2026-10-02: realme GuardElf/Athena was confirmed killing Termux despite reported
background/auto-launch permissions. Its separate **Settings → Battery → More
battery settings (or Advanced settings) → Optimize battery use** page offers
**Don't optimize** per app. Inspect Termux, Termux:API, Termux:Boot and Tailscale
there as well; background/auto-launch is not enough evidence of this policy.
The vendor battery provider cannot be read by ordinary ADB shell because it
requires `oplus.permission.OPLUS_COMPONENT_SAFE`. An unlocked UI is needed to
verify the actual selection on this unit. Do not claim it was verified or changed
from the ordinary Doze whitelist alone. See [the handover](handover.md) for
recovery state and still-incomplete unattended verification.

## Applied memory cleanup

2026-10-01: optional Google Search/Assistant and realme Search were disabled
for the primary user after a full memory report identified them as candidates:

```sh
adb shell pm disable-user --user 0 com.google.android.googlequicksearchbox
adb shell pm disable-user --user 0 com.oppo.quicksearchbox
```

Their combined resident PSS was 296.5 MiB before disabling; no corresponding
processes appeared in the subsequent full memory report. Their search/assistant
features are unavailable while disabled. The launcher, Play services, Android
core components, Termux and Tailscale were preserved. MemAvailable rose from
1,729.8 to 1,977.1 MiB during the work; this is an observed change, not a guaranteed
permanent saving (monitoring was restarted and other app/cache usage fluctuates).

To reverse:

```sh
adb shell pm enable --user 0 com.google.android.googlequicksearchbox
adb shell pm enable --user 0 com.oppo.quicksearchbox
```
