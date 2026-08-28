"""Mobile + PIN authentication helpers."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime
from typing import Optional

from fastapi import Request, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from models import User

SESSION_SECRET = os.environ.get("SALES_SESSION_SECRET") or "sales-dashboard-change-me-in-production"
SESSION_KEY = "user_id"

# Template account — all new/empty users get a copy of this member's products + monthly setup
TEMPLATE_MOBILE = "03368382799"


def normalize_mobile(mobile: str) -> str:
    digits = re.sub(r"\D", "", (mobile or "").strip())
    return digits


def hash_pin(pin: str, salt: Optional[str] = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt, hexdigest = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return hmac.compare_digest(dk.hex(), hexdigest)


def get_session_user_id(request: Request) -> Optional[int]:
    uid = request.session.get(SESSION_KEY)
    if uid is None:
        return None
    try:
        return int(uid)
    except (TypeError, ValueError):
        return None


def set_session_user(request: Request, user: User) -> None:
    request.session[SESSION_KEY] = user.id
    request.session["mobile"] = user.mobile
    request.session["name"] = user.name or ""


def clear_session(request: Request) -> None:
    request.session.clear()


def get_current_user(request: Request, db: Session) -> Optional[User]:
    uid = get_session_user_id(request)
    if not uid:
        return None
    return db.query(User).filter(User.id == uid).first()


def require_user(request: Request, db: Session) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def seed_default_products(db: Session, user_id: int) -> None:
    from models import Product
    if db.query(Product).filter(Product.user_id == user_id).count() > 0:
        return
    defaults = [
        ("BRONOCHOL COUGH S", "Bronochol Syp", "19798", 5000, 1),
        ("CALIPTROL 10MG TA", "Caliptrol 10mg", "31560", 500, 2),
        ("CALIPTROL 20MG TA", "Caliptrol 20mg", "31561", 500, 3),
        ("ESOMEGA 20MG CAPS", "Esomega 20mg", "19793", 2000, 4),
        ("ESOMEGA 40MG CAPS", "Esomega 40mg", "19794", 2000, 5),
        ("LEVO 250MG TABLET", "Levo 250mg", "19789", 3000, 6),
        ("LEVO 500MG TABLET", "Levo 500mg", "19790", 1000, 7),
        ("ULTRAHEAT RUB CRE", "Ultraheat", "32815", 500, 8),
        ("HELICURE TABLET/C", "Helicure", "19795", 500, 9),
    ]
    for pdf_name, display, code, tgt, order in defaults:
        db.add(Product(
            user_id=user_id,
            pdf_name=pdf_name,
            display_name=display,
            product_code=code,
            monthly_target=tgt,
            sort_order=order,
            is_active=True,
        ))
    try:
        db.commit()
    except Exception:
        db.rollback()


def claim_orphan_data(db: Session, user_id: int) -> None:
    from models import Product, MonthlyConfig, Report, MonthOtherCity
    for model in (Product, MonthlyConfig, Report, MonthOtherCity):
        db.query(model).filter(model.user_id.is_(None)).update(
            {model.user_id: user_id}, synchronize_session=False
        )
    db.commit()


def get_template_user_id(db: Session, exclude_user_id: int) -> Optional[int]:
    from models import Product
    bilal = db.query(User).filter(User.mobile == TEMPLATE_MOBILE).first()
    if bilal and bilal.id != exclude_user_id:
        n = db.query(Product).filter(Product.user_id == bilal.id).count()
        if n > 0:
            return bilal.id
        orphans = db.query(Product).filter(Product.user_id.is_(None)).count()
        if orphans > 0:
            claim_orphan_data(db, bilal.id)
            return bilal.id
    row = (
        db.query(Product.user_id)
        .filter(Product.user_id.isnot(None), Product.user_id != exclude_user_id)
        .order_by(Product.user_id.asc())
        .first()
    )
    if row:
        return row[0]
    return None


def ensure_products_table_multiuser(db: Session) -> None:
    from database import engine, _rebuild_products_table
    import os
    marker = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".products_multiuser_ok")
    try:
        with engine.connect() as conn:
            _rebuild_products_table(conn)
            conn.commit()
        open(marker, "w").write("ok")
    except Exception:
        pass


def clone_template_for_user(db: Session, user_id: int) -> None:
    from models import Product, MonthlyConfig, ProductMonthlyTarget

    if db.query(Product).filter(Product.user_id == user_id).count() > 0:
        return

    ensure_products_table_multiuser(db)

    template_uid = get_template_user_id(db, exclude_user_id=user_id)

    bilal = db.query(User).filter(User.mobile == TEMPLATE_MOBILE).first()
    if bilal and db.query(Product).filter(Product.user_id == bilal.id).count() == 0:
        if db.query(Product).filter(Product.user_id.is_(None)).count() > 0:
            claim_orphan_data(db, bilal.id)
            template_uid = bilal.id

    if not template_uid:
        seed_default_products(db, user_id)
        return

    template_products = (
        db.query(Product)
        .filter(Product.user_id == template_uid)
        .order_by(Product.sort_order, Product.id)
        .all()
    )
    if not template_products:
        seed_default_products(db, user_id)
        return

    id_map = {}
    for p in template_products:
        np = Product(
            user_id=user_id,
            pdf_name=p.pdf_name,
            display_name=p.display_name,
            product_code=p.product_code,
            monthly_target=float(p.monthly_target or 0),
            sort_order=int(p.sort_order or 0),
            is_active=True if p.is_active is None else bool(p.is_active),
        )
        db.add(np)
        try:
            db.flush()
            id_map[p.id] = np.id
        except IntegrityError:
            db.rollback()
            ensure_products_table_multiuser(db)
            id_map = {}
            for p2 in template_products:
                np2 = Product(
                    user_id=user_id,
                    pdf_name=p2.pdf_name,
                    display_name=p2.display_name,
                    product_code=p2.product_code,
                    monthly_target=float(p2.monthly_target or 0),
                    sort_order=int(p2.sort_order or 0),
                    is_active=True,
                )
                db.add(np2)
                try:
                    db.flush()
                    id_map[p2.id] = np2.id
                except IntegrityError:
                    db.rollback()
                    seed_default_products(db, user_id)
                    return
            break

    cfg = (
        db.query(MonthlyConfig)
        .filter(MonthlyConfig.user_id == template_uid)
        .order_by(MonthlyConfig.year.desc(), MonthlyConfig.month.desc())
        .first()
    )
    if not cfg:
        cfg = (
            db.query(MonthlyConfig)
            .filter(MonthlyConfig.user_id.is_(None))
            .order_by(MonthlyConfig.year.desc(), MonthlyConfig.month.desc())
            .first()
        )
        if cfg and bilal:
            cfg.user_id = bilal.id
            db.flush()

    if cfg and id_map:
        existing = db.query(MonthlyConfig).filter(
            MonthlyConfig.user_id == user_id,
            MonthlyConfig.year == cfg.year,
            MonthlyConfig.month == cfg.month,
        ).first()
        if not existing:
            ncfg = MonthlyConfig(
                user_id=user_id,
                year=cfg.year,
                month=cfg.month,
                psp_name=cfg.psp_name or "",
                town=cfg.town or "",
                monthly_sales_target=float(cfg.monthly_sales_target or 0),
                working_days=int(cfg.working_days or 26),
                per_day_target_override=cfg.per_day_target_override,
                zero_qty_display=cfg.zero_qty_display or "dash",
            )
            db.add(ncfg)
            db.flush()
            for pt in list(cfg.product_targets or []):
                new_pid = id_map.get(pt.product_id)
                if not new_pid:
                    continue
                db.add(ProductMonthlyTarget(
                    monthly_config_id=ncfg.id,
                    product_id=new_pid,
                    target_qty=float(pt.target_qty or 0),
                ))

    try:
        db.commit()
    except Exception:
        db.rollback()
        if db.query(Product).filter(Product.user_id == user_id).count() == 0:
            seed_default_products(db, user_id)
