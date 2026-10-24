from unittest.mock import patch

from read_emails import read_emails


# Checks that every returned email includes the required fields. A simulated
# IMAP connection supplies messages, so this test does not access your inbox.
def test_read_emails():
    raw_email = (
        b"Subject: Example email\r\n"
        b"From: sender@example.com\r\n"
        b"Date: Sat, 24 Oct 2026 10:00:00 +1100\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\nExample body."
    )

    with patch("read_emails.imaplib.IMAP4") as imap:
        mail = imap.return_value.__enter__.return_value
        mail.starttls.return_value = ("OK", [])
        mail.login.return_value = ("OK", [])
        mail.select.return_value = ("OK", [b"2"])
        mail.uid.side_effect = [
            ("OK", [b"1 2"]),
            ("OK", [(b"2 (BODY[])", raw_email)]),
            ("OK", [(b"1 (BODY[])", raw_email)]),
        ]

        results = read_emails(
            {"limit": 2},
            username="test@example.com",
            password="test-password",
        )

    assert results, "Expected emails to check; an empty result cannot verify fields"
    for email in results:
        assert {"subject", "sender", "date", "body"}.issubset(email), (
            f"Missing required fields in email: {email}"
        )


if __name__ == "__main__":
    test_read_emails()
