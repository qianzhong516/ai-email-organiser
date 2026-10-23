#!/usr/bin/env python3
"""Apply TEST to the newest inbox arrival through local Proton Mail Bridge."""

import argparse
import getpass
import imaplib
import os
import ssl
import sys


def checked(result):
    status, data = result
    if status != "OK":
        raise RuntimeError(f"IMAP command failed: {data!r}")
    return data


def label_latest(mail, dry_run=False):
    checked(mail.select("INBOX", readonly=dry_run))
    data = checked(mail.uid("SEARCH", None, "ALL"))
    uids = data[0].split() if data and data[0] else []
    if not uids:
        print("Inbox is empty; nothing to label.")
        return
    # UIDs increase as messages arrive in this mailbox.
    uid = max(uids, key=int)
    if dry_run:
        print(f"Would apply TEST to inbox message UID {uid.decode()}.")
        return

    # Bridge represents labels as virtual mailboxes. COPY adds a label.
    destination = '"Labels/TEST"'
    existing = checked(mail.list('""', destination))
    if not any(existing):
        checked(mail.create(destination))
    checked(mail.uid("COPY", uid, destination))
    print(f"Applied TEST to inbox message UID {uid.decode()}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=1143)
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    args = parser.parse_args()
    username = os.environ.get("BRIDGE_USERNAME") or input("Bridge username: ").strip()
    password = os.environ.get("BRIDGE_PASSWORD") or getpass.getpass("Bridge password: ")
    if not username or not password:
        raise ValueError("Bridge username and password are required.")

    # Bridge uses a self-signed certificate; restrict this exception to loopback.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with imaplib.IMAP4("127.0.0.1", args.port, timeout=30) as mail:
        checked(mail.starttls(ssl_context=context))
        checked(mail.login(username, password))
        label_latest(mail, dry_run=args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except (imaplib.IMAP4.error, OSError, RuntimeError, ValueError, EOFError) as error:
        sys.exit(f"Error: {error}")
