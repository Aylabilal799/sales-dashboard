from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, Date, DateTime, ForeignKey, Boolean, UniqueConstraint
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    mobile = Column(String(20), unique=True, nullable=False, index=True)
    pin_hash = Column(String(255), nullable=False)
    name = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("user_id", "pdf_name", name="uq_user_pdf_name"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    pdf_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    product_code = Column(String(50), nullable=True)
    monthly_target = Column(Float, default=0.0)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class MonthlyConfig(Base):
    __tablename__ = "monthly_configs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    psp_name = Column(String(255), nullable=False)
    town = Column(String(255), nullable=False)
    monthly_sales_target = Column(Float, default=0.0)
    working_days = Column(Integer, default=26)
    per_day_target_override = Column(Float, nullable=True)
    zero_qty_display = Column(String(20), default="dash")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product_targets = relationship("ProductMonthlyTarget", back_populates="monthly_config", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="monthly_config")
    user = relationship("User")


class ProductMonthlyTarget(Base):
    __tablename__ = "product_monthly_targets"

    id = Column(Integer, primary_key=True)
    monthly_config_id = Column(Integer, ForeignKey("monthly_configs.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    target_qty = Column(Float, default=0.0)

    monthly_config = relationship("MonthlyConfig", back_populates="product_targets")
    product = relationship("Product")


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    report_date = Column(Date, nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    monthly_config_id = Column(Integer, ForeignKey("monthly_configs.id"), nullable=True)
    filename = Column(String(512), nullable=False)
    today_sale_value = Column(Float, default=0.0)
    mtd_sale_value = Column(Float, default=0.0)
    per_day_target = Column(Float, default=0.0)
    mtd_target = Column(Float, default=0.0)
    today_achievement = Column(Float, default=0.0)
    mtd_achievement = Column(Float, default=0.0)
    generated_message = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    monthly_config = relationship("MonthlyConfig", back_populates="reports")
    products = relationship("ReportProduct", back_populates="report", cascade="all, delete-orphan")
    user = relationship("User")


class ReportProduct(Base):
    __tablename__ = "report_products"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    pdf_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    today_qty = Column(Float, default=0.0)
    mtd_qty = Column(Float, default=0.0)
    other_city_sales = Column(Float, default=0.0)
    current_sale = Column(Float, default=0.0)
    monthly_target = Column(Float, default=0.0)
    tp = Column(Float, default=0.0)
    today_value = Column(Float, default=0.0)
    mtd_value = Column(Float, default=0.0)
    matched = Column(Boolean, default=False)

    report = relationship("Report", back_populates="products")
    product = relationship("Product")


class MonthOtherCity(Base):
    __tablename__ = "month_other_city"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    other_city_sales = Column(Float, default=0.0)

    product = relationship("Product")
    user = relationship("User")
