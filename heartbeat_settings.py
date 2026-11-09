import os
from pathlib import Path


# Host execution uses /tmp; Compose points both containers at a shared volume.
HEARTBEAT_PATH = Path(os.environ.get("CLASSIFIER_HEARTBEAT_PATH", "/tmp/email-classifier-heartbeat"))
