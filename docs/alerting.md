# Telegram outage notifications

Prometheus evaluates [the alert rules](../config/alert-rules.yml) every five
seconds and forwards firing/recovered alerts to Alertmanager at
`127.0.0.1:9093`. Alertmanager runs in the same Debian PRoot environment under
the existing phone monitoring supervisor. It has persistent state under
ignored `data/alertmanager/`, bounded supervisor logs and clustering disabled.
Its HTTP API is loopback-only and is not published through Funnel.

`TargetDown` fires when `up == 0` persists for one minute. Alertmanager groups
by alert name, job and instance, waits 15 seconds before first notification,
checks group changes every minute, and repeats ongoing outages every four hours.
Recovery messages are enabled. Notification timing also depends on network
delivery and Android scheduling; this is not a hard deadline.
Messages use a red/green status heading, a readable service name, the target
address and a short explanation. The tracked
[Telegram template](../config/alertmanager-telegram.tmpl) uses Telegram HTML
formatting and escapes variable labels before inserting them.

## Installation

Phone/Termux, after the baseline Debian monitoring installation:

```sh
proot-distro login debian -- apt-get install -y --no-install-recommends prometheus-alertmanager
```

Laptop:

```sh
python scripts/deploy-monitoring
```

The Debian installer also includes Alertmanager for new phones. Deployment
checks the Prometheus rules and Alertmanager template, preserves secrets and
restarts monitoring. Alertmanager starts with an `unconfigured` receiver until
Telegram setup is complete: alerts are visible in its API but not delivered.

## Create and configure the bot

1. In Telegram, open verified [@BotFather](https://t.me/BotFather), send `/newbot`
   and choose a name/username. Keep the returned token private.
2. Open your new bot and send `/start`. This permits it to message your account.
3. Phone/Termux:

   ```sh
   python ~/phome/scripts/configure-telegram.py
   ```

The script prompts for the token with terminal echo disabled, validates it
against Telegram, discovers your private chat using `getUpdates`, saves private
files and validates/reloads Alertmanager. If multiple private chats exist, select
the intended chat. This setup is intended for a dedicated alert bot and a private
chat; a bot already using webhooks or consumed updates needs separate setup.
Do not put a token directly in a command, shell history or tracked configuration.

Secrets: `data/telegram/bot-token` and `data/telegram/chat.json`, mode 600 in a
mode 700 directory. Alertmanager uses `bot_token_file`, so the generated JSON
configuration contains a file path rather than the token. JSON is valid YAML
for Alertmanager. The supervisor redacts Telegram token patterns in Alertmanager
log output, including Bot API URLs. Keep these files private when sharing logs.

The tracked [Alertmanager template](../config/alertmanager.json) controls grouping
and timing. After changing it, phone/Termux:

```sh
python ~/phome/scripts/configure-telegram.py --reload
```

Startup renders the template automatically. Future scraped services inherit the
same `TargetDown` rule. Register their scrape targets in
[Prometheus configuration](../config/prometheus.yml); intentionally removing a
target removes its `up` series and does not create an outage alert.

## Verification and limits

Phone/Termux:

```sh
curl --fail http://127.0.0.1:9093/-/ready
curl --fail http://127.0.0.1:9090/api/v1/rules
curl --fail http://127.0.0.1:9090/api/v1/alertmanagers
```

Rule unit tests, inside Debian with the repository at `/opt/phome`:

```sh
cd /opt/phome
promtool test rules tests/alert-rules.test.yml
```

For a live test, add a temporary loopback-only scrape job on an unused port,
reload Prometheus, wait for `TargetDown` and confirm Telegram delivery. Start a
temporary metrics HTTP server on that port to verify a recovery notification,
then remove the test job and stop the server. Avoid stopping production services
to test notification delivery.

**The phone cannot reliably alert about its own complete outage.** If Android
kills the stack, Prometheus stops evaluating rules; if the phone loses internet,
Telegram delivery stops. If Alertmanager is down, it cannot deliver its own
outage notification while down. Independent external monitoring is required for
those cases. These local alerts cover failed scrapes while the alerting stack
and notification connection are operating.

Current Telegram end-to-end verification status is recorded in the
[handover](handover.md). Package installation and rule tests alone do not prove
that a push notification arrived.

Installed phone verification on 2026-10-02: the real Prometheus rule fired for a
temporary failed scrape target, Telegram accepted the notification and the user
confirmed receipt. Starting a loopback metrics server cleared the alert and
Telegram accepted the recovery notification. Both deliveries had zero errors.
The test target/server were removed and production configuration restored.
31 Python tests and Promtool rule tests passed; both message template states
and HTML escaping were verified with the installed amtool. Phone reboot recovery
and whole-phone outage detection are not proven by this test.
