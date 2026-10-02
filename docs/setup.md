# Set up a phone home server

Goal: connect from a laptop using `ssh phone`, including outside the home, with
SSH keys and automatic startup after reboot. No Android root access is required.

## 1. Install Termux and start SSH

**On Android:** turn Battery Saver off, including automatic activation. A server
needs to keep running with the screen off. Vendor power restrictions can still
interfere; see [the screen-off reliability check](monitoring.md#sparse-data-investigation--2026-10-01).

Connect both devices to the same Wi-Fi. Install Termux and Termux:Boot from the
same source (for example F-Droid), then open both once. Their signatures must
match; do not mix installation sources. Back up an existing Termux installation
before uninstalling it.

**On the phone, in Termux:**

```sh
pkg install openssh
passwd
sshd
whoami
ssh-keygen -lf "$PREFIX/etc/ssh/ssh_host_ed25519_key.pub"
```

Choose a password privately. Record the username and ED25519 fingerprint.
Find the phone's local IP in Android Wi-Fi settings.

**On the laptop**, substitute the username and local IP:

```sh
ssh -p 8022 PHONE_USER@PHONE_LAN_IP
```

Compare the ED25519 fingerprint with the phone before accepting the host key,
then enter the password. Run `whoami` to confirm and `exit` to return to the laptop.
Termux SSH uses port **8022**.

## 2. Set up Tailscale on both devices

**On Android:** install Tailscale, sign in, enable its VPN connection and record
its `100.x.x.x` address.

**On an Omarchy laptop:**

```sh
omarchy pkg add tailscale
sudo systemctl enable --now tailscaled
sudo tailscale up
```

On plain Arch Linux, install with `sudo pacman -S --needed tailscale` instead.
For other systems, use [Tailscale installation](https://tailscale.com/download).
Open the login link returned by `tailscale up` and use the same account as the
phone. Both devices must connect to the same tailnet.

**On the laptop:**

```sh
tailscale status
ssh -p 8022 PHONE_USER@PHONE_TAILSCALE_IP
```

Verify the same phone host fingerprint when prompted for the new address.
This uses ordinary SSH over Tailscale; the separate Tailscale SSH feature is
unnecessary. No router port forwarding is needed.

For unattended access, open [Tailscale Machines](https://login.tailscale.com/admin/machines),
find the phone and choose **Disable key expiry** from its menu. Otherwise periodic
reauthentication may interrupt access.

## 3. Configure `ssh phone` and password-free login

**On the laptop:** create a dedicated key only if this path does not already exist.

```sh
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/phone_ed25519 -N '' -C 'laptop to phome'
```

The empty passphrase allows login without prompting from this laptop. Keep the
private key on the laptop, outside this repository. A passphrase with an SSH agent
is an alternative.

Add this block to `~/.ssh/config`, replacing placeholders and preserving existing
entries. Place it before any `Host *` block that sets the same options:

```sshconfig
Host phone
    HostName PHONE_TAILSCALE_IP
    User PHONE_USER
    Port 8022
    IdentityFile ~/.ssh/phone_ed25519
    IdentitiesOnly yes
```

Then run:

```sh
chmod 600 ~/.ssh/config
ssh-copy-id -i ~/.ssh/phone_ed25519.pub phone
ssh -o BatchMode=yes phone 'whoami'
```

`ssh-copy-id` asks for the phone password once and installs the public key.
The final command should print the Termux username without prompting.
Normal access is now **`ssh phone`**.

## 4. Configure automatic startup

Ensure Termux:Boot has been installed and opened once.
**On the laptop, from this repository's root:**

```sh
ssh phone 'mkdir -p ~/.termux/boot'
scp scripts/start-sshd phone:.termux/boot/start-sshd
ssh phone 'chmod 700 ~/.termux/boot/start-sshd; termux-wake-lock'
```

Check for an existing `start-sshd` before replacing custom startup configuration.
The script acquires a wake lock and brings up the Termux `sshd` runit service
when available. Before service supervision is installed, it starts SSH directly.
The [monitoring installation](monitoring.md) also installs SSH supervision and
migrates any standalone listener, backing up the previous boot script.

For SSH supervision without monitoring, copy `scripts/` to `~/phome/scripts`,
install `python` and `termux-services` in Termux, then run:

```sh
sh ~/phome/scripts/install-sshd-service
sv status "$PREFIX/var/service/sshd"
```

Runit immediately restarts an exited SSH listener. With monitoring installed,
the scheduler also runs `sv up` every 30 seconds, recovering an accidentally
stopped service. Existing SSH configuration, host keys and authorized keys are
preserved. Neither mechanism can recover if Android stops the entire Termux app;
boot/background permissions are still required.

**In Android settings:** allow background activity and auto launch, wherever
available, for Termux, Termux:Boot and Tailscale; disable battery optimisation
for those apps. On the tested realme, use **Settings → Apps → App management →
app → Battery usage**. Another entry is **Settings → Battery → App battery
management**. Labels vary between devices.

Search Settings for **VPN**, open Tailscale's settings and enable **Always-on VPN**.
Leave **Block connections without VPN** off.

## 5. Test recovery and remote access

1. Reboot the phone manually and unlock it once.
2. Wait a moment, then run `ssh phone` without opening Termux or Tailscale.
3. Leave the screen off overnight and try again.
4. Connect the laptop to another network, such as a hotspot, and try again.

Tailscale keeps the same IP through reboots and network changes while the device
remains registered. Resetting/reinstalling Tailscale, wiping the phone or removing
and registering it again can change the address. Interrupted SSH sessions need
a fresh connection.

Recovery before the first unlock is device-dependent. Total battery depletion
may require manual power-on and unlocking.

## Troubleshooting and replacement phones

- **Connection times out:** check internet access and both devices in Tailscale.
  Open Termux and run `sshd`; if this fixes it, check boot and background settings.
- **Password requested:** verify the username/key with `ssh -G phone` and repeat
  `ssh-copy-id` if needed.
- **Host key changed:** verify the fingerprint directly on the phone first. After
  confirming a legitimate replacement/reinstall, remove the obsolete entry with
  `ssh-keygen -R '[PHONE_TAILSCALE_IP]:8022'`, then reconnect.
- **Replacement phone:** repeat the guide, update `HostName` and `User` in the
  laptop config and install the existing laptop public key on the new phone.
  Do not overwrite the laptop private key just to replace the phone.

## Tested installation (example)

Configured on 2026-10-01: realme GT Master Edition (RMX3363), Android 13, and an
Omarchy laptop. These values are examples; discover the new phone's own values.

| Setting | Value |
| --- | --- |
| Termux username | `u0_a128` |
| Phone Tailscale IP | `100.108.243.40` |
| Initial phone Wi-Fi IP | `192.168.0.143` |
| Laptop SSH alias | `phone` |

Verified: password login on Wi-Fi, SSH over Tailscale, password-free key login,
and recovery after manual reboot and first unlock. Later verified SSH listener
crash recovery through runit and recovery from a deliberately stopped service
through the monitoring scheduler. The updated boot/service configuration has
not been retested with a physical reboot. Overnight operation and access
from an external network remain untested. Disabling key expiry was recommended
but has not been confirmed.

## References

- [Termux installation](https://github.com/termux/termux-app#installation)
- [Termux:Boot](https://github.com/termux/termux-boot/blob/master/README.md)
- [Tailscale Linux setup](https://tailscale.com/docs/install/linux)
- [Tailscale stable addresses](https://tailscale.com/docs/concepts/ip-and-dns-addresses)
- [Unattended access and expiry](https://tailscale.com/docs/how-to/run-unattended)
- [realme app settings](https://www.realme.com/global/support/kw/doc/2085394)
