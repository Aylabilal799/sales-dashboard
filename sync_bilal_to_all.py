#!/usr/bin/env python3
"""ONE TIME: copy Bilal (03368382799) products + monthly setup to every other user.
Run:  cd /root/sales-dashboard && source venv/bin/activate && python sync_bilal_to_all.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from database import engine, SessionLocal, init_db, _rebuild_products_table
from models import User, Product, MonthlyConfig, ProductMonthlyTarget

TEMPLATE_MOBILE = "03368382799"

def main():
    init_db()
    print("=== 1) Rebuild products table (remove UNIQUE) ===")
    with engine.connect() as conn:
        _rebuild_products_table(conn)
        conn.commit()
    marker = os.path.join(os.path.dirname(__file__), ".products_multiuser_ok")
    open(marker, "w").write("ok")
    print("    done")

    db = SessionLocal()
    try:
        print("=== 2) Users ===")
        users = db.query(User).all()
        for u in users:
            n = db.query(Product).filter(Product.user_id == u.id).count()
            print(f"    id={u.id} mobile={u.mobile} products={n}")

        bilal = db.query(User).filter(User.mobile == TEMPLATE_MOBILE).first()
        if not bilal:
            bilal = db.query(User).filter(User.mobile.like("%3368382799")).first()
        if not bilal:
            print("ERROR: Bilal user not found!")
            return

        orphans = db.query(Product).filter(Product.user_id.is_(None)).all()
        if orphans:
            print(f"=== 3) Assign {len(orphans)} orphan products to Bilal ===")
            for p in orphans:
                p.user_id = bilal.id
            db.commit()

        src_products = db.query(Product).filter(Product.user_id == bilal.id).order_by(Product.sort_order, Product.id).all()
        print(f"=== 4) Bilal has {len(src_products)} products ===")
        if not src_products:
            print("ERROR: Bilal has no products to copy!")
            return

        src_cfg = (
            db.query(MonthlyConfig)
            .filter(MonthlyConfig.user_id == bilal.id)
            .order_by(MonthlyConfig.year.desc(), MonthlyConfig.month.desc())
            .first()
        )
        if not src_cfg:
            src_cfg = db.query(MonthlyConfig).order_by(MonthlyConfig.year.desc(), MonthlyConfig.month.desc()).first()
            if src_cfg and src_cfg.user_id is None:
                src_cfg.user_id = bilal.id
                db.commit()
        print(f"    monthly config: {src_cfg.year}-{src_cfg.month:02d}" if src_cfg else "    no monthly config")

        for u in users:
            if u.id == bilal.id:
                continue
            existing = db.query(Product).filter(Product.user_id == u.id).count()
            if existing > 0:
                print(f"=== skip {u.mobile} (already has {existing} products) ===")
                continue

            print(f"=== COPY → {u.mobile} (id={u.id}) ===")
            id_map = {}
            for p in src_products:
                np = Product(
                    user_id=u.id,
                    pdf_name=p.pdf_name,
                    display_name=p.display_name,
                    product_code=p.product_code,
                    monthly_target=p.monthly_target or 0,
                    sort_order=p.sort_order or 0,
                    is_active=True if p.is_active is None else bool(p.is_active),
                )
                db.add(np)
                db.flush()
                id_map[p.id] = np.id
            print(f"    products copied: {len(id_map)}")

            if src_cfg:
                exists_cfg = db.query(MonthlyConfig).filter(
                    MonthlyConfig.user_id == u.id,
                    MonthlyConfig.year == src_cfg.year,
                    MonthlyConfig.month == src_cfg.month,
                ).first()
                if not exists_cfg:
                    ncfg = MonthlyConfig(
                        user_id=u.id,
                        year=src_cfg.year,
                        month=src_cfg.month,
                        psp_name=src_cfg.psp_name or "",
                        town=src_cfg.town or "",
                        monthly_sales_target=src_cfg.monthly_sales_target or 0,
                        working_days=src_cfg.working_days or 26,
                        per_day_target_override=src_cfg.per_day_target_override,
                        zero_qty_display=src_cfg.zero_qty_display or "dash",
                    )
                    db.add(ncfg)
                    db.flush()
                    for pt in src_cfg.product_targets:
                        new_pid = id_map.get(pt.product_id)
                        if new_pid:
                            db.add(ProductMonthlyTarget(
                                monthly_config_id=ncfg.id,
                                product_id=new_pid,
                                target_qty=pt.target_qty or 0,
                            ))
                    print(f"    monthly config copied")
            db.commit()
            print(f"    OK {u.mobile}")

        print("=== FINAL ===")
        for u in db.query(User).all():
            n = db.query(Product).filter(Product.user_id == u.id).count()
            c = db.query(MonthlyConfig).filter(MonthlyConfig.user_id == u.id).count()
            print(f"    {u.mobile}: products={n} months={c}")
        print("DONE")
    except Exception as e:
        db.rollback()
        print("FAILED:", type(e).__name__, e)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
