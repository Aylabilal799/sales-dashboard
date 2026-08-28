"""
Deterministic PDF parser for Ferozsons-style MTD/YTD sales reports.
Uses PyMuPDF word extraction + Y-coordinate clustering.
Isolated module for easy future adjustments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import fitz  # PyMuPDF


@dataclass
class ExtractedProduct:
    p_code: str
    pdf_name: str
    tp: float
    today_qty: float
    mtd_qty: float
    net_qty: float
    value: float
    raw_line: str = ""


@dataclass
class ParseResult:
    success: bool
    report_date: Optional[date] = None
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    today_sale_value: float = 0.0
    mtd_sale_value: float = 0.0
    products: List[ExtractedProduct] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    raw_text_preview: str = ""


def _parse_float(s: str) -> Optional[float]:
    try:
        cleaned = s.replace(",", "").strip()
        if not cleaned or cleaned == "-":
            return 0.0
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_date_str(s: str) -> Optional[date]:
    s = s.strip()
    formats = ["%d-%m-%Y", "%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%b-%d-%y", "%d %b %Y"]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _cluster_words_by_y(words: list, tolerance: float = 3.0) -> Dict[float, List[Tuple[float, str]]]:
    if not words:
        return {}
    sorted_words = sorted(words, key=lambda w: (w[1], w[0]))
    lines: Dict[float, List[Tuple[float, str]]] = {}
    current_y = None
    for w in sorted_words:
        y0, text = w[1], w[4]
        if current_y is None or abs(y0 - current_y) > tolerance:
            current_y = y0
            lines[current_y] = []
        lines[current_y].append((w[0], text))
    for y in lines:
        lines[y].sort(key=lambda t: t[0])
    return lines


def _is_product_code(token: str) -> bool:
    return bool(re.match(r"^\d{6,8}$", token.strip()))


def _reconstruct_product_name(tokens: List[str]) -> str:
    return " ".join(tokens).strip()


def parse_sales_pdf(pdf_path: str) -> ParseResult:
    result = ParseResult(success=False)
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        result.errors.append(f"Cannot open PDF: {e}")
        return result
    if len(doc) == 0:
        result.errors.append("PDF has no pages")
        doc.close()
        return result

    page = doc[0]
    words = page.get_text("words")
    full_text = page.get_text()
    result.raw_text_preview = full_text[:1500]
    lines = _cluster_words_by_y(words, tolerance=4.0)

    from_date = None
    to_date = None
    report_date = None
    for y, tokens in sorted(lines.items()):
        texts = [t[1] for t in tokens]
        if "From" in texts:
            try:
                idx = texts.index("From")
                if idx + 1 < len(texts):
                    from_date = _parse_date_str(texts[idx + 1])
                if "To" in texts:
                    tidx = texts.index("To")
                    if tidx + 1 < len(texts):
                        to_date = _parse_date_str(texts[tidx + 1])
            except Exception:
                pass
        if not from_date:
            m = re.search(r"From\s*(\d{2}-\d{2}-\d{4})", full_text)
            if m:
                from_date = _parse_date_str(m.group(1))
        if not to_date:
            m = re.search(r"To\s*(\d{2}-\d{2}-\d{4})", full_text)
            if m:
                to_date = _parse_date_str(m.group(1))

    report_date = to_date or from_date
    if report_date is None:
        m = re.search(r"(\d{2}-\d{2}-20\d{2})", full_text)
        if m:
            report_date = _parse_date_str(m.group(1))
    if report_date is None:
        result.warnings.append("Could not determine report date from PDF; using today's date")
        report_date = date.today()
    result.report_date = report_date
    result.from_date = from_date
    result.to_date = to_date

    products: List[ExtractedProduct] = []
    sorted_ys = sorted(lines.keys())
    for i, y in enumerate(sorted_ys):
        tokens = [t[1] for t in lines[y]]
        if not tokens:
            continue
        joined_upper = " ".join(tokens).upper()
        if any(k in joined_upper for k in ("P-CODE", "PRODUCT NAM", "GROUP TOTAL", "SALE VALUE", "PAGE ", "USER NAME", "SUPPLIER")):
            continue
        if tokens[0] in ("PHARMA", "10764"):
            continue
        p_code = None
        start_idx = 0
        if _is_product_code(tokens[0]):
            p_code = tokens[0].lstrip("0") or tokens[0]
            start_idx = 1
        else:
            continue
        rest = tokens[start_idx:]
        if rest and rest[0] == "*":
            rest = rest[1:]
        name_tokens = []
        num_tokens = []
        in_numbers = False
        for tok in rest:
            if not in_numbers:
                if re.match(r"^\d+\.\d{2}$", tok) or (re.match(r"^\d+$", tok) and len(name_tokens) > 0 and len(num_tokens) == 0 and float(tok) > 50):
                    if re.match(r"^\d+\.\d{2}$", tok):
                        in_numbers = True
                        num_tokens.append(tok)
                    else:
                        name_tokens.append(tok)
                else:
                    name_tokens.append(tok)
            else:
                num_tokens.append(tok)
        if len(name_tokens) == 0 and len(num_tokens) >= 8:
            for dy in (-1, 1):
                ni = i + dy
                if 0 <= ni < len(sorted_ys):
                    ntoks = [t[1] for t in lines[sorted_ys[ni]]]
                    if ntoks and ntoks[0] == "*" and not _is_product_code(ntoks[0] if ntoks else ""):
                        name_tokens = [t for t in ntoks if t != "*"]
                        break
                    if ntoks and not _is_product_code(ntoks[0]) and not any(re.match(r"^\d+\.\d{2}$", t) for t in ntoks[:3]):
                        name_tokens = ntoks
                        break
        pdf_name = _reconstruct_product_name(name_tokens)
        if not pdf_name:
            result.warnings.append(f"Could not extract product name for code {p_code}")
            continue
        floats = []
        for tok in num_tokens:
            f = _parse_float(tok)
            if f is not None:
                floats.append(f)
        if len(floats) < 4:
            result.warnings.append(f"Insufficient numeric columns for {pdf_name} (code {p_code}): got {len(floats)}")
            continue
        tp = floats[0]
        today_qty = floats[1] if len(floats) > 1 else 0.0
        mtd_qty = floats[3] if len(floats) > 3 else 0.0
        net_qty = floats[6] if len(floats) > 6 else mtd_qty
        value = floats[7] if len(floats) > 7 else 0.0
        products.append(ExtractedProduct(p_code=p_code, pdf_name=pdf_name, tp=tp, today_qty=today_qty, mtd_qty=mtd_qty, net_qty=net_qty, value=value, raw_line=" ".join(tokens)))

    result.products = products
    today_total = None
    mtd_total = None
    for y, tokens in sorted(lines.items()):
        texts = [t[1] for t in tokens]
        if "Group" in texts and "Total" in texts:
            nums = []
            for t in texts:
                f = _parse_float(t)
                if f is not None and f > 100:
                    nums.append(f)
            if len(nums) >= 2:
                today_total = nums[0]
                mtd_total = nums[1]
                break
    if today_total is None or mtd_total is None:
        for y, tokens in sorted(lines.items()):
            texts = [t[1] for t in tokens]
            joined = " ".join(texts)
            if "Sale Value on Trade" in joined or "Sale Value on Trade Pric" in joined:
                nums = [_parse_float(t) for t in texts]
                nums = [n for n in nums if n is not None and n > 100]
                if len(nums) >= 2:
                    today_total = nums[0]
                    mtd_total = nums[1]
                    break
    if today_total is not None:
        result.today_sale_value = today_total
    else:
        result.warnings.append("Could not extract Today's total sale value from Group Total")
    if mtd_total is not None:
        result.mtd_sale_value = mtd_total
    else:
        result.warnings.append("Could not extract MTD total sale value")
    if not products:
        result.errors.append("No product rows could be extracted. PDF structure may have changed.")
    else:
        result.success = True
    doc.close()
    return result


def match_products(extracted: List[ExtractedProduct], configured: List[dict]) -> Tuple[List[dict], List[ExtractedProduct], List[dict]]:
    matched = []
    used_config_ids = set()
    unmatched_pdf = []
    by_code = {}
    by_pdf_name = {}
    by_norm = {}
    for c in configured:
        if c.get("product_code"):
            by_code[str(c["product_code"]).lstrip("0")] = c
        by_pdf_name[c["pdf_name"].strip().upper()] = c
        norm = re.sub(r"[^A-Z0-9]", "", c["pdf_name"].upper())
        by_norm[norm] = c
    for ep in extracted:
        conf = None
        code = ep.p_code.lstrip("0")
        if code in by_code:
            conf = by_code[code]
        if conf is None:
            key = ep.pdf_name.strip().upper()
            if key in by_pdf_name:
                conf = by_pdf_name[key]
        if conf is None:
            norm = re.sub(r"[^A-Z0-9]", "", ep.pdf_name.upper())
            if norm in by_norm:
                conf = by_norm[norm]
        if conf is not None:
            used_config_ids.add(conf["id"])
            tp = float(ep.tp or 0)
            today_qty = float(ep.today_qty or 0)
            mtd_qty = float(ep.mtd_qty or 0)
            matched.append({
                "product_id": conf["id"],
                "pdf_name": ep.pdf_name,
                "display_name": conf["display_name"],
                "today_qty": today_qty,
                "mtd_qty": mtd_qty,
                "other_city_sales": 0.0,
                "current_sale": mtd_qty,
                "monthly_target": conf.get("monthly_target", 0.0),
                "matched": True,
                "tp": tp,
                "today_value": round(today_qty * tp, 2),
                "mtd_value": round(mtd_qty * tp, 2),
                "value": ep.value,
            })
        else:
            unmatched_pdf.append(ep)
    missing = [c for c in configured if c["id"] not in used_config_ids and c.get("is_active", True)]
    return matched, unmatched_pdf, missing
