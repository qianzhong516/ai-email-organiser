from pathlib import Path
import time


HEARTBEAT_PATH = Path("/tmp/email-classifier-heartbeat")
HEARTBEAT_TIMEOUT_SECONDS = 60


# Checks the worker's heartbeat using the same monotonic clock as its writer.
# Returns Docker health-check exit code 0 when fresh, or 1 when missing, invalid,
# or at least 60 seconds old. This measures liveness, not LLM progress.
def main() -> int:
    try:
        last_heartbeat = float(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Classifier heartbeat is missing or invalid")
        return 1
    age = time.monotonic() - last_heartbeat
    if not 0 <= age < HEARTBEAT_TIMEOUT_SECONDS:
        print(f"Classifier heartbeat is stale or invalid: age={age:.1f}s")
        return 1
    print(f"Classifier heartbeat is fresh: age={age:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
