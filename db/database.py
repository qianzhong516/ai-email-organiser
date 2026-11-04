import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Engine, URL, create_engine


# Builds a synchronous PostgreSQL engine using .env or overriding environment
# variables. URL.create handles special characters in database passwords.
# Creating the engine does not connect until the caller executes an operation.
def get_engine() -> Engine:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ValueError(f"Missing database settings: {', '.join(missing)}")
    url = URL.create(
        "postgresql+psycopg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ["POSTGRES_DB"],
    )
    return create_engine(url, pool_pre_ping=True, hide_parameters=True, connect_args={"connect_timeout": 10})
