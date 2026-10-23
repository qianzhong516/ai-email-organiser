# Email organiser

`label_latest.py` applies the Proton Mail label `TEST` to the most recently
arrived message in **INBOX** (highest IMAP UID). It creates the label if needed.
It uses only the Python standard library.

Start and sign in to Proton Mail Bridge first. The included Docker Compose file
exposes IMAP on local port 1143. Use the username and generated **Bridge password**
shown in Bridge's account settings, rather than your Proton account password.

```sh
python3 label_latest.py --dry-run
python3 label_latest.py
```

Credentials are prompted for; the password is hidden and neither is saved.
For automation, `BRIDGE_USERNAME` and `BRIDGE_PASSWORD` environment variables
are also supported. Use `--port 1144` if your Bridge listens on a different port.

The script connects only to `127.0.0.1`, uses STARTTLS, and accepts Bridge's
self-signed certificate without certificate verification on that local connection.
It copies the message into `Labels/TEST`, which adds the label without moving
the message out of the inbox or changing its read status. Proton documents its
[label-to-folder mapping](https://proton.me/support/labels-in-bridge).
