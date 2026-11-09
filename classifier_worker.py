from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import threading
import time

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from classify_emails import classify_email_record
from heartbeat_settings import HEARTBEAT_PATH
from db.database import get_engine
from db.models import Email, EmailTask, Result


CHECK_INTERVAL_SECONDS = 300
HEARTBEAT_INTERVAL_SECONDS = 15
PROMPT_PATH = Path(__file__).resolve().parent / "prompting" / "sender_type.txt"
MODEL = "qwen2.5:7b"
OLLAMA_URL = "http://127.0.0.1:11434"
REQUEST_TIMEOUT_SECONDS = 900
logger = logging.getLogger(__name__)


# Publishes a monotonic timestamp with an atomic rename so Docker cannot read a
# partially written heartbeat. This temporary file is not task recovery state.
def write_heartbeat() -> None:
    temporary = HEARTBEAT_PATH.with_suffix(".tmp")
    temporary.write_text(str(time.monotonic()), encoding="utf-8")
    temporary.replace(HEARTBEAT_PATH)


# Updates the heartbeat while the main thread waits for Ollama or the next poll.
# Event.wait lets shutdown interrupt the 15-second wait immediately. Write errors
# are logged; the unchanged heartbeat will eventually fail Docker's health check.
def heartbeat_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        try:
            write_heartbeat()
        except OSError:
            logger.exception("Classifier heartbeat update failed")


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
    stop_event = threading.Event()
    heartbeat_thread = None
    try:
        engine = get_engine()
        write_heartbeat()
        heartbeat_thread = threading.Thread(
            target=heartbeat_loop, args=(stop_event,), daemon=True,
            name="classifier-heartbeat",
        )
        heartbeat_thread.start()
        logger.info("Heartbeat started: interval=%ss", HEARTBEAT_INTERVAL_SECONDS)
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
        stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=2)
        try:
            HEARTBEAT_PATH.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove classifier heartbeat")
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
