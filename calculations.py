"""
Sales achievement and message generation helpers.
"""

from __future__ import annotations

from datetime import date
from typing import List, Dict, Optional, Any
import calendar


def calc_per_day_target(monthly_target: float, working_days: int, override: Optional[float] = None) -> float:
    if override is not None and override > 0:
        return round(override, 2)
    if working_days <= 0:
        return 0.0
    return round(monthly_target / working_days, 2)


def calc_mtd_target(monthly_target: float, working_days: int, day_of_month: int, days_in_month: Optional[int] = None) -> float:
    if monthly_target <= 0:
        return 0.0
    if days_in_month is None or days_in_month <= 0:
        days_in_month = working_days if working_days > 0 else 30
    progress = min(max(day_of_month, 1), days_in_month) / days_in_month
    return round(monthly_target * progress, 2)


def calc_achievement(actual: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return round((actual / target) * 100, 0)


def calc_sale_value_from_products(products: list, qty_key: str = "today_qty") -> float:
    total = 0.0
    for p in products:
        qty = float(p.get(qty_key) or 0)
        tp = float(p.get("tp") or 0)
        total += qty * tp
    return round(total, 2)


def format_number(n: float, decimals: int = 0) -> str:
    if decimals == 0:
        return f"{int(round(n)):,}"
    return f"{n:,.{decimals}f}"


def generate_message(
    report_date: date,
    psp_name: str,
    town: str,
    per_day_target: float,
    today_sale: float,
    today_achievement: float,
    mtd_sale: float,
    mtd_target: float,
    mtd_achievement: float,
    products: List[Dict[str, Any]],
    zero_display: str = "dash",
) -> str:
    date_str = report_date.strftime("%d-%m-%y")
    lines = [
        f"📆 Date: {date_str}",
        f"👤 PSP: {psp_name}",
        f"📍 Town: {town}",
        "",
        f"🎯 Per Day Target: {format_number(per_day_target)}",
        f"💰 Today’s Sale: {format_number(today_sale)}",
        f"✅ Achievement: {int(today_achievement)}%",
        "",
        f"📊 MTD Sale: {format_number(mtd_sale)}",
        f"🎯 MTD Target: {format_number(mtd_target)}",
        f"📌 Achievement: {int(mtd_achievement)}%",
        "",
        "🧪 Today’s Product Sale",
    ]
    for p in products:
        name = p.get("display_name", p.get("pdf_name", "?"))
        qty = p.get("today_qty", 0) or 0
        if qty == 0:
            if zero_display == "zero":
                lines.append(f"• {name} – 0")
            else:
                lines.append(f"• {name} –")
        else:
            qstr = str(int(qty)) if float(qty).is_integer() else str(qty)
            lines.append(f"• {name} – {qstr}")
    lines.append("")
    lines.append("📦 Till Date (Tgt/Ach)")
    for p in products:
        name = p.get("display_name", p.get("pdf_name", "?"))
        tgt = p.get("monthly_target", 0) or 0
        ach = p.get("current_sale", 0) or 0
        tgt_s = str(int(tgt)) if float(tgt).is_integer() else str(tgt)
        ach_s = str(int(ach)) if float(ach).is_integer() else str(ach)
        lines.append(f"• {name} – {tgt_s} / {ach_s}")
    return "\n".join(lines)


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]
