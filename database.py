import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from models import Base

_BASE = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(_BASE, "sales_dashboard.db")
DATABASE_URL = f"sqlite:///{_DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _rebuild_products_table(conn) -> None:
    """Rebuild products WITHOUT unique on pdf_name. FK off during swap."""
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    conn.execute(text("DROP TABLE IF EXISTS products_new"))
    conn.execute(text("""
        CREATE TABLE products_new (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER,
            pdf_name VARCHAR(255) NOT NULL,
            display_name VARCHAR(255) NOT NULL,
            product_code VARCHAR(50),
            monthly_target FLOAT DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME,
            updated_at DATETIME
        )
    """))
    old_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(products)")).fetchall()]
    if not old_cols:
        conn.execute(text("DROP TABLE IF EXISTS products_new"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
        return
    if "user_id" in old_cols:
        conn.execute(text("""
            INSERT INTO products_new
            (id, user_id, pdf_name, display_name, product_code, monthly_target, sort_order, is_active, created_at, updated_at)
            SELECT id, user_id, pdf_name, display_name, product_code, monthly_target, sort_order, is_active, created_at, updated_at
            FROM products
        """))
    else:
        conn.execute(text("""
            INSERT INTO products_new
            (id, user_id, pdf_name, display_name, product_code, monthly_target, sort_order, is_active, created_at, updated_at)
            SELECT id, NULL, pdf_name, display_name, product_code, monthly_target, sort_order, is_active, created_at, updated_at
            FROM products
        """))
    conn.execute(text("DROP TABLE products"))
    conn.execute(text("ALTER TABLE products_new RENAME TO products"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_products_user_id ON products (user_id)"))
    conn.execute(text("PRAGMA foreign_keys=ON"))


def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        try:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(report_products)")).fetchall()]
            for col, typ in [
                ("tp", "REAL DEFAULT 0"),
                ("today_value", "REAL DEFAULT 0"),
                ("mtd_value", "REAL DEFAULT 0"),
            ]:
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE report_products ADD COLUMN {col} {typ}"))

            for table in ("products", "monthly_configs", "reports", "month_other_city"):
                tcols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()]
                if tcols and "user_id" not in tcols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER"))

            marker = os.path.join(_BASE, ".products_multiuser_ok")
            if not os.path.exists(marker):
                try:
                    _rebuild_products_table(conn)
                    with open(marker, "w") as f:
                        f.write("ok")
                except Exception:
                    pass

            conn.commit()
        except Exception:
            pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
