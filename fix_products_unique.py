"""Run once on server: python fix_products_unique.py
Removes global UNIQUE on products.pdf_name so each user can have same products.
Then clones Bilal template into any user who has zero products.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import engine, SessionLocal, init_db
from sqlalchemy import text
from models import User, Product
from auth import clone_template_for_user, get_template_user_id

def rebuild_products():
    with engine.connect() as conn:
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
            print("No products table")
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
        conn.commit()
        print("products table rebuilt without UNIQUE(pdf_name)")

def fill_empty_users():
    db = SessionLocal()
    try:
        for u in db.query(User).all():
            n = db.query(Product).filter(Product.user_id == u.id).count()
            print(f"user {u.id} {u.mobile}: {n} products")
            if n == 0:
                print(f"  cloning template for {u.mobile}...")
                clone_template_for_user(db, u.id)
                n2 = db.query(Product).filter(Product.user_id == u.id).count()
                print(f"  now {n2} products")
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
    rebuild_products()
    fill_empty_users()
    print("DONE")
