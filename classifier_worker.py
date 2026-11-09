from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import time

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from classify_emails import classify_email_record
from db.database import get_engine
from db.models import Email, EmailTask, Result


CHECK_INTERVAL_SECONDS = 300
PROMPT_PATH = Path(__file__).resolve().parent / "prompting" / "sender_type.txt"
MODEL = "qwen2.5:7b"
OLLAMA_URL = "http://127.0.0.1:11434"
REQUEST_TIMEOUT_SECONDS = 900
logger = logging.getLogger(__name__)


# Claims one pending task and commits processing/started_at before calling the
# LLM. Assumes one classifier worker; no explicit row locking is used. Returns
# completed/failed, or None when no pending tasks remain. Result and completion
# are saved together in a separate transaction after the LLM request finishes.
def classify_next_task(engine: Engine) -> str | None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    if not prompt.strip():
        raise ValueError("The classification prompt must not be empty")
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    with Session(engine) as session, session.begin():
        task = session.scalar(
            select(EmailTask).where(EmailTask.status == "pending")
            .order_by(EmailTask.created_at, EmailTask.id).limit(1)
        )
        if task is None:
            return None
        email = session.get(Email, task.email_id)
        if email is None:
            raise RuntimeError(f"Missing email for task {task.id}")
        record = {key: getattr(email, key) for key in ("id", "subject", "sender", "date", "body")}
        task_id, email_id = task.id, task.email_id
        task.status = "processing"
        task.started_at = datetime.now(timezone.utc)
        task.last_error = None
        task.completed_at = None

    logger.info("Classification started: task_id=%s email_id=%s", task_id, email_id)
    try:
        completed = classify_email_record(
            record, prompt=prompt, model=MODEL,
            ollama_url=os.environ.get("OLLAMA_URL", OLLAMA_URL), timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as error:
        with Session(engine) as session, session.begin():
            task = session.get(EmailTask, task_id)
            task.status = "failed"
            task.last_error = str(error)
            task.completed_at = datetime.now(timezone.utc)
        logger.exception("Classification failed: task_id=%s email_id=%s", task_id, email_id)
        return "failed"

    with Session(engine) as session, session.begin():
        session.add(Result(
            email_id=email_id,
            task_id=task_id,
            sender_type=completed["prediction"]["sender_type"],
            explanation=completed["prediction"]["explanation"],
            model=MODEL,
            prompt_hash=prompt_hash,
            execution_time_seconds=completed["execution_time_seconds"],
        ))
        task = session.get(EmailTask, task_id)
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
    logger.info(
        "Classification completed: task_id=%s email_id=%s sender_type=%s execution_time_seconds=%s",
        task_id, email_id, completed["prediction"]["sender_type"], completed["execution_time_seconds"],
    )
    return "completed"


# Checks immediately on startup and drains the pending queue one task at a time.
# Waits five minutes when idle or after a worker/database error. Individual task
# failures do not pause the remaining queue. No CLI options or automatic task
# retries/recovery are provided; interrupted tasks may remain processing.
def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = None
    try:
        engine = get_engine()
        while True:
            try:
                outcome = classify_next_task(engine)
                if outcome is not None:
                    continue
                logger.info("No pending tasks; checking again in %s seconds", CHECK_INTERVAL_SECONDS)
            except Exception:
                logger.exception("Classifier worker cycle failed")
            time.sleep(CHECK_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Classifier stopped")
        return 130
    except Exception:
        logger.exception("Classifier startup failed")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
