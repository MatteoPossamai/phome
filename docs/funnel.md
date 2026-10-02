# Public HTTPS with Tailscale Funnel

[Funnel](https://tailscale.com/docs/features/tailscale-funnel) gives visitors a
public `https://NODE.TAILNET.ts.net` address without a purchased domain, router
port forwarding or a Tailscale client on the visitor's device. Keep the node
name, tailnet DNS suffix and persistent node state to retain the address.
Supported public ports are 443, 8443 and 10000; bandwidth limits apply.

## Phone setup

The Android VPN app remains responsible for private SSH access. A separate
userspace Tailscale node runs inside the existing Debian PRoot environment.
It creates no second Android VPN and needs no root/TUN device. It does need a
separate sign-in and consumes an additional device in the tailnet.

Laptop: deploy repository files using `python scripts/deploy-monitoring`.

Phone/Termux, with Debian already installed:

```sh
python ~/phome/scripts/install-funnel
sv -w 60 restart "$PREFIX/var/service/phome-monitoring"
sh ~/phome/scripts/funnel-cli up --hostname=phome-public --accept-dns=false
```

Open the authentication link locally and sign in to the existing account. Do
not save that link or authentication keys in the repository. Return to Termux
after signing in so its Keep screen on setting applies.

The installer supports ARM64, downloads official Tailscale 1.102.4 binaries and
verifies the published SHA-256 checksum. Binaries are in ignored
`data/funnel-bin/`; node credentials and socket are in private `data/funnel/`.
It preserves existing node state. Direct execution of these Linux binaries in
Termux was blocked by Android's syscall restrictions; PRoot execution works.
Both wrappers run with the real Termux UID/GID so Tailscale's Unix socket
permissions match. The installer sets `/bin/sh` as that imported Android user's
Debian shell (PRoot initially imports it with `/sbin/nologin`). Fake root alone
does not permit local control: it produces `checkprefs access denied`. Android
root and `sudo` are unnecessary.
The existing monitoring supervisor starts/restarts `run-funnel` when
`data/funnel/enabled` exists. Routine deployments preserve that marker and state.

## Publishing services

Account sign-in, Funnel permission and HTTPS certificate issuance are verified.
Grafana is published on port 8443 and public relay access is verified. Its
existing private address remains available.
The user selected anonymous public Viewer access for Grafana; admin actions
still require Grafana authentication.

After account sign-in, enable MagicDNS, HTTPS certificates and Funnel permission
if requested by the CLI. These are tailnet administrator settings. Use the
CLI's setup workflow rather than replacing the existing tailnet policy.
If the CLI displays an enablement link, open it locally and enable the requested
capabilities. Do not publish sign-in links or node state.

Publish Grafana, phone/Termux (replace the placeholder with the Android VPN IP
used in `data/grafana.env`):

```sh
sh ~/phome/scripts/funnel-cli funnel --bg --https=8443 http://PHONE_TAILSCALE_IP:3000
```

The installed public address is
`https://phome-public.tail1b8023.ts.net:8443/d/phome-phone` (actual device example).
Current Tailscale supports this private-IP proxy target, so no additional
loopback proxy was necessary. `run-funnel` explicitly sets `--statedir` for
certificate storage; omitting it caused `no TailscaleVarRoot` TLS failures.

Phone/Termux example for a future HTTP app listening on loopback port 8000:

```sh
sh ~/phome/scripts/funnel-cli funnel --bg --https=443 http://127.0.0.1:8000
sh ~/phome/scripts/funnel-cli funnel status
```

`--bg` persists the route in the node's state, allowing daemon restarts to restore
it. Reserve a separate public port (for example 8443) for Grafana, or use paths
for apps that support a URL prefix. Port 443 is available for future apps; no
application is installed or published there yet.

## Verification and recovery

Check `sh ~/phome/scripts/funnel-cli status` and `funnel status` on the phone.
Verify the published URL from outside the tailnet, including static assets and
Grafana queries, and verify persistence across a controlled daemon restart.
Do not reboot the phone just to test this. Keep Prometheus/exporter and SSH out
of public routes. Funnel publishes the selected HTTP service, not all phone ports.
Public DNS can take up to ten minutes to appear. Tests from a tailnet member may
use its private MagicDNS address, so they do not establish public relay access.
Grafana's anonymous dashboard, CSS/JS assets and live Prometheus queries passed
through HTTPS, with admin settings returning 403. A controlled Funnel process
group restart restored the same saved route and certificate. A graceful daemon
TERM hung during shutdown on this unit; restart the entire Funnel process group
if necessary, rather than leaving a lingering PRoot session. The supervisor
already forces stuck service groups down after its shutdown timeout.

Public verification on 2026-10-02: Cloudflare DNS returned public relay IPv4
addresses. Requests forced to two public relay addresses (bypassing local
MagicDNS and HTTP proxies, retaining normal TLS certificate verification)
returned Grafana health OK. Dashboard HTML/API, CSS and JavaScript loaded,
live Prometheus queries showed all three targets up, and anonymous admin access
returned 403. This verifies real public relay access, not only tailnet access.

For long-term hosting, account owner: in the Tailscale admin console Machines
page, select `phome-public` and disable key expiry. This node's current key
expires on **2027-03-31**; expiry has not been disabled by the setup. Preserve
its hostname and node state for the same public address. Physical reboot and
overnight Android stability remain separate, unverified checks.

Stop a published example route with:

```sh
sh ~/phome/scripts/funnel-cli funnel --https=443 off
```

Removing `data/funnel/enabled` and restarting monitoring stops the separate
daemon without deleting its keys. Do not remove the node state unless retiring
its identity. Node key expiry, Android killing Termux, lost Wi-Fi/VPN and a drained
battery can interrupt hosting. Screen-on operation is a workaround still under
observation; Funnel does not resolve those Android reliability limits.
