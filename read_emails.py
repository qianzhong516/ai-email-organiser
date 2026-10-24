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
) -> list[dict[str, str]]:
    """Read emails through Proton Mail Bridge at 127.0.0.1 using STARTTLS.

    Supported filters: {"status": "read" | "unread", "limit": 50}.
    Omitting status includes both read and unread messages. Omitting limit
    defaults to 50. Limit must be a positive integer. Unsupported keys and
    values raise an error.

    Returns newest arrivals first, as dictionaries with subject, sender, date,
    and body. Date is the original Date header (the sender's stated sending
    time, including any timezone), or an empty string if absent. It is not the
    inbox arrival time. The body prefers HTML, falling back to plain text or an empty string
    if neither exists. MIME transfer encoding and character encoding are decoded;
    the decoded body is otherwise unchanged. Attachments are not returned.
    """
    if not isinstance(filters, dict):
        raise TypeError("filters must be a JSON object represented as a dictionary")
    if set(filters) - {"status", "limit"}:
        raise ValueError("Only the 'status' and 'limit' filters are currently supported")
    if "status" in filters and filters["status"] not in ("read", "unread"):
        raise ValueError("status must be 'read' or 'unread'")
    limit = filters.get("limit", 50)
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")

    criterion = {"read": "SEEN", "unread": "UNSEEN"}.get(filters.get("status"), "ALL")

    # Stop on a failed IMAP command instead of returning an incomplete result.
    def checked(result):
        status, data = result
        if status != "OK":
            raise RuntimeError(f"IMAP command failed: {data!r}")
        return data

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Accept Bridge's self-signed cert on loopback only.

    emails = []
    with imaplib.IMAP4("127.0.0.1", port, timeout=30) as mail:
        checked(mail.starttls(ssl_context=context))
        checked(mail.login(username, password))
        checked(mail.select("INBOX", readonly=True))
        matches = checked(mail.uid("SEARCH", None, criterion))
        uids = matches[0].split() if matches and matches[0] else []
        for uid in sorted(uids, key=int, reverse=True)[:limit]:
            fetched = checked(mail.uid("FETCH", uid, "(BODY.PEEK[])"))
            raw = next((item[1] for item in fetched if isinstance(item, tuple)), None)
            if raw is None:
                raise RuntimeError(f"Message UID {uid.decode()} is no longer available; retry the read")
            message = BytesParser(policy=policy.default).parsebytes(raw)
            body = message.get_body(preferencelist=("html", "plain"))
            emails.append({
                "subject": str(message.get("Subject", "")),
                "sender": str(message.get("From", "")),
                "date": str(message.get("Date", "")),
                "body": body.get_content() if body is not None else "",
            })
    return emails
