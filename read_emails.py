from collections.abc import Iterator
from email import policy
from email.parser import BytesParser
import imaplib
import ssl


# Reads inbox messages matching a JSON-style filter and returns their subject,
# sender, date, and original body without sanitizing or marking messages as read.
def read_emails(
    filters: dict,
    *,
    username: str,
    password: str,
    port: int = 1143,
    host: str = "127.0.0.1",
) -> list[dict[str, str]]:
    return list(iter_emails(filters, username=username, password=password, port=port, host=host))


# Yields emails one at a time so the collector can commit each email before
# fetching the next. Optional metadata identifies messages across inbox polls.
# Bodies are MIME-decoded but not passed through HTML_parser here.
def iter_emails(
    filters: dict,
    *,
    username: str,
    password: str,
    port: int = 1143,
    host: str = "127.0.0.1",
    include_metadata: bool = False,
    exclude_ids: set[tuple[int, int]] | None = None,
) -> Iterator[dict]:
    """Read emails through Proton Mail Bridge using STARTTLS.

    Defaults to 127.0.0.1:1143 for host execution. Containers can use the
    Compose service name and internal port instead.

    Supported filters: {"status": "read" | "unread", "limit": 50}.
    Omitting status includes both read and unread messages. Omitting limit
    defaults to 50. Set limit to None to fetch all matching messages; otherwise,
    limit must be a positive integer. Unsupported keys and values raise an error.

    Yields newest arrivals first, as dictionaries with subject, sender, date,
    and body. Date is the original Date header (the sender's stated sending
    time, including any timezone), or an empty string if absent. It is not the
    inbox arrival time. The body prefers HTML, falling back to plain text or an empty string
    if neither exists. MIME transfer encoding and character encoding are decoded;
    the decoded body is otherwise unchanged. Attachments are not returned.

    include_metadata adds account, mailbox, uidvalidity, uid, and message_id.
    exclude_ids skips stored (UIDVALIDITY, UID) pairs before applying the limit.
    """
    if not isinstance(filters, dict):
        raise TypeError("filters must be a JSON object represented as a dictionary")
    if set(filters) - {"status", "limit"}:
        raise ValueError("Only the 'status' and 'limit' filters are currently supported")
    if "status" in filters and filters["status"] not in ("read", "unread"):
        raise ValueError("status must be 'read' or 'unread'")
    limit = filters.get("limit", 50)
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer or None")

    criterion = {"read": "SEEN", "unread": "UNSEEN"}.get(filters.get("status"), "ALL")

    # Stop on a failed IMAP command instead of returning an incomplete result.
    def checked(result):
        status, data = result
        if status != "OK":
            raise RuntimeError(f"IMAP command failed: {data!r}")
        return data

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Accept the configured Bridge's self-signed cert; use a trusted local/Docker network.

    with imaplib.IMAP4(host, port, timeout=30) as mail:
        checked(mail.starttls(ssl_context=context))
        checked(mail.login(username, password))
        checked(mail.select("INBOX", readonly=True))
        uidvalidity = None
        if include_metadata or exclude_ids is not None:
            _, values = mail.response("UIDVALIDITY")
            if not values or not values[0]:
                raise RuntimeError("The inbox did not provide UIDVALIDITY")
            uidvalidity = int(values[0])
            if uidvalidity < 1:
                raise RuntimeError("The inbox provided invalid UIDVALIDITY")
        matches = checked(mail.uid("SEARCH", None, criterion))
        uids = matches[0].split() if matches and matches[0] else []
        selected = [
            uid for uid in sorted(uids, key=int, reverse=True)
            if (uidvalidity, int(uid)) not in (exclude_ids or set())
        ][:limit]
        for uid in selected:
            fetched = checked(mail.uid("FETCH", uid, "(BODY.PEEK[])"))
            raw = next((item[1] for item in fetched if isinstance(item, tuple)), None)
            if raw is None:
                raise RuntimeError(f"Message UID {uid.decode()} is no longer available; retry the read")
            message = BytesParser(policy=policy.default).parsebytes(raw)
            body = message.get_body(preferencelist=("html", "plain"))
            record = {
                "subject": str(message.get("Subject", "")),
                "sender": str(message.get("From", "")),
                "date": str(message.get("Date", "")),
                "body": body.get_content() if body is not None else "",
            }
            if include_metadata:
                record.update(
                    account=username,
                    mailbox="INBOX",
                    uidvalidity=uidvalidity,
                    uid=int(uid),
                    message_id=str(message["Message-ID"]) if message["Message-ID"] else None,
                )
            yield record
