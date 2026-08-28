"""
Sales Dashboard - FastAPI application
Run: uvicorn app:app --host 0.0.0.0 --port 3304
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Request, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc

from database import init_db, get_db, SessionLocal
from models import User, Product, MonthlyConfig, ProductMonthlyTarget, Report, ReportProduct, MonthOtherCity
from pdf_parser import parse_sales_pdf, match_products
from calculations import (
    calc_per_day_target,
    calc_mtd_target,
    calc_achievement,
    calc_sale_value_from_products,
    generate_message,
    days_in_month,
    format_number,
)
from auth import (
    SESSION_SECRET,
    normalize_mobile,
    hash_pin,
    verify_pin,
    get_current_user,
    set_session_user,
    clear_session,
    seed_default_products,
    claim_orphan_data,
    clone_template_for_user,
)

# ---------- App setup ----------
app = FastAPI(title="Sales Dashboard", docs_url=None, redoc_url=None)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

PUBLIC_PATHS = {"/login", "/register", "/static"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or path in ("/login", "/register"):
        return await call_next(request)
    # SessionMiddleware must wrap this; if missing, force login
    if "session" not in request.scope:
        return RedirectResponse("/login", status_code=303)
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


# SessionMiddleware added LAST so it runs FIRST (outermost)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="sales_session",
    max_age=60 * 60 * 24 * 30,
)


@app.on_event("startup")
def on_startup():
    init_db()
    # Force multi-user products table + clone Bilal template into every empty account
    try:
        from database import engine, _rebuild_products_table
        with engine.connect() as conn:
            _rebuild_products_table(conn)
            conn.commit()
    except Exception:
        pass
    db = SessionLocal()
    try:
        from models import User, Product
        from auth import clone_template_for_user, claim_orphan_data, TEMPLATE_MOBILE
        # Attach orphan rows to Bilal if needed
        bilal = db.query(User).filter(User.mobile == TEMPLATE_MOBILE).first()
        if bilal:
            try:
                claim_orphan_data(db, bilal.id)
            except Exception:
                db.rollback()
        for u in db.query(User).all():
            if db.query(Product).filter(Product.user_id == u.id).count() == 0:
                try:
                    clone_template_for_user(db, u.id)
                except Exception:
                    db.rollback()
    finally:
        db.close()


# ---------- Helpers ----------
def get_or_create_monthly(db: Session, year: int, month: int, user_id: int) -> Optional[MonthlyConfig]:
    return db.query(MonthlyConfig).filter(
        MonthlyConfig.user_id == user_id,
        MonthlyConfig.year == year,
        MonthlyConfig.month == month,
    ).first()


def products_as_dicts(db: Session, user_id: int) -> List[dict]:
    rows = db.query(Product).filter(
        Product.user_id == user_id, Product.is_active == True
    ).order_by(Product.sort_order, Product.id).all()
    return [
        {
            "id": p.id,
            "pdf_name": p.pdf_name,
            "display_name": p.display_name,
            "product_code": p.product_code or "",
            "monthly_target": p.monthly_target or 0,
            "sort_order": p.sort_order,
            "is_active": p.is_active,
        }
        for p in rows
    ]


# ---------- Routes ----------

# ---------- Auth ----------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "mode": "login", "error": None, "success": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    db: Session = Depends(get_db),
    mobile: str = Form(...),
    pin: str = Form(...),
):
    mob = normalize_mobile(mobile)
    user = db.query(User).filter(User.mobile == mob).first()
    if not user or not verify_pin(pin.strip(), user.pin_hash):
        return templates.TemplateResponse("login.html", {
            "request": request, "mode": "login", "error": "Invalid mobile number or PIN.",
            "mobile": mobile, "success": None,
        })
    user.last_login = datetime.utcnow()
    db.commit()
    set_session_user(request, user)
    try:
        clone_template_for_user(db, user.id)
    except Exception:
        db.rollback()
    return RedirectResponse("/", status_code=303)


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "mode": "register", "error": None, "success": None})


@app.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(""),
    mobile: str = Form(...),
    pin: str = Form(...),
    pin2: str = Form(...),
):
    mob = normalize_mobile(mobile)
    pin = pin.strip()
    pin2 = pin2.strip()
    err = None
    if len(mob) < 10:
        err = "Enter a valid mobile number (at least 10 digits)."
    elif not pin.isdigit() or not (4 <= len(pin) <= 6):
        err = "PIN must be 4 to 6 digits."
    elif pin != pin2:
        err = "PINs do not match."
    elif db.query(User).filter(User.mobile == mob).first():
        err = "This mobile number is already registered. Please login."
    if err:
        return templates.TemplateResponse("login.html", {
            "request": request, "mode": "register", "error": err,
            "mobile": mobile, "name": name, "success": None,
        })
    user = User(mobile=mob, pin_hash=hash_pin(pin), name=(name or "").strip() or None)
    db.add(user)
    db.commit()
    db.refresh(user)
    # First user claims any old data without user_id
    if db.query(User).count() == 1:
        try:
            claim_orphan_data(db, user.id)
        except Exception:
            db.rollback()
    try:
        clone_template_for_user(db, user.id)
    except Exception:
        db.rollback()
        try:
            seed_default_products(db, user.id)
        except Exception:
            db.rollback()
    set_session_user(request, user)
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    clear_session(request)
    return RedirectResponse("/login", status_code=303)




@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uid = user.id
    latest = db.query(Report).filter(Report.user_id == uid).order_by(desc(Report.report_date)).first()
    recent = db.query(Report).filter(Report.user_id == uid).order_by(desc(Report.report_date)).limit(5).all()
    product_count = db.query(Product).filter(Product.user_id == uid, Product.is_active == True).count()
    config_count = db.query(MonthlyConfig).filter(MonthlyConfig.user_id == uid).count()

    cards = None
    if latest:
        cards = {
            "today_sale": latest.today_sale_value,
            "per_day_target": latest.per_day_target,
            "today_achievement": latest.today_achievement,
            "mtd_sale": latest.mtd_sale_value,
            "mtd_target": latest.mtd_target,
            "mtd_achievement": latest.mtd_achievement,
            "report_date": latest.report_date,
        }

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active": "dashboard",
        "user": user,
        "latest": latest,
        "recent": recent,
        "product_count": product_count,
        "config_count": config_count,
        "cards": cards,
        "format_number": format_number,
    })


@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "active": "upload",
        "user": user,
        "result": None,
        "error": None,
    })


@app.post("/upload", response_class=HTMLResponse)
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uid = user.id
    error = None
    result_data = None

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return templates.TemplateResponse("upload.html", {
            "request": request,
            "active": "upload",
            "user": user,
            "result": None,
            "error": "Please upload a valid PDF file.",
        })

    # Save upload
    safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Parse
    parse_result = parse_sales_pdf(save_path)
    if not parse_result.success:
        return templates.TemplateResponse("upload.html", {
            "request": request,
            "active": "upload",
            "user": user,
            "result": None,
            "error": "PDF parsing failed: " + "; ".join(parse_result.errors),
            "warnings": parse_result.warnings,
        })

    report_date = parse_result.report_date
    year, month = report_date.year, report_date.month

    # Load monthly config
    config = get_or_create_monthly(db, year, month, uid)
    if not config:
        return templates.TemplateResponse("upload.html", {
            "request": request,
            "active": "upload",
            "user": user,
            "result": None,
            "error": f"No Monthly Setup found for {year}-{month:02d}. Please create it first under Monthly Setup.",
            "warnings": parse_result.warnings,
        })

    # Check existing report for same date (this user only)
    existing = db.query(Report).filter(Report.user_id == uid, Report.report_date == report_date).first()
    overwrite_warning = bool(existing)

    # Match products
    configured = products_as_dicts(db, uid)
    # Override monthly targets from ProductMonthlyTarget if present
    targets_map = {}
    for pt in db.query(ProductMonthlyTarget).filter(ProductMonthlyTarget.monthly_config_id == config.id).all():
        targets_map[pt.product_id] = pt.target_qty
    for c in configured:
        if c["id"] in targets_map:
            c["monthly_target"] = targets_map[c["id"]]

    matched, unmatched_pdf, missing = match_products(parse_result.products, configured)

    # Sort matched by configured sort_order
    id_to_order = {c["id"]: c["sort_order"] for c in configured}
    matched.sort(key=lambda m: id_to_order.get(m["product_id"], 999))

    # Carry forward Other City Sales for this month (persists across the whole month)
    other_city_map = {}
    for row in db.query(MonthOtherCity).filter(
        MonthOtherCity.user_id == uid,
        MonthOtherCity.year == year, MonthOtherCity.month == month
    ).all():
        other_city_map[row.product_id] = row.other_city_sales
    # Fallback: latest report in same month
    if not other_city_map:
        prev = (
            db.query(Report)
            .filter(Report.user_id == uid, Report.year == year, Report.month == month)
            .order_by(desc(Report.report_date))
            .first()
        )
        if prev:
            for rp in prev.products:
                if rp.product_id and rp.other_city_sales:
                    other_city_map[rp.product_id] = rp.other_city_sales

    for m in matched:
        pid = m.get("product_id")
        other = float(other_city_map.get(pid, 0) or 0)
        m["other_city_sales"] = other
        mtd = float(m.get("mtd_qty") or 0)
        current = max(0.0, mtd - other)
        m["current_sale"] = current
        tp = float(m.get("tp") or 0)
        today_qty = float(m.get("today_qty") or 0)
        tgt = float(m.get("monthly_target") or 0)
        m["today_value"] = round(today_qty * tp, 2)
        m["mtd_value"] = round(mtd * tp, 2)
        m["current_sale_value"] = round(current * tp, 2)  # used for MTD sale totals/message
        m["target_value"] = round(tgt * tp, 2)  # monthly target qty × TP

    # Today = sum(today_qty × TP)
    # MTD  = sum(current_sale × TP)  ← current sale (after other-city), not raw MTD
    today_sale = calc_sale_value_from_products(matched, "today_qty")
    mtd_sale = calc_sale_value_from_products(matched, "current_sale")

    # Monthly target VALUE from products = Σ (monthly_target_qty × TP)
    # Header MTD Target = this FULL value (same as footer Monthly Target Value)
    product_monthly_target_value = round(sum(float(m.get("target_value") or 0) for m in matched), 2)
    monthly_target_base = product_monthly_target_value if product_monthly_target_value > 0 else float(config.monthly_sales_target or 0)

    # Per-day still from full monthly target / working days
    per_day = calc_per_day_target(
        monthly_target_base,
        config.working_days,
        config.per_day_target_override,
    )
    # MTD Target = FULL monthly target value (NOT pro-rated by day)
    mtd_tgt = monthly_target_base
    today_ach = calc_achievement(today_sale, per_day)
    mtd_ach = calc_achievement(mtd_sale, mtd_tgt)

    # Build message
    msg = generate_message(
        report_date=report_date,
        psp_name=config.psp_name,
        town=config.town,
        per_day_target=per_day,
        today_sale=today_sale,
        today_achievement=today_ach,
        mtd_sale=mtd_sale,
        mtd_target=mtd_tgt,
        mtd_achievement=mtd_ach,
        products=matched,
        zero_display=config.zero_qty_display or "dash",
    )

    result_data = {
        "filename": safe_name,
        "original_filename": file.filename,
        "report_date": report_date.isoformat(),
        "year": year,
        "month": month,
        "today_sale_value": today_sale,
        "mtd_sale_value": mtd_sale,
        "per_day_target": per_day,
        "mtd_target": mtd_tgt,
        "today_achievement": today_ach,
        "mtd_achievement": mtd_ach,
        "psp_name": config.psp_name,
        "town": config.town,
        "zero_display": config.zero_qty_display or "dash",
        "working_days": config.working_days,
        "per_day_target_override": config.per_day_target_override,
        "monthly_target_base": monthly_target_base,
        "product_monthly_target_value": product_monthly_target_value,
        "products": matched,
        "unmatched_pdf": [],  # intentionally hidden – only your product list is used
        "missing_configured": [
            {"display_name": m["display_name"], "pdf_name": m["pdf_name"]}
            for m in missing
        ],
        "generated_message": msg,
        "overwrite_warning": overwrite_warning,
        "existing_report_id": existing.id if existing else None,
        "warnings": parse_result.warnings,
        "config_id": config.id,
    }

    return templates.TemplateResponse("upload.html", {
        "request": request,
        "active": "upload",
        "user": user,
        "result": result_data,
        "error": None,
        "format_number": format_number,
    })


@app.post("/api/save-report")
async def save_report(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "login"}, status_code=401)
    uid = user.id
    data = await request.json()

    report_date = date.fromisoformat(data["report_date"])
    year, month = report_date.year, report_date.month

    # Delete existing if overwrite
    existing = db.query(Report).filter(Report.user_id == uid, Report.report_date == report_date).first()
    if existing:
        db.delete(existing)
        db.flush()

    config = get_or_create_monthly(db, year, month, uid)

    report = Report(
        user_id=uid,
        report_date=report_date,
        year=year,
        month=month,
        monthly_config_id=config.id if config else None,
        filename=data.get("filename", ""),
        today_sale_value=float(data.get("today_sale_value", 0)),
        mtd_sale_value=float(data.get("mtd_sale_value", 0)),
        per_day_target=float(data.get("per_day_target", 0)),
        mtd_target=float(data.get("mtd_target", 0)),
        today_achievement=float(data.get("today_achievement", 0)),
        mtd_achievement=float(data.get("mtd_achievement", 0)),
        generated_message=data.get("generated_message", ""),
    )
    db.add(report)
    db.flush()

    for p in data.get("products", []):
        other = float(p.get("other_city_sales") or 0)
        mtd = float(p.get("mtd_qty") or 0)
        today_qty = float(p.get("today_qty") or 0)
        tp = float(p.get("tp") or 0)
        current = max(0.0, mtd - other)
        today_value = round(today_qty * tp, 2)
        mtd_value = round(mtd * tp, 2)
        pid = p.get("product_id")
        rp = ReportProduct(
            report_id=report.id,
            product_id=pid,
            pdf_name=p.get("pdf_name", ""),
            display_name=p.get("display_name", ""),
            today_qty=today_qty,
            mtd_qty=mtd,
            other_city_sales=other,
            current_sale=current,
            monthly_target=float(p.get("monthly_target") or 0),
            tp=tp,
            today_value=today_value,
            mtd_value=mtd_value,
            matched=bool(p.get("matched", True)),
        )
        db.add(rp)

        # Persist Other City Sales for the whole month
        if pid:
            moc = db.query(MonthOtherCity).filter(
                MonthOtherCity.user_id == uid,
                MonthOtherCity.year == year,
                MonthOtherCity.month == month,
                MonthOtherCity.product_id == pid,
            ).first()
            if moc:
                moc.other_city_sales = other
            else:
                db.add(MonthOtherCity(
                    user_id=uid, year=year, month=month, product_id=pid, other_city_sales=other
                ))

    db.commit()
    return JSONResponse({"ok": True, "report_id": report.id})


@app.post("/api/regenerate-message")
async def regenerate_message(request: Request, db: Session = Depends(get_db)):
    if not get_current_user(request, db):
        return JSONResponse({"error": "login"}, status_code=401)
    data = await request.json()
    products = data.get("products", [])
    # recompute current_sale, values, and totals from qty * tp
    for p in products:
        other = float(p.get("other_city_sales") or 0)
        mtd = float(p.get("mtd_qty") or 0)
        today_qty = float(p.get("today_qty") or 0)
        tp = float(p.get("tp") or 0)
        tgt = float(p.get("monthly_target") or 0)
        current = max(0.0, mtd - other)
        p["current_sale"] = current
        p["today_value"] = round(today_qty * tp, 2)
        p["mtd_value"] = round(mtd * tp, 2)
        p["current_sale_value"] = round(current * tp, 2)
        p["target_value"] = round(tgt * tp, 2)
        p["tp"] = tp

    # MTD sale uses current_sale (after other-city deduction)
    today_sale = calc_sale_value_from_products(products, "today_qty")
    mtd_sale = calc_sale_value_from_products(products, "current_sale")

    # Rebuild monthly target base from products so header stays accurate when TP changes
    product_monthly_target_value = round(sum(float(p.get("target_value") or 0) for p in products), 2)
    monthly_target_base = product_monthly_target_value if product_monthly_target_value > 0 else float(data.get("monthly_target_base") or data.get("mtd_target") or 0)

    # Keep original working_days / day info from client if provided
    working_days = int(data.get("working_days") or 26)
    report_date = date.fromisoformat(data["report_date"])
    dim = days_in_month(report_date.year, report_date.month)
    override = data.get("per_day_target_override")
    override = float(override) if override not in (None, "", 0, "0") else None

    per_day = calc_per_day_target(monthly_target_base, working_days, override)
    # MTD Target = FULL monthly target value (matches footer Monthly Target Value)
    mtd_tgt = monthly_target_base
    today_ach = calc_achievement(today_sale, per_day)
    mtd_ach = calc_achievement(mtd_sale, mtd_tgt)

    msg = generate_message(
        report_date=date.fromisoformat(data["report_date"]),
        psp_name=data["psp_name"],
        town=data["town"],
        per_day_target=per_day,
        today_sale=today_sale,
        today_achievement=today_ach,
        mtd_sale=mtd_sale,
        mtd_target=mtd_tgt,
        mtd_achievement=mtd_ach,
        products=products,
        zero_display=data.get("zero_display", "dash"),
    )
    return JSONResponse({
        "message": msg,
        "products": products,
        "today_sale_value": today_sale,
        "mtd_sale_value": mtd_sale,
        "today_achievement": today_ach,
        "mtd_achievement": mtd_ach,
        "per_day_target": per_day,
        "mtd_target": mtd_tgt,
        "monthly_target_base": monthly_target_base,
        "product_monthly_target_value": product_monthly_target_value,
    })


# ---------- Monthly Setup ----------
@app.get("/monthly", response_class=HTMLResponse)
async def monthly_list(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    uid = user.id
    configs = db.query(MonthlyConfig).filter(MonthlyConfig.user_id == uid).order_by(desc(MonthlyConfig.year), desc(MonthlyConfig.month)).all()
    return templates.TemplateResponse("monthly_setup.html", {
        "request": request,
        "active": "monthly",
        "user": user,
        "configs": configs,
        "edit": None,
        "products": products_as_dicts(db, uid),
    })


@app.get("/monthly/new", response_class=HTMLResponse)
async def monthly_new(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    uid = user.id
    today = date.today()
    return templates.TemplateResponse("monthly_setup.html", {
        "request": request,
        "active": "monthly",
        "user": user,
        "configs": db.query(MonthlyConfig).filter(MonthlyConfig.user_id == uid).order_by(desc(MonthlyConfig.year), desc(MonthlyConfig.month)).all(),
        "edit": {
            "year": today.year,
            "month": today.month,
            "psp_name": "",
            "town": "",
            "monthly_sales_target": 0,
            "working_days": 26,
            "per_day_target_override": None,
            "zero_qty_display": "dash",
            "product_targets": {},
        },
        "products": products_as_dicts(db, uid),
        "is_new": True,
    })


@app.get("/monthly/{config_id}", response_class=HTMLResponse)
async def monthly_edit(request: Request, config_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    uid = user.id
    config = db.query(MonthlyConfig).filter(MonthlyConfig.id == config_id, MonthlyConfig.user_id == uid).first()
    if not config:
        raise HTTPException(404)
    targets = {pt.product_id: pt.target_qty for pt in config.product_targets}
    edit = {
        "id": config.id,
        "year": config.year,
        "month": config.month,
        "psp_name": config.psp_name,
        "town": config.town,
        "monthly_sales_target": config.monthly_sales_target,
        "working_days": config.working_days,
        "per_day_target_override": config.per_day_target_override,
        "zero_qty_display": config.zero_qty_display or "dash",
        "product_targets": targets,
    }
    return templates.TemplateResponse("monthly_setup.html", {
        "request": request,
        "active": "monthly",
        "user": user,
        "configs": db.query(MonthlyConfig).filter(MonthlyConfig.user_id == uid).order_by(desc(MonthlyConfig.year), desc(MonthlyConfig.month)).all(),
        "edit": edit,
        "products": products_as_dicts(db, uid),
        "is_new": False,
    })


@app.post("/monthly/save")
async def monthly_save(
    request: Request,
    db: Session = Depends(get_db),
    config_id: Optional[int] = Form(None),
    year: int = Form(...),
    month: int = Form(...),
    psp_name: str = Form(...),
    town: str = Form(...),
    monthly_sales_target: float = Form(0),
    working_days: int = Form(26),
    per_day_target_override: Optional[str] = Form(None),
    zero_qty_display: str = Form("dash"),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uid = user.id
    form = await request.form()
    override = None
    if per_day_target_override and per_day_target_override.strip():
        try:
            override = float(per_day_target_override)
        except ValueError:
            pass

    if config_id:
        config = db.query(MonthlyConfig).filter(MonthlyConfig.id == config_id, MonthlyConfig.user_id == uid).first()
        if not config:
            raise HTTPException(404)
    else:
        existing = get_or_create_monthly(db, year, month, uid)
        if existing:
            return RedirectResponse(f"/monthly/{existing.id}?error=exists", status_code=303)
        config = MonthlyConfig(user_id=uid, year=year, month=month)
        db.add(config)

    config.psp_name = psp_name.strip()
    config.town = town.strip()
    config.monthly_sales_target = monthly_sales_target
    config.working_days = working_days
    config.per_day_target_override = override
    config.zero_qty_display = zero_qty_display
    db.flush()

    # Product targets
    for key, val in form.items():
        if key.startswith("target_"):
            try:
                pid = int(key.replace("target_", ""))
                qty = float(val) if val else 0.0
            except ValueError:
                continue
            pt = db.query(ProductMonthlyTarget).filter(
                ProductMonthlyTarget.monthly_config_id == config.id,
                ProductMonthlyTarget.product_id == pid,
            ).first()
            if pt:
                pt.target_qty = qty
            else:
                db.add(ProductMonthlyTarget(
                    monthly_config_id=config.id,
                    product_id=pid,
                    target_qty=qty,
                ))
            # also update product default (this user only)
            prod = db.query(Product).filter(Product.id == pid, Product.user_id == uid).first()
            if prod:
                prod.monthly_target = qty

    db.commit()
    return RedirectResponse(f"/monthly/{config.id}?saved=1", status_code=303)


# ---------- Products ----------
@app.get("/products", response_class=HTMLResponse)
async def products_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    products = db.query(Product).filter(Product.user_id == user.id).order_by(Product.sort_order, Product.id).all()
    return templates.TemplateResponse("products.html", {
        "request": request,
        "active": "products",
        "user": user,
        "products": products,
        "edit": None,
    })


@app.get("/products/new", response_class=HTMLResponse)
async def product_new(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    products = db.query(Product).filter(Product.user_id == user.id).order_by(Product.sort_order, Product.id).all()
    return templates.TemplateResponse("products.html", {
        "request": request,
        "active": "products",
        "user": user,
        "products": products,
        "edit": {
            "pdf_name": "",
            "display_name": "",
            "product_code": "",
            "monthly_target": 0,
            "sort_order": len(products) + 1,
            "is_active": True,
        },
        "is_new": True,
    })


@app.get("/products/{product_id}", response_class=HTMLResponse)
async def product_edit(request: Request, product_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    p = db.query(Product).filter(Product.id == product_id, Product.user_id == user.id).first()
    if not p:
        raise HTTPException(404)
    products = db.query(Product).filter(Product.user_id == user.id).order_by(Product.sort_order, Product.id).all()
    return templates.TemplateResponse("products.html", {
        "request": request,
        "active": "products",
        "user": user,
        "products": products,
        "edit": p,
        "is_new": False,
    })


@app.post("/products/save")
async def product_save(
    request: Request,
    db: Session = Depends(get_db),
    product_id: Optional[int] = Form(None),
    pdf_name: str = Form(...),
    display_name: str = Form(...),
    product_code: str = Form(""),
    monthly_target: float = Form(0),
    sort_order: int = Form(0),
    is_active: Optional[str] = Form(None),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if product_id:
        p = db.query(Product).filter(Product.id == product_id, Product.user_id == user.id).first()
        if not p:
            raise HTTPException(404)
    else:
        p = Product(user_id=user.id)
        db.add(p)

    p.user_id = user.id
    p.pdf_name = pdf_name.strip()
    p.display_name = display_name.strip()
    p.product_code = product_code.strip() or None
    p.monthly_target = monthly_target
    p.sort_order = sort_order
    p.is_active = is_active == "on" or is_active == "true" or is_active is True
    db.commit()
    return RedirectResponse("/products?saved=1", status_code=303)


@app.post("/products/delete/{product_id}")
async def product_delete(request: Request, product_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    p = db.query(Product).filter(Product.id == product_id, Product.user_id == user.id).first()
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse("/products?deleted=1", status_code=303)


# ---------- History ----------
@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    reports = db.query(Report).filter(Report.user_id == user.id).order_by(desc(Report.report_date)).all()
    return templates.TemplateResponse("history.html", {
        "request": request,
        "active": "history",
        "user": user,
        "reports": reports,
        "format_number": format_number,
    })


@app.get("/history/{report_id}", response_class=HTMLResponse)
async def history_detail(request: Request, report_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    report = db.query(Report).options(joinedload(Report.products)).filter(
        Report.id == report_id, Report.user_id == user.id
    ).first()
    if not report:
        raise HTTPException(404)
    return templates.TemplateResponse("history_detail.html", {
        "request": request,
        "active": "history",
        "user": user,
        "report": report,
        "format_number": format_number,
    })


@app.post("/history/delete/{report_id}")
async def history_delete(request: Request, report_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    r = db.query(Report).filter(Report.id == report_id, Report.user_id == user.id).first()
    if r:
        db.delete(r)
        db.commit()
    return RedirectResponse("/history?deleted=1", status_code=303)


# ---------- Settings (simple) ----------
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active": "settings",
        "user": user,
    })
