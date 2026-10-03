# posserver recovery copy

The database backup and the configuration backup are separate. posserver uploads
database snapshots to Dropbox. Its Dropbox refresh credential and other runtime
settings live on the phone in `$PREFIX/data/posserver/config.json`; losing the
phone would mean setting those up again unless you keep an encrypted copy.

On the laptop, from this repository, run:

```sh
scripts/backup-posserver-config
```

This streams the phone config directly into Ansible Vault and saves only
`config/posserver-runtime.json.vault` here. It does not save a plaintext copy on
the laptop. Install `ansible-core` if `ansible-vault` is missing. Choose a strong
Vault password and save it in a password manager; the encrypted file cannot be
recovered without it. The script needs the existing `ssh phone` access.

Run the command again after changing posserver backup/provider credentials or
other runtime configuration. The database snapshots continue to update in
Dropbox independently. Keep this repository's encrypted file in a private,
off-device backup (for example a private Git remote); a file only on the laptop
does not protect against losing the laptop too.

## Restore to a replacement phone

Install posserver on the replacement phone, then from the posserver repository
run:

```sh
scripts/phone configure --vault ../phome_srvr/config/posserver-runtime.json.vault
scripts/phone restart
```

The first command asks for the Vault password and installs the decrypted config
with private file permissions on the phone. Then use posserver's Dropbox restore
procedure to retrieve the latest database snapshot. The Vault file does not
contain the database itself.
