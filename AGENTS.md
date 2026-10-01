# Repository purpose

phome contains guides, scripts and related resources for using old Android phones
as home servers. The baseline is Termux, ordinary OpenSSH on port 8022, Tailscale
for stable remote access, and Termux:Boot for startup. Extend the repository as
phone-hosted services and supporting tools are added.

## Conventions

- At handover, read `docs/handover.md` for installed state, verification and open
  issues before making changes. Keep it current when operational state changes.
- Keep guides concise, reproducible and ordered for someone setting up a new phone.
- Label commands by where they run: laptop or phone/Termux.
- Use placeholders for device-specific values; label actual examples clearly.
- Put scripts in `scripts/` and detailed guides in `docs/`; link them from README.
- Keep monitoring backends in the same Debian PRoot environment. Collect Android
  host metrics in Termux because PRoot may substitute synthetic `/proc` data.
  Use the single monitoring supervisor to limit Android background process use.
- Put service configuration and provisioned dashboards in `config/`. Keep runtime
  databases, logs and generated secrets under the ignored `data/` directory.
- Update relevant documentation when setup procedures or scripts change.
- Keep passwords, private keys, authentication links and tokens out of the repo.
- Preserve existing configuration and keys when providing installation commands.
- Use shell syntax compatible with the documented runtime; Termux paths differ
  from desktop Linux paths. Document dependencies and installation locations.
- Check shell syntax and local documentation links. Test relevant behaviour when
  possible, and distinguish verified results from assumptions and future checks.
- Adding a script to the repo does not install it on a device. Report actual
  installation and testing separately; do not reboot devices unexpectedly.
- Charging automation and enclosure design are deferred. Do not add them without
  a new user request.
- Routine laptop deployment uses `python scripts/deploy-monitoring`; services and
  interval jobs run on the phone without the laptop. Setup, ADB permissions and
  optional diagnostics are separate operations, documented in `docs/`.
- Keep SSH under Termux runit supervision, separate from the Python supervisor.
  The scheduler periodically ensures it is up. Avoid creating a second listener.
- `CLAUDE.md` is a relative symlink to this file; keep one instruction source.
- Memory cleanup is paused. Do not disable more Android apps or tune memory
  limits unless requested. The optional search apps already disabled and their
  reversal commands are recorded in `docs/android-access.md`.
- Next planned work is smart-plug charging, then an app hosting framework. The
  plug is available, but its exact model/control interface still needs checking.
