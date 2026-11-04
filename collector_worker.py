from contextlib import closing
import logging
import os
import time

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db.database import get_engine
from db.models import Email, EmailTask
from html_parser import HTML_parser
from read_emails import iter_emails


COLLECTION_INTERVAL_SECONDS = 600
EMAIL_LIMIT = 10
logger = logging.getLogger(__name__)


# Collects new unread emails without changing read flags or labels. Parses each
# fetched body outside the reader and the database transaction, then atomically
# saves the email and its pending task before fetching the next email.
def collect_emails(engine: Engine, *, username: str, password: str) -> int:
    with Session(engine) as session:
        known_ids = {
            (uidvalidity, uid)
            for uidvalidity, uid in session.execute(
                select(Email.uidvalidity, Email.uid).where(
                    Email.account == username, Email.mailbox == "INBOX",
                )
            )
        }

    queued = 0
    with closing(iter_emails(
        {"status": "unread", "limit": EMAIL_LIMIT},
        username=username,
        password=password,
        include_metadata=True,
        exclude_ids=known_ids,
    )) as emails:
        for record in emails:
            record = {**record, "body": HTML_parser(record["body"])}
            with Session(engine) as session, session.begin():
                email_id = session.scalar(
                    insert(Email).values(**record)
                    .on_conflict_do_nothing(constraint="uq_emails_mailbox_identity")
                    .returning(Email.id)
                )
                if email_id is not None:
                    session.add(EmailTask(email_id=email_id, status="pending"))
            if email_id is not None:
                queued += 1
                logger.info("Queued email_id=%s", email_id)
    logger.info("Collection finished: queued=%s", queued)
    return queued


# Starts the collector immediately and waits ten minutes between cycles.
# Credentials come from .env or the environment. No CLI options are defined.
# Cycle failures are logged, then collection is attempted at the next interval.
def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = None
    try:
        engine = get_engine()
        username = os.environ.get("BRIDGE_USERNAME")
        password = os.environ.get("BRIDGE_PASSWORD")
        if not username or not password:
            raise ValueError("Set BRIDGE_USERNAME and BRIDGE_PASSWORD in .env")
        while True:
            try:
                logger.info("Collection started")
                collect_emails(engine, username=username, password=password)
            except Exception:
                logger.exception("Collection failed")
            time.sleep(COLLECTION_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Collector stopped")
        return 130
    except Exception:
        logger.exception("Collector startup failed")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
