import argparse
import imaplib
import json
from pathlib import Path
import random
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if __package__ in (None, ""):
    sys.path.insert(0, str(PROJECT_ROOT))

from read_emails import read_emails
from html_parser import HTML_parser


# Fetches up to 400 emails, parses their bodies, and keeps the first 350 unique
# records for separate development (100) and test (250) datasets.
def create_datasets(
    *,
    username: str,
    password: str,
    port: int = 1143,
    seed: int = 42,
) -> dict[str, Path]:
    """Save parsed email records as JSON arrays under tests/fixtures/.

    Includes both read and unread messages. Each record retains subject, sender,
    and date from read_emails(), with body processed by HTML_parser() and
    expected set to {"sender_type": None} for manual annotation. Expected answers
    must be excluded from future LLM inputs and used only for evaluation.
    The same fetched records and shuffle seed produce the same datasets.

    Deduplication preserves fetch order, keeping the newest copy of each record.
    The first 350 unique records are selected before shuffling and splitting.
    Each selected record receives an id from 1 to 350 before shuffling, unique
    across both datasets. These are dataset IDs, not persistent mailbox IDs.
    Raises an error before writing if fewer than 350 unique records remain
    or either output file already exists.
    Returns the paths of the two created files. Does not modify the inbox.
    """
    fixtures = PROJECT_ROOT / "data" / "datasets"
    paths = {
        "development": fixtures / "development_emails.json",
        "test": fixtures / "test_emails.json",
    }
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("A dataset file already exists; existing datasets will not be overwritten")

    emails = read_emails(
        {"limit": 400},
        username=username,
        password=password,
        port=port,
    )
    emails = [
        {
            **email,
            "body": HTML_parser(email["body"]),
            "expected": {"sender_type": None},
        }
        for email in emails
    ]
    unique_emails = {}
    for email in emails:
        key = json.dumps(email, sort_keys=True)
        if key not in unique_emails:
            unique_emails[key] = email
    if len(unique_emails) < 350:
        raise ValueError(
            f"Expected at least 350 unique emails, found {len(unique_emails)} "
            f"among {len(emails)} fetched emails; no datasets were written"
        )
    emails = [
        {"id": index, **email}
        for index, email in enumerate(list(unique_emails.values())[:350], start=1)
    ]

    random.Random(seed).shuffle(emails)
    datasets = {"development": emails[:100], "test": emails[100:]}

    fixtures.mkdir(parents=True, exist_ok=True)
    for name, records in datasets.items():
        with paths[name].open("x", encoding="utf-8") as output:
            json.dump(records, output, ensure_ascii=False, indent=2)
            output.write("\n")

    return paths


# Reads CLI options and creates the datasets using the supplied Bridge credentials.
def main():
    parser = argparse.ArgumentParser(description="Create 100-email development and 250-email test datasets.")
    parser.add_argument("--username", required=True, help="Proton Mail Bridge username")
    parser.add_argument("--password", required=True, help="Proton Mail Bridge password")
    parser.add_argument("--port", type=int, default=1143, help="Bridge IMAP port (default: 1143)")
    parser.add_argument("--seed", type=int, default=42, help="Shuffle seed (default: 42)")
    args = parser.parse_args()

    try:
        paths = create_datasets(
            username=args.username,
            password=args.password,
            port=args.port,
            seed=args.seed,
        )
    except (OSError, ValueError, RuntimeError, imaplib.IMAP4.error) as error:
        parser.exit(1, f"Error: {error}\n")
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
