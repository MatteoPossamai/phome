# Battery-controlled WiZ charging

The phone controls its charger socket locally over Wi-Fi. At **80% or higher**
it switches off; at **40% or lower** it switches on. Between those values it
keeps the remembered charging cycle. Checks run every 30 seconds through the existing
Termux supervisor's scheduler; no laptop, cloud API or additional daemon is needed.
Dependencies are the existing Python, Termux:API battery collector and Wi-Fi LAN.

## Setup

1. Pair the WiZ socket using the WiZ app and connect the phone to the same LAN.
   Give it a recognisable name, such as `phome-1`. The app name is a human label;
   the controller identifies the socket using its MAC address.
2. WiZ app: **Settings → Security → Allow local communication → Allow all
   controls**. This allows LAN devices to control WiZ products. If queries work
   but switching returns `-32602`, save **Only verified controls**, then save
   **Allow all controls** again. See [WiZ security settings](https://faq.wizconnected.com/hc/en/7-wiz-v2/faq/548-secure-or-disable-local-network-communication/)
   and the [reported app-setting issue](https://github.com/home-assistant/core/issues/177463).
3. Find the socket's IP and MAC in the app/router's device information. Reserve
   its DHCP address if possible. Record your LAN's broadcast address too. Confirm
   the socket supplies only the intended charger before enabling control.
4. **Phone/Termux:** create `~/phome/data/charging-device.json` using your own
   values. Keep the file outside version control. An absent file disables control;
   routine deployment preserves this file.

   ```json
   {
     "enabled": true,
     "name": "YOUR_SOCKET_NAME",
     "mac": "YOUR_12_HEX_DIGIT_MAC",
     "ip": "YOUR_SOCKET_IPV4",
     "broadcast": "YOUR_LAN_BROADCAST_IPV4"
   }
   ```

5. **Laptop, repository root:** `python scripts/deploy-monitoring`. This validates
   and copies configuration/code, then restarts monitoring. Allow a minute for
   the collector and scheduler to start. SSH remains independently supervised.
6. **Phone/Termux:** inspect `cat ~/phome/data/charging-status.json` and
   `tail -n 30 ~/phome/data/logs/scheduler/current`. Verify socket state and
   Android external-power status together. Grafana shows controller health,
   last verified socket state and check age, alongside existing battery charts.

Actual installed example, 2026-10-01: app name `phome-1`, MAC `6c2990aed172`,
IP `192.168.0.202`, broadcast `192.168.0.255`, firmware `1.33.1`,
module `ESP10_SOCKET_06`. The retail model number was not established.

## Behaviour and recovery

- Thresholds and maximum battery-snapshot age live in `config/charging.json`.
  They are read on every run. Defaults are 40%, 80% and 60 seconds.
- Every check reads the actual plug state. Each switch requires an acknowledgement
  and independent state readback. Failed commands return nonzero, appear in the
  scheduler log/status file, and are retried at the next interval.
- A stale, corrupt or unavailable snapshot triggers a direct `termux-battery-status`
  request with an eight-second timeout. If that also fails, request **power on**,
  giving availability priority over the upper threshold. This cannot work if the socket
  is unreachable. Invalid controller/device configuration causes an error rather
  than sending commands to an uncertain target.
- The configured MAC is checked before switching. If the cached address fails or
  belongs to a different device, broadcast discovery searches only for that MAC
  and a socket module. A recovered IP is saved atomically in the device file.
  Discovery does not select another socket. Wi-Fi isolation/broadcast filtering
  can prevent discovery; update the address manually or reserve DHCP.
- `data/charging-cycle.json` remembers ON until 80%, then OFF until 40%, tied to
  the configured MAC. Restarts, manual plug changes and temporary safety ON
  overrides do not reset it. On the first check without cycle memory, the actual
  plug state supplies the starting band state. Once battery readings recover,
  the remembered cycle is restored, even if the level is between 40% and 80%.
- Scheduler jobs do not overlap, and a file lock also prevents overlapping manual
  commands. Each network request has bounded retries; the job has a 25-second
  timeout. No polling loop runs as an additional resident process.
- Status is overwritten atomically in `data/charging-status.json`. Controller
  health becomes zero if its last successful automatic check is older than 90
  seconds. These status metrics depend on the collector and monitoring being alive;
  old Grafana data is not evidence of current health.

**Phone/Termux**, optional commands (the scheduler will resume its policy):

```sh
python ~/phome/scripts/control-charging.py --action status
python ~/phome/scripts/control-charging.py --action on
```

`status` queries the socket without switching, and temporarily replaces the
automatic status record. `on` requests and verifies power on. To stop automation,
set `enabled` to `false` in the device file, wait for any current check to finish,
then turn the socket on using the app. Disabling does not itself switch the socket.

## Reliability limits and validation

This is software control, not an independent hardware charge limiter. Checks can
be delayed by Android sleep; percentages may pass a threshold before execution.
The realme previously released Termux's wake lock while unplugged. The existing
wake-lock guard now renews locks aged four minutes or more as a workaround for
observed vendor releases. Renewal is checked again after three seconds. Longer
verification is required; Battery Saver should remain off. See
[the sleep investigation](monitoring.md#sparse-data-investigation--2026-10-01).

A killed Termux app, dead phone or unavailable Wi-Fi cannot send an ON command.
The implementation has no verified plug-side watchdog/automatic return-to-ON
timer. If it stops while the socket is off, the phone can eventually drain. Manual
recovery is the socket's button or WiZ app. An independent recovery schedule in
WiZ could reduce this risk, but is not configured or verified here and would
sometimes override the upper threshold. Physical reboot and long unattended
charge/discharge cycles must be observed separately; do not infer them from
short tests. Recovery before first Android unlock remains device-dependent.

Local automated tests cover thresholds, stale/invalid sources, disabled setup,
failed switching and retries, identity mismatch, changed-address persistence,
state readback, health freshness and actual UDP packet-loss recovery. Live results
and outstanding observation are recorded in [the handover](handover.md).
