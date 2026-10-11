import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "feereconcile.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

# Connect args for SQLite to allow multi-threaded access in FastAPI
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

# Enable Foreign Key constraints and WAL (Write-Ahead Logging) mode in SQLite, plus self-healing schema checks
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Ensure advance_credit column exists in students table
        cursor.execute("PRAGMA table_info(students)")
        cols = [row[1] for row in cursor.fetchall()]
        if cols and "advance_credit" not in cols:
            cursor.execute("ALTER TABLE students ADD COLUMN advance_credit INTEGER DEFAULT 0")
    except Exception:
        pass
    finally:
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        try:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(students)")).fetchall()]
            if cols and "advance_credit" not in cols:
                conn.execute(text("ALTER TABLE students ADD COLUMN advance_credit INTEGER DEFAULT 0"))
        except Exception:
            pass


def reset_db():
    import app.models  # noqa: F401
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        try:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(students)")).fetchall()]
            if cols and "advance_credit" not in cols:
                conn.execute(text("ALTER TABLE students ADD COLUMN advance_credit INTEGER DEFAULT 0"))
        except Exception:
            pass

