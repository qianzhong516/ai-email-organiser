import argparse

from sqlalchemy.exc import SQLAlchemyError

from database import get_engine
from models import Base


# Creates missing application tables without dropping or altering existing ones.
# Future changes to existing tables require schema migrations, not create_all.
def main():
    parser = argparse.ArgumentParser(description="Create the emails, email_tasks, and results tables in PostgreSQL.")
    parser.parse_args()
    engine = None
    try:
        engine = get_engine()
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
        print("Database initialized: emails, email_tasks, results.")
    except (ValueError, SQLAlchemyError) as error:
        parser.exit(1, f"Database initialization failed: {error}\n")
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
