from datetime import datetime, timezone
import os
import time

from heartbeat_settings import HEARTBEAT_PATH

HEARTBEAT_TIMEOUT_SECONDS = 60
CHECK_INTERVAL_SECONDS = 30


# Checks the worker's heartbeat using the same monotonic clock as its writer.
# Returns 0 when fresh, or 1 when missing, invalid,
# or at least 60 seconds old. This measures liveness, not LLM progress.
# Logs UTC check time and the heartbeat file's last-write time. Read metadata
# from the opened file so an atomic heartbeat replacement cannot mix versions.
def check_classifier_heartbeat() -> int:
    check_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with HEARTBEAT_PATH.open(encoding="utf-8") as heartbeat:
            last_heartbeat = float(heartbeat.read())
            latest_heartbeat = datetime.fromtimestamp(
                os.fstat(heartbeat.fileno()).st_mtime, timezone.utc,
            ).isoformat(timespec="seconds")
    except (OSError, ValueError):
        print(
            f"Classifier heartbeat is missing or invalid: check_time={check_time} latest_heartbeat=unknown",
            flush=True,
        )
        return 1
    timestamps = f"check_time={check_time} latest_heartbeat={latest_heartbeat}"
    age = time.monotonic() - last_heartbeat
    if not 0 <= age < HEARTBEAT_TIMEOUT_SECONDS:
        print(f"Classifier heartbeat is stale or invalid: {timestamps} age={age:.1f}s", flush=True)
        return 1
    print(f"Classifier heartbeat is fresh: {timestamps} age={age:.1f}s", flush=True)
    return 0


# Runs immediately and every 30 seconds thereafter. A failed heartbeat is logged
# without stopping the monitor, so it can observe subsequent recovery.
def main() -> int:
    try:
        while True:
            check_classifier_heartbeat()
            time.sleep(CHECK_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("Health checks stopped", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
