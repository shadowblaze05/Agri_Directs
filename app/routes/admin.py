from datetime import datetime, timedelta, timezone
from functools import wraps
import csv
import io
import math
import os
import re
import sqlite3
import uuid
from zipfile import BadZipFile
# OpenPyXL installs its hardened XML backend and uses it for XLSX parsing.
from xml.etree.ElementTree import ParseError  # nosec B405

from flask import Response, abort, current_app, flash, redirect, render_template, request, send_from_directory, session, stream_with_context, url_for
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import generate_password_hash

from .. import legacy as core
from ..extensions import db
from ..password_policy import password_policy_error
from ..models.audit import AuditEvent
from ..models.listing_photo_location_alert import ListingPhotoLocationAlert
from ..models.profile_report import ProfileReport
from ..models.slow_query import SlowQueryStat
from ..models.database import _save_upload_file, get_db, is_online_payment_enabled
from ..services.notification_service import notify_published_announcement
from ..services.auth_service import (
    PHILIPPINE_TIMEZONE,
    activate_due_accounts,
    get_active_user_role,
)
from ..services.upload_service import save_sanitized_public_image
from ..services.crop_pricing import (
    parse_pricing_rule,
    price_bounds,
    seller_price_error,
)
from ..services.face_scanning import MAX_SCAN_ATTEMPTS

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

ADMIN_EDITABLE_MARKETPLACE_STATUSES = {"available", "expired", "cancelled"}
ADMIN_MARKETPLACE_IMAGE_FORMATS = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "gif": "GIF",
    "webp": "WEBP",
}
ADMIN_PROFILE_IMAGE_FORMATS = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
}
MARKETPLACE_TRANSACTION_FILTER = """(
    COALESCE(TRIM(m.buyer_username), '') <> ''
    OR LOWER(COALESCE(m.order_status, '')) NOT IN ('', 'available')
    OR LOWER(COALESCE(m.preorder_status, '')) NOT IN ('', 'available')
    OR LOWER(COALESCE(m.status, '')) = 'traded'
)"""
MARKETPLACE_TRANSACTION_COMPLETED = """(
    LOWER(COALESCE(m.order_status, '')) = 'completed'
    OR LOWER(COALESCE(m.preorder_status, '')) = 'completed'
    OR LOWER(COALESCE(m.status, '')) = 'traded'
    OR (COALESCE(m.delivery_confirmed, 0) = 1 AND COALESCE(m.buyer_confirmed, 0) = 1)
)"""
_SAVEABLE_RECORD_COLUMNS = {
    ("commodity_categories", "name"),
    ("knowledge_categories", "category_name"),
}
_EDITABLE_RECORD_COLUMNS = {
    ("commodity_categories", "name", "id", "description"),
    ("knowledge_categories", "category_name", "category_id", None),
}
_DELETABLE_RECORD_COLUMNS = {
    ("commodity_categories", "id"),
    ("commodities", "id"),
    ("knowledge_categories", "category_id"),
}


def _current_user_is_admin():
    username = session.get("user")
    if not username:
        return False
    role = get_active_user_role(username, get_db)
    if role != "admin":
        session.pop("role", None)
        return False
    session["role"] = "admin"
    return True


def _current_user_is_superadmin():
    return (
        _current_user_is_admin()
        and session.get("user") == current_app.config["SUPERADMIN_USERNAME"]
    )


def _admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        if not _current_user_is_admin():
            flash("Admin access required", "warning")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)

    return wrapped


def _superadmin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        if not _current_user_is_superadmin():
            flash("Super admin access required", "warning")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)

    return wrapped


def _redirect_admin(endpoint="admin"):
    return redirect(url_for(endpoint))


def _form_value(name):
    return request.form.get(name, "").strip()


@_admin_required
def create_admin_user():
    username = _form_value("username")
    email = _form_value("email").lower()
    password = request.form.get("password", "")
    role = _form_value("role") or "seller"
    if role == "user":
        role = "seller"
    if not username or not password:
        flash("Username and password are required", "danger")
        return _redirect_admin("admin_users")
    password_error = password_policy_error(password)
    if password_error:
        flash(password_error, "danger")
        return _redirect_admin("admin_users")
    if role not in {"buyer", "seller", "admin"}:
        flash("Invalid account role", "danger")
        return _redirect_admin("admin_users")
    if role == "admin" and not _current_user_is_superadmin():
        flash("Only the super admin can create administrator accounts", "danger")
        return _redirect_admin("admin_users")

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO users(username, first_name, last_name, email, password, role, location)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                username,
                _form_value("first_name") or username,
                _form_value("last_name") or "User",
                email or f"{username}@example.com",
                generate_password_hash(password),
                role,
                _form_value("location") or None,
            ),
        )
        conn.commit()
        flash(f"User {username} created", "success")
    except IntegrityError:
        flash("That username or email is already in use", "danger")
    finally:
        conn.close()
    return _redirect_admin("admin_users")


@_admin_required
def edit_admin_user(user_id):
    activate_due_accounts(get_db)
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(
        "SELECT id, username, email, role, is_active, reactivate_on "
        "FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not user:
        conn.close()
        flash("User not found", "danger")
        return _redirect_admin("admin_users")

    is_superadmin = _current_user_is_superadmin()
    if (
        user["role"] == "admin"
        and user["username"] != session.get("user")
        and not is_superadmin
    ):
        conn.close()
        flash("Only the super admin can manage administrator accounts", "danger")
        return _redirect_admin("admin_users")

    role = _form_value("role") or "user"
    if role == "user":
        role = "seller"
    if role not in {"buyer", "seller", "admin"}:
        conn.close()
        flash("Invalid account role", "danger")
        return _redirect_admin("admin_users")
    if role == "admin" and not is_superadmin and user["role"] != "admin":
        conn.close()
        flash("Only the super admin can assign administrator access", "danger")
        return _redirect_admin("admin_users")
    if user["username"] == session.get("user") and user["role"] == "admin" and role != "admin":
        conn.close()
        flash("You cannot remove your own administrator access", "danger")
        return _redirect_admin("admin_users")
    is_active = request.form.get("is_active", str(int(user["is_active"])))
    if is_active not in {"0", "1"}:
        conn.close()
        flash("Invalid account status", "danger")
        return _redirect_admin("admin_users")
    if user["username"] == session.get("user") and is_active == "0":
        conn.close()
        flash("You cannot deactivate your own administrator account", "danger")
        return _redirect_admin("admin_users")
    requested_reactivation = request.form.get("reactivate_on")
    reactivate_on = None
    if is_active == "0":
        if requested_reactivation is None:
            reactivate_on = user["reactivate_on"]
        else:
            requested_reactivation = requested_reactivation.strip()
            if requested_reactivation:
                try:
                    reactivation_date = datetime.strptime(
                        requested_reactivation, "%Y-%m-%d"
                    ).date()
                except ValueError:
                    conn.close()
                    flash("Enter a valid reactivation date.", "danger")
                    return _redirect_admin("admin_users")
                if reactivation_date <= datetime.now(PHILIPPINE_TIMEZONE).date():
                    conn.close()
                    flash("The reactivation date must be in the future.", "danger")
                    return _redirect_admin("admin_users")
                reactivate_on = reactivation_date.isoformat()

    status_changed = bool(user["is_active"]) != (is_active == "1")
    password = request.form.get("password", "")
    fields = [
        _form_value("first_name") or user["username"],
        _form_value("last_name") or "User",
        _form_value("email").lower() or f"{user['username']}@example.com",
        role,
        _form_value("location") or None,
        is_active,
        reactivate_on,
    ]
    query = """UPDATE users SET first_name=?, last_name=?, email=?, role=?, location=?,
                is_active=?, reactivate_on=?"""
    if password:
        password_error = password_policy_error(password)
        if password_error:
            conn.close()
            flash(password_error, "danger")
            return _redirect_admin("admin_users")
        query += ", password = ?"
        fields.append(generate_password_hash(password))
    if password or status_changed:
        query += ", auth_version = auth_version + 1"
    query += " WHERE id=?"
    fields.append(user_id)
    try:
        cur.execute(query, fields)
        conn.commit()
        if is_active == "0" and reactivate_on:
            flash(
                f"User {user['username']} is inactive until {reactivate_on} "
                "(Philippine time).",
                "success",
            )
        else:
            flash(f"User {user['username']} updated", "success")
    except IntegrityError:
        flash("That email address is already in use", "danger")
    finally:
        conn.close()
    return _redirect_admin("admin_users")


@_admin_required
def delete_admin_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(
        "SELECT username, role FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if not user:
        conn.close()
        flash("User not found", "danger")
        return _redirect_admin("admin_users")
    if user["role"] == "admin" and not _current_user_is_superadmin():
        conn.close()
        flash("Only the super admin can manage administrator accounts", "danger")
        return _redirect_admin("admin_users")
    if user["username"] == session.get("user"):
        conn.close()
        flash("You cannot delete your own administrator account", "danger")
        return _redirect_admin("admin_users")
    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash(f"User {user['username']} deleted", "success")
    return _redirect_admin("admin_users")


def _save_named_record(table, column, success_message, endpoint="admin_catalog"):
    if (table, column) not in _SAVEABLE_RECORD_COLUMNS:
        raise ValueError("Unsupported named record")
    value = _form_value("name")
    if not value:
        flash("A name is required", "danger")
        return _redirect_admin(endpoint)
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            f"INSERT INTO {table}({column}) VALUES (?)",  # nosec B608
            (value,),
        )
        conn.commit()
        flash(success_message, "success")
    except IntegrityError:
        flash("That name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin(endpoint)


@_admin_required
def create_crop_category():
    name = _form_value("name")
    if not name:
        flash("A category name is required", "danger")
        return _redirect_admin()
    conn = get_db()
    try:
        conn.cursor().execute(
            """INSERT INTO commodity_categories(name, description, default_price_unit)
               VALUES (?, ?, ?)""",
            (
                name,
                _form_value("description") or None,
                _default_price_unit_for_category(category_name=name),
            ),
        )
        conn.commit()
        flash("Commodity category created", "success")
    except IntegrityError:
        flash("That category name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin()


@_admin_required
def edit_crop_category(category_id):
    return _edit_named_record("commodity_categories", "name", "id", category_id, "Commodity category updated", "description")


@_admin_required
def delete_crop_category(category_id):
    conn = get_db()
    cur = conn.cursor()
    crop_count = cur.execute(
        "SELECT COUNT(*) AS count FROM commodities WHERE category_id=?",
        (category_id,),
    ).fetchone()["count"]
    conn.close()
    if crop_count:
        flash("Move or remove this category's commodities before deleting it", "danger")
        return _redirect_admin("admin_commodity_details")
    return _delete_named_record(
        "commodity_categories",
        "id",
        category_id,
        "Commodity category deleted",
        endpoint="admin_commodity_details",
    )


def _crop_category_id():
    value = request.form.get("category_id", "").strip()
    if not value:
        return None
    try:
        category_id = int(value)
    except ValueError:
        return None

    conn = get_db()
    category = conn.cursor().execute(
        "SELECT id FROM commodity_categories WHERE id=?",
        (category_id,),
    ).fetchone()
    conn.close()
    return category_id if category else None


@_admin_required
def create_crop():
    name = _form_value("name")
    category_value = request.form.get("category_id", "").strip()
    category_id = _crop_category_id()
    if category_value and category_id is None:
        flash("Select a valid commodity category", "danger")
        return _redirect_admin()
    if not name:
        flash("A name is required", "danger")
        return _redirect_admin()

    conn = get_db()
    try:
        conn.cursor().execute(
            """INSERT INTO commodities(
                   commodity_name, category_id, default_price_unit
               ) VALUES (?, ?, ?)""",
            (
                name,
                category_id,
                _default_price_unit_for_category(category_id, conn=conn),
            ),
        )
        conn.commit()
        flash("Commodity created", "success")
    except IntegrityError:
        flash("That name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin()


@_admin_required
def edit_crop(commodity_id):
    name = _form_value("name")
    if not name:
        flash("A name is required", "danger")
        return _redirect_admin()

    conn = get_db()
    cur = conn.cursor()
    crop = cur.execute(
        "SELECT category_id, default_price_unit FROM commodities WHERE id=?",
        (commodity_id,),
    ).fetchone()
    if not crop:
        conn.close()
        flash("Commodity not found", "danger")
        return _redirect_admin()

    category_value = request.form.get("category_id")
    category_id = crop["category_id"] if category_value is None else _crop_category_id()
    if category_value is not None and category_value.strip() and category_id is None:
        conn.close()
        flash("Select a valid commodity category", "danger")
        return _redirect_admin()

    default_price_unit = crop["default_price_unit"] or "kg"
    if category_id != crop["category_id"]:
        default_price_unit = _default_price_unit_for_category(category_id, conn=conn)

    try:
        cur.execute(
            """UPDATE commodities
               SET commodity_name=?, category_id=?, default_price_unit=? WHERE id=?""",
            (name, category_id, default_price_unit, commodity_id),
        )
        if category_id != crop["category_id"]:
            cur.execute(
                "UPDATE commodity_pricing SET price_unit=? WHERE commodity_id=?",
                (default_price_unit, commodity_id),
            )
        conn.commit()
        flash("Commodity updated", "success")
    except IntegrityError:
        flash("That name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin()


@_admin_required
def save_crop_pricing(commodity_id):
    pricing_mode = _form_value("pricing_mode")
    conn = get_db()
    cur = conn.cursor()
    crop = cur.execute(
        "SELECT id, default_price_unit FROM commodities WHERE id=?",
        (commodity_id,),
    ).fetchone()
    if not crop:
        conn.close()
        flash("Commodity not found", "danger")
        return _redirect_admin("admin_catalog")

    price_unit = _form_value("price_unit").strip().lower() or crop["default_price_unit"] or "kg"
    if pricing_mode != "none" and not _price_unit_exists(price_unit, conn=conn):
        conn.close()
        flash("Choose a registered commodity price unit.", "danger")
        return _redirect_admin("admin_catalog")

    if pricing_mode == "none":
        rule = None
    elif pricing_mode in {"range", "bounds"}:
        try:
            rule = parse_pricing_rule(
                pricing_mode,
                price_unit,
                _form_value("reference_price"),
                _form_value("price_range"),
                _form_value("minimum_price"),
                _form_value("maximum_price"),
            )
        except ValueError as error:
            conn.close()
            flash(str(error), "danger")
            return _redirect_admin("admin_catalog")
    else:
        conn.close()
        flash("Select a valid commodity pricing method", "danger")
        return _redirect_admin("admin_catalog")

    if pricing_mode == "none":
        cur.execute("DELETE FROM commodity_pricing WHERE commodity_id=?", (commodity_id,))
        flash("Commodity pricing restrictions removed", "success")
    else:
        cur.execute(
            """INSERT INTO commodity_pricing(
                   commodity_id, pricing_mode, reference_price, price_range,
                   minimum_price, maximum_price, price_unit
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(commodity_id) DO UPDATE SET
                   pricing_mode=excluded.pricing_mode,
                   reference_price=excluded.reference_price,
                   price_range=excluded.price_range,
                   minimum_price=excluded.minimum_price,
                   maximum_price=excluded.maximum_price,
                   price_unit=excluded.price_unit""",
            (commodity_id, rule["pricing_mode"], rule["reference_price"],
             rule["price_range"], rule["minimum_price"],
             rule["maximum_price"], rule["price_unit"]),
        )
        flash("Commodity pricing saved", "success")
    conn.commit()
    conn.close()
    return _redirect_admin("admin_catalog")


@_admin_required
def save_crop_pricing_batch():
    crop_ids = request.form.getlist("commodity_id") or request.form.getlist("crop_id")
    pricing_modes = request.form.getlist("pricing_mode")
    reference_prices = request.form.getlist("reference_price")
    price_ranges = request.form.getlist("price_range")
    minimum_prices = request.form.getlist("minimum_price")
    maximum_prices = request.form.getlist("maximum_price")
    row_count = len(crop_ids)

    if not row_count or row_count > 100 or any(
        len(values) != row_count
        for values in (
            pricing_modes,
            reference_prices,
            price_ranges,
            minimum_prices,
            maximum_prices,
        )
    ):
        flash("Add between 1 and 100 complete commodity price rules.", "danger")
        return _redirect_admin("admin_catalog")

    prepared_rules = []
    seen_crop_ids = set()
    try:
        for index, crop_id_value in enumerate(crop_ids):
            commodity_id = int(crop_id_value)
            if commodity_id <= 0 or commodity_id in seen_crop_ids:
                raise ValueError("Choose a different commodity for each price rule.")
            seen_crop_ids.add(commodity_id)
            pricing_mode = pricing_modes[index]
            if pricing_mode == "none":
                rule = None
            elif pricing_mode in {"range", "bounds"}:
                rule = parse_pricing_rule(
                    pricing_mode,
                    "kg",
                    reference_prices[index].strip(),
                    price_ranges[index].strip(),
                    minimum_prices[index].strip(),
                    maximum_prices[index].strip(),
                )
            else:
                raise ValueError("Select a valid commodity pricing method.")
            prepared_rules.append((commodity_id, pricing_mode, rule))
    except (TypeError, ValueError) as error:
        flash(f"Commodity price rule validation failed: {error}", "danger")
        return _redirect_admin("admin_catalog")

    imported_crop_ids = {
        int(commodity_id)
        for commodity_id in session.get("crop_pricing_import_crop_ids", [])
    }
    if not imported_crop_ids or not seen_crop_ids.issubset(imported_crop_ids):
        flash("Choose commodities from the most recently imported file.", "danger")
        return _redirect_admin("admin_catalog")

    conn = get_db()
    cur = conn.cursor()
    placeholders = ", ".join("?" for _ in seen_crop_ids)
    existing_crop_ids = {
        row["id"]
        for row in cur.execute(
            f"SELECT id FROM commodities WHERE id IN ({placeholders})",  # nosec B608
            tuple(seen_crop_ids),
        ).fetchall()
    }
    if existing_crop_ids != seen_crop_ids:
        conn.close()
        flash("One or more selected commodities no longer exist. No rules were saved.", "danger")
        return _redirect_admin("admin_catalog")

    try:
        for commodity_id, pricing_mode, rule in prepared_rules:
            if pricing_mode == "none":
                cur.execute("DELETE FROM commodity_pricing WHERE commodity_id=?", (commodity_id,))
                continue
            cur.execute(
                """INSERT INTO commodity_pricing(
                       commodity_id, pricing_mode, reference_price, price_range,
                       minimum_price, maximum_price, price_unit
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(commodity_id) DO UPDATE SET
                       pricing_mode=excluded.pricing_mode,
                       reference_price=excluded.reference_price,
                       price_range=excluded.price_range,
                       minimum_price=excluded.minimum_price,
                       maximum_price=excluded.maximum_price,
                       price_unit=excluded.price_unit""",
                (
                    commodity_id,
                    rule["pricing_mode"],
                    rule["reference_price"],
                    rule["price_range"],
                    rule["minimum_price"],
                    rule["maximum_price"],
                    rule["price_unit"],
                ),
            )
        conn.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Batch crop pricing save failed")
        conn.close()
        flash("Commodity price rules could not be saved. No changes were committed.", "danger")
        return _redirect_admin("admin_catalog")

    conn.close()
    session.pop("crop_pricing_import_crop_ids", None)
    commodity_label = "commodity" if row_count == 1 else "commodities"
    flash(f"Saved price rules for {row_count} {commodity_label}.", "success")
    return _redirect_admin("admin_catalog")


@_admin_required
def download_crop_pricing_template():
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        (
            "commodity_name",
            "category_name",
            "price_unit",
            "price",
        )
    )
    writer.writerow(("Rice", "Grains", "kg", "50"))
    writer.writerow(("Tomato", "Vegetables", "kg", "40"))
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="crop-pricing-template.csv"'
        },
    )


@_admin_required
def import_crop_pricing():
    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        flash("Choose a CSV or Excel (.xlsx) file to import.", "danger")
        return _redirect_admin("admin_catalog")

    extension = uploaded_file.filename.rsplit(".", 1)[-1].lower()
    if extension not in {"csv", "xlsx"}:
        flash("Only CSV and Excel (.xlsx) files are supported.", "danger")
        return _redirect_admin("admin_catalog")

    file_contents = uploaded_file.stream.read(5 * 1024 * 1024 + 1)
    if len(file_contents) > 5 * 1024 * 1024:
        flash("The pricing file must be 5 MB or smaller.", "danger")
        return _redirect_admin("admin_catalog")
    if not file_contents:
        flash("The selected pricing file is empty.", "danger")
        return _redirect_admin("admin_catalog")

    if extension == "csv":
        try:
            csv_rows = csv.reader(
                io.StringIO(file_contents.decode("utf-8-sig"), newline="")
            )
            header_row = next(csv_rows, None)
            data_rows = csv_rows
        except (UnicodeDecodeError, csv.Error):
            flash("The CSV must be a valid UTF-8 file.", "danger")
            return _redirect_admin("admin_catalog")
    else:
        try:
            workbook = load_workbook(
                io.BytesIO(file_contents), read_only=True, data_only=True
            )
            worksheet = workbook.active
            excel_rows = worksheet.iter_rows(values_only=True)
            header_row = next(excel_rows, None)
            data_rows = excel_rows
        except (BadZipFile, InvalidFileException, OSError, ValueError):
            flash("The Excel file is invalid or cannot be opened.", "danger")
            return _redirect_admin("admin_catalog")

    expected_headers = {"commodity_name", "category_name", "price_unit", "price"}
    headers = [
        str(header).strip().lower().replace(" ", "_") if header is not None else ""
        for header in (header_row or ())
    ]
    headers = [
        "commodity_name" if header == "crop_name" else header
        for header in headers
    ]
    if not headers or len(headers) > 32 or len(headers) != len(set(headers)):
        if extension == "xlsx":
            workbook.close()
        flash(
            "The file must have one header row with no duplicate column names "
            "and no more than 32 columns.",
            "danger",
        )
        return _redirect_admin("admin_catalog")
    if set(headers) != expected_headers:
        if extension == "xlsx":
            workbook.close()
        flash(
            "The file must contain only these columns: "
            "commodity_name, category_name, price_unit, price.",
            "danger",
        )
        return _redirect_admin("admin_catalog")

    prepared_rows = []
    seen_crops = set()
    try:
        for row_number, row in enumerate(data_rows, start=2):
            if row_number > 5001:
                raise ValueError("Files may contain at most 5,000 pricing rows.")
            values = list(row)
            if not any(value is not None and str(value).strip() for value in values):
                continue
            if len(values) > len(headers):
                raise ValueError(f"Row {row_number} has more cells than the header.")
            values.extend([None] * (len(headers) - len(values)))
            record = dict(zip(headers, values))
            commodity_name = str(record.get("commodity_name") or "").strip()
            if not commodity_name:
                raise ValueError(f"Row {row_number}: commodity_name is required.")
            if len(commodity_name) > 128:
                raise ValueError(f"Row {row_number}: commodity_name must be 128 characters or fewer.")
            category_name = str(record.get("category_name") or "").strip()
            if len(category_name) > 128:
                raise ValueError(
                    f"Row {row_number}: category_name must be 128 characters or fewer."
                )
            normalized_name = commodity_name.casefold()
            if normalized_name in seen_crops:
                raise ValueError(f"Row {row_number}: {commodity_name} appears more than once.")
            seen_crops.add(normalized_name)
            price_unit = str(record.get("price_unit") or "").strip().lower()
            if price_unit != "kg":
                raise ValueError(
                    f"Row {row_number} ({commodity_name}): price_unit must be kg."
                )
            try:
                price_rule = parse_pricing_rule(
                    "range",
                    "kg",
                    record.get("price"),
                    request.form.get("price_range", ""),
                    "",
                    "",
                )
            except ValueError as error:
                raise ValueError(f"Row {row_number} ({commodity_name}): {error}") from error
            prepared_rows.append(
                {
                    "row_number": row_number,
                    "commodity_name": commodity_name,
                    "category_name": category_name,
                    "price_unit": "kg",
                    "price_rule": price_rule,
                }
            )
    except (csv.Error, ParseError, ValueError) as error:
        if extension == "xlsx":
            workbook.close()
        flash(str(error), "danger")
        return _redirect_admin("admin_catalog")

    if extension == "xlsx":
        workbook.close()
    if not prepared_rows:
        flash("The file contains no commodity pricing rows to import.", "danger")
        return _redirect_admin("admin_catalog")

    conn = get_db()
    cur = conn.cursor()
    for record in prepared_rows:
        crop = cur.execute(
            """SELECT commodities.id, commodities.category_id,
                      COALESCE(commodity_categories.name, '') AS category_name
               FROM commodities LEFT JOIN commodity_categories
                 ON commodity_categories.id=commodities.category_id
               WHERE LOWER(TRIM(commodities.commodity_name))=LOWER(?)""",
            (record["commodity_name"],),
        ).fetchone()
        category_name = record["category_name"]
        category = None
        if category_name:
            category = cur.execute(
                "SELECT id, name FROM commodity_categories "
                "WHERE LOWER(TRIM(name))=LOWER(?)",
                (category_name,),
            ).fetchone()
        if crop:
            if category_name and category_name.casefold() != crop["category_name"].casefold():
                actual_category = crop["category_name"] or "Uncategorized"
                conn.close()
                flash(
                    f"Row {record['row_number']}: '{record['commodity_name']}' belongs "
                    f"to {actual_category}, not {category_name}. No prices were imported.",
                    "danger",
                )
                return _redirect_admin("admin_catalog")
            record["commodity_id"] = crop["id"]
            record["category_id"] = crop["category_id"]
            record["create_crop"] = False
        else:
            record["commodity_id"] = None
            record["category_id"] = category["id"] if category else None
            record["create_crop"] = True
            record["new_category_name"] = (
                category_name if category_name and category is None else None
            )

    new_categories = {}
    for record in prepared_rows:
        new_category_name = record.get("new_category_name")
        if new_category_name:
            new_categories.setdefault(new_category_name.casefold(), new_category_name)

    category_ids = {}
    for normalized_name, category_name in new_categories.items():
        cur.execute(
            "INSERT INTO commodity_categories(name) VALUES (?) RETURNING id",
            (category_name,),
        )
        category_ids[normalized_name] = cur.fetchone()["id"]

    new_crop_count = 0
    for record in prepared_rows:
        if not record["create_crop"]:
            continue
        category_id = record["category_id"]
        if record.get("new_category_name"):
            category_id = category_ids[record["new_category_name"].casefold()]
        cur.execute(
            "INSERT INTO commodities(commodity_name, category_id) VALUES (?, ?) RETURNING id",
            (record["commodity_name"], category_id),
        )
        record["commodity_id"] = cur.fetchone()["id"]
        new_crop_count += 1

    for record in prepared_rows:
        rule = record["price_rule"]
        cur.execute(
            """INSERT INTO commodity_pricing(
                   commodity_id, pricing_mode, reference_price, price_range,
                   minimum_price, maximum_price, price_unit
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(commodity_id) DO UPDATE SET
                   pricing_mode=excluded.pricing_mode,
                   reference_price=excluded.reference_price,
                   price_range=excluded.price_range,
                   minimum_price=excluded.minimum_price,
                   maximum_price=excluded.maximum_price,
                   price_unit=excluded.price_unit""",
            (
                record["commodity_id"],
                rule["pricing_mode"],
                rule["reference_price"],
                rule["price_range"],
                rule["minimum_price"],
                rule["maximum_price"],
                rule["price_unit"],
            ),
        )

    conn.commit()
    conn.close()
    session["crop_pricing_import_crop_ids"] = [
        record["commodity_id"] for record in prepared_rows
    ]
    new_commodity_label = "commodity" if new_crop_count == 1 else "commodities"
    imported_commodity_label = (
        "commodity" if len(prepared_rows) == 1 else "commodities"
    )
    flash(
        f"Import successful: added {new_crop_count} new {new_commodity_label} and "
        f"updated prices for {len(prepared_rows)} {imported_commodity_label}.",
        "success",
    )
    return _redirect_admin("admin_catalog")


@_admin_required
def delete_crop(commodity_id):
    return _delete_named_record("commodities", "id", commodity_id, "Commodity deleted")


@_admin_required
def create_knowledge_category():
    return _save_named_record(
        "knowledge_categories", "category_name", "Knowledge category created", "admin_knowledge_categories"
    )


@_admin_required
def edit_knowledge_category(category_id):
    return _edit_named_record("knowledge_categories", "category_name", "category_id", category_id, "Knowledge category updated", endpoint="admin_knowledge_categories")


@_admin_required
def delete_knowledge_category(category_id):
    return _delete_named_record("knowledge_categories", "category_id", category_id, "Knowledge category deleted", endpoint="admin_knowledge_categories")


def _edit_named_record(table, column, id_column, record_id, message, extra_column=None, endpoint="admin_catalog"):
    if (table, column, id_column, extra_column) not in _EDITABLE_RECORD_COLUMNS:
        raise ValueError("Unsupported named record")
    value = _form_value("name")
    if not value:
        flash("A name is required", "danger")
        return _redirect_admin(endpoint)
    conn = get_db()
    values = [value]
    query = f"UPDATE {table} SET {column}=?"  # nosec B608
    if extra_column:
        query += f", {extra_column}=?"
        values.append(_form_value("description") or None)
    query += f" WHERE {id_column}=?"
    values.append(record_id)
    try:
        cur = conn.cursor()
        cur.execute(query, values)
        conn.commit()
        flash(message, "success")
    except IntegrityError:
        flash("That name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin(endpoint)


def _delete_named_record(table, id_column, record_id, message, endpoint="admin_catalog"):
    if (table, id_column) not in _DELETABLE_RECORD_COLUMNS:
        raise ValueError("Unsupported named record")
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            f"DELETE FROM {table} WHERE {id_column}=?",  # nosec B608
            (record_id,)
        )
        conn.commit()
        flash(message, "success")
    except IntegrityError:
        flash("This record is still in use and cannot be deleted", "danger")
    finally:
        conn.close()
    return _redirect_admin(endpoint)


def admin_knowledge():
    if "user" not in session:
        return redirect("/login")
    if not _current_user_is_admin():
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    search = request.args.get("q", "").strip()
    search_filter = ""
    params = []
    if search:
        search_filter = "WHERE kp.title LIKE ? OR kp.author LIKE ? OR kc.category_name LIKE ?"
        params = [f"%{search}%"] * 3
    # search_filter selects a fixed clause; search values are bound separately.
    posts_query = (
        "SELECT kp.post_id, kp.title, kp.status, kp.is_pinned, kp.created_at, kp.views, kc.category_name, kp.author\n"  # nosec B608
        "FROM knowledge_posts kp\n"
        "LEFT JOIN knowledge_categories kc ON kp.category_id = kc.category_id\n"
        + search_filter
        + "\nORDER BY kp.is_pinned DESC, kp.created_at DESC"
    )
    cur.execute(posts_query, params)
    posts = cur.fetchall()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()
    cur.execute("SELECT COUNT(*) AS total_posts FROM knowledge_posts")
    total_posts = cur.fetchone()["total_posts"]
    cur.execute("SELECT COUNT(*) AS published_posts FROM knowledge_posts WHERE status = 'Published'")
    published_posts = cur.fetchone()["published_posts"]
    cur.execute("SELECT COUNT(*) AS draft_posts FROM knowledge_posts WHERE status = 'Draft'")
    draft_posts = cur.fetchone()["draft_posts"]
    conn.close()
    return render_template(
        "admin_knowledge.html",
        posts=posts,
        categories=categories,
        total_posts=total_posts,
        published_posts=published_posts,
        draft_posts=draft_posts,
        search=search,
    )

def create_knowledge_post():
    if "user" not in session:
        return redirect("/login")
    if not _current_user_is_admin():
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()
    conn.close()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id = request.form.get("category_id") or None
        status = request.form.get("status", "Published")
        is_pinned = request.form.get("is_pinned") == "1"
        if not title or not content:
            flash("Title and content are required")
            return render_template("create_post.html", categories=categories)

        try:
            image_path = _save_upload_file(request.files.get("image"), "images")
            video_path = _save_upload_file(request.files.get("video"), "videos")
        except ValueError as error:
            flash(str(error), "danger")
            return render_template("create_post.html", categories=categories), 400

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO knowledge_posts
                (title, content, category_id, author, image, video, status, is_pinned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING post_id
            """,
            (
                title, content, category_id, session.get("user"), image_path,
                video_path, status, int(is_pinned),
            ),
        )
        created_post = cur.fetchone()
        if is_pinned and status == "Published":
            notify_published_announcement(cur, created_post["post_id"], title)
        conn.commit()
        conn.close()
        flash("Article created successfully")
        return redirect("/admin/knowledge")

    return render_template("create_post.html", categories=categories)

def edit_knowledge_post(post_id):
    if "user" not in session:
        return redirect("/login")
    if not _current_user_is_admin():
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """SELECT post_id, title, content, category_id, image, video, status, is_pinned
           FROM knowledge_posts WHERE post_id=?""",
        (post_id,),
    )
    post = cur.fetchone()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()
    conn.close()

    if not post:
        flash("Post not found")
        return redirect("/admin/knowledge")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id = request.form.get("category_id") or None
        status = request.form.get("status", "Published")
        is_pinned = request.form.get("is_pinned") == "1"
        if not title or not content:
            flash("Title and content are required")
            return render_template("edit_post.html", post=post, categories=categories)

        try:
            image_path = _save_upload_file(request.files.get("image"), "images") or post["image"]
            video_path = _save_upload_file(request.files.get("video"), "videos") or post["video"]
        except ValueError as error:
            flash(str(error), "danger")
            return render_template("edit_post.html", post=post, categories=categories), 400

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE knowledge_posts
            SET title=?, content=?, category_id=?, image=?, video=?, status=?, is_pinned=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE post_id=?
            """,
            (
                title, content, category_id, image_path, video_path, status,
                int(is_pinned), post_id,
            ),
        )
        if (
            is_pinned
            and status == "Published"
            and (not post["is_pinned"] or post["status"] != "Published")
        ):
            notify_published_announcement(cur, post_id, title)
        conn.commit()
        conn.close()
        flash("Article updated successfully")
        return redirect("/admin/knowledge")

    return render_template("edit_post.html", post=post, categories=categories)

def delete_knowledge_post(post_id):
    if "user" not in session:
        return redirect("/login")
    if not _current_user_is_admin():
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM knowledge_replies WHERE comment_id IN (SELECT comment_id FROM knowledge_comments WHERE post_id=?)", (post_id,))
    cur.execute("DELETE FROM knowledge_comments WHERE post_id=?", (post_id,))
    cur.execute("DELETE FROM knowledge_likes WHERE post_id=?", (post_id,))
    cur.execute("DELETE FROM knowledge_posts WHERE post_id=?", (post_id,))
    conn.commit()
    conn.close()
    flash("Article deleted successfully")
    return redirect("/admin/knowledge")

def admin():
    if "user" not in session:
        return redirect("/login")
    if not _current_user_is_admin():
        flash("Admin access required")
        return redirect("/dashboard")
    conn = get_db()
    cur = conn.cursor()
    stats = {
        "users": cur.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"],
        "admins": cur.execute("SELECT COUNT(*) AS count FROM users WHERE role='admin'").fetchone()["count"],
        "commodities": cur.execute("SELECT COUNT(*) AS count FROM commodities").fetchone()["count"],
        "articles": cur.execute("SELECT COUNT(*) AS count FROM knowledge_posts").fetchone()["count"],
        "marketplace": cur.execute("SELECT COUNT(*) AS count FROM marketplace").fetchone()["count"],
        "marketplace_transactions": cur.execute(
            f"SELECT COUNT(*) AS count FROM marketplace m WHERE {MARKETPLACE_TRANSACTION_FILTER}",  # nosec B608
        ).fetchone()["count"],
        "face_scans_verified": cur.execute(
            "SELECT COUNT(*) AS count FROM users "
            "WHERE profile_photo_scan_verified_at IS NOT NULL"
        ).fetchone()["count"],
        "online_payments_pending": cur.execute(
            "SELECT COUNT(*) AS count FROM marketplace "
            "WHERE payment_method='xendit' AND order_status='awaiting_payment'"
        ).fetchone()["count"],
        "open_reports": cur.execute(
            "SELECT COUNT(*) AS count FROM profile_reports WHERE status='open'"
        ).fetchone()["count"],
        "open_listing_photo_alerts": cur.execute(
            "SELECT COUNT(*) AS count FROM listing_photo_location_alerts WHERE status='open'"
        ).fetchone()["count"],
    }
    conn.close()
    return render_template(
        "admin.html",
        stats=stats,
        is_superadmin=_current_user_is_superadmin(),
    )


def _save_admin_profile_photo(uploaded_file):
    extension = os.path.splitext(uploaded_file.filename)[1].lower().lstrip(".")
    expected_format = ADMIN_PROFILE_IMAGE_FORMATS.get(extension)
    if not expected_format:
        raise ValueError("Choose a PNG, JPG, JPEG, or WEBP profile photo.")

    profile_directory = os.path.join(
        current_app.config["UPLOAD_FOLDER"], "profile_photos"
    )
    os.makedirs(profile_directory, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{extension}"
    image_path = os.path.join(profile_directory, filename)
    temporary_path = os.path.join(profile_directory, f".{uuid.uuid4().hex}.tmp")
    try:
        save_sanitized_public_image(
            uploaded_file,
            temporary_path,
            expected_format,
            current_app.config["MAX_PROFILE_PHOTO_SIZE_BYTES"],
        )
        os.replace(temporary_path, image_path)
    except (OSError, ValueError):
        for path in (temporary_path, image_path):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                current_app.logger.exception(
                    "Unable to remove an uncommitted admin profile photo"
                )
        raise
    return filename, image_path


def _managed_admin_profile_photo_path(profile_picture):
    if not isinstance(profile_picture, str) or not profile_picture:
        return None

    legacy_prefix = "/static/uploads/profiles/"
    if profile_picture.startswith(legacy_prefix):
        filename = profile_picture[len(legacy_prefix):]
        directory = os.path.join(current_app.static_folder, "uploads", "profiles")
    else:
        filename = profile_picture
        directory = os.path.join(current_app.config["UPLOAD_FOLDER"], "profile_photos")
    if (
        not filename
        or os.path.basename(filename) != filename
        or os.path.splitext(filename)[1].lower().lstrip(".")
        not in ADMIN_PROFILE_IMAGE_FORMATS
    ):
        return None
    return os.path.join(directory, filename)


@_admin_required
def update_admin_user_profile_photo(user_id):
    uploaded_photo = request.files.get("profile_photo")
    if not uploaded_photo or not uploaded_photo.filename:
        flash("Choose a profile photo to upload.", "danger")
        return _redirect_admin("admin_users")

    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(
        "SELECT username, profile_picture FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if not user:
        conn.close()
        flash("User not found.", "danger")
        return _redirect_admin("admin_users")

    try:
        filename, image_path = _save_admin_profile_photo(uploaded_photo)
    except ValueError as error:
        conn.close()
        flash(str(error), "danger")
        return _redirect_admin("admin_users")

    try:
        # Admin replacement changes the photo and invalidates only its old
        # capture/scan claims. The user's location and geotag stay untouched.
        cur.execute(
            "UPDATE users SET profile_picture=?, profile_photo_captured_at=NULL, "
            "profile_photo_scan_verified_at=NULL WHERE id=?",
            (filename, user_id),
        )
        if cur.rowcount != 1:
            raise RuntimeError("The user profile could not be updated.")
        conn.commit()
    except Exception:
        conn.rollback()
        current_app.logger.exception("Unable to update an admin-managed profile photo")
        try:
            if os.path.isfile(image_path):
                os.remove(image_path)
        except OSError:
            current_app.logger.exception(
                "Unable to remove an uncommitted admin profile photo"
            )
        flash("The profile photo could not be updated.", "danger")
        return _redirect_admin("admin_users")
    finally:
        conn.close()

    old_path = _managed_admin_profile_photo_path(user["profile_picture"])
    if old_path and old_path != image_path and os.path.isfile(old_path):
        try:
            os.remove(old_path)
        except OSError:
            current_app.logger.exception("Unable to remove the replaced profile photo")

    flash(
        f"Profile photo updated for {user['username']}. Location and geotag were not changed.",
        "success",
    )
    return _redirect_admin("admin_users")


@_admin_required
def admin_users():
    # The verification table is also used by password recovery. Ensure its
    # current schema before computing pending account status.
    from .auth import _ensure_password_reset_table

    _ensure_password_reset_table()
    activate_due_accounts(get_db)
    search = request.args.get("q", "").strip()
    conn = get_db()
    cur = conn.cursor()
    query = """SELECT id, username, first_name, last_name, email, role, location,
               profile_picture,
               is_active, reactivate_on,
               CASE WHEN COALESCE(users.is_verified, FALSE)=FALSE AND EXISTS (
                   SELECT 1 FROM password_reset_tokens t WHERE t.user_id=users.id
                   AND t.purpose='email_verification' AND t.used_at IS NULL
               ) THEN 1 ELSE 0 END AS pending_verification,
               (SELECT t.expires_at FROM password_reset_tokens t WHERE t.user_id=users.id
                AND t.purpose='email_verification' AND t.used_at IS NULL
                ORDER BY t.created_at DESC LIMIT 1) AS verification_expires_at,
               reliability_status, completed_transactions, cancelled_transactions,
               total_transactions FROM users"""
    params = []
    if search:
        query += """ WHERE username LIKE ? OR email LIKE ? OR first_name LIKE ?
                     OR last_name LIKE ? OR role LIKE ? OR location LIKE ?"""
        params.extend([f"%{search}%"] * 6)
    query += " ORDER BY role, username"
    users = cur.execute(query, params).fetchall()
    conn.close()
    return render_template(
        "admin_users.html",
        users=users,
        search=search,
        active_user_count=sum(
            bool(user["is_active"]) and not bool(user["pending_verification"])
            for user in users
        ),
        pending_user_count=sum(bool(user["pending_verification"]) for user in users),
        inactive_user_count=sum(
            not bool(user["is_active"]) and not bool(user["pending_verification"])
            for user in users
        ),
        minimum_reactivation_date=(
            datetime.now(PHILIPPINE_TIMEZONE).date() + timedelta(days=1)
        ).isoformat(),
        is_superadmin=_current_user_is_superadmin(),
        superadmin_username=current_app.config["SUPERADMIN_USERNAME"],
    )


@_admin_required
def admin_catalog():
    search = request.args.get("q", "").strip()
    category_filter = request.args.get("category_id", "").strip()
    crop_filter = (
        request.args.get("commodity_id", request.args.get("crop_id", ""))
        .strip()
    )
    try:
        category_id = int(category_filter) if category_filter else None
        if category_id is not None and category_id <= 0:
            category_id = None
    except ValueError:
        category_id = None
    uncategorized = category_filter == "uncategorized"
    try:
        commodity_id = int(crop_filter) if crop_filter else None
        if commodity_id is not None and commodity_id <= 0:
            commodity_id = None
    except ValueError:
        commodity_id = None

    conn = get_db()
    cur = conn.cursor()
    pattern = f"%{search}%"
    commodities = cur.execute(
        """SELECT commodities.id, commodities.commodity_name, commodities.category_id,
                  COALESCE(commodity_categories.name, 'Uncategorized') AS category_name,
                  commodity_pricing.pricing_mode, commodity_pricing.reference_price,
                  commodity_pricing.price_range, commodity_pricing.minimum_price,
                  commodity_pricing.maximum_price,
                  COALESCE(commodity_pricing.price_unit,
                           commodities.default_price_unit, 'kg') AS price_unit
           FROM commodities
           LEFT JOIN commodity_categories ON commodity_categories.id = commodities.category_id
           LEFT JOIN commodity_pricing ON commodity_pricing.commodity_id = commodities.id
           WHERE (? = '' OR commodities.commodity_name LIKE ? OR commodity_categories.name LIKE ?)
             AND (? IS NULL OR commodities.category_id = ?)
             AND (? = 0 OR commodities.category_id IS NULL)
             AND (? IS NULL OR commodities.id = ?)
           ORDER BY COALESCE(commodity_categories.name, 'Uncategorized'), commodities.commodity_name""",
        (
            search,
            pattern,
            pattern,
            category_id,
            category_id,
            int(uncategorized),
            commodity_id,
            commodity_id,
        ),
    ).fetchall()
    commodity_categories = cur.execute(
        """SELECT id, name, description FROM commodity_categories
           WHERE ? = '' OR name LIKE ? OR description LIKE ? ORDER BY name""",
        (search, pattern, pattern),
    ).fetchall()
    all_crop_categories = cur.execute(
        "SELECT id, name FROM commodity_categories ORDER BY name"
    ).fetchall()
    crop_filter_options = cur.execute(
        """SELECT commodities.id, commodities.commodity_name, commodities.category_id,
                  commodity_pricing.pricing_mode, commodity_pricing.reference_price,
                  commodity_pricing.price_range, commodity_pricing.minimum_price,
                  commodity_pricing.maximum_price,
                  COALESCE(commodity_pricing.price_unit,
                           commodities.default_price_unit, 'kg') AS price_unit
           FROM commodities LEFT JOIN commodity_pricing ON commodity_pricing.commodity_id=commodities.id
           ORDER BY commodities.commodity_name"""
    ).fetchall()
    conn.close()
    imported_crop_ids = session.get("crop_pricing_import_crop_ids", [])
    if imported_crop_ids:
        imported_crop_ids = {int(commodity_id) for commodity_id in imported_crop_ids}
        all_crops = [
            crop for crop in crop_filter_options
            if crop["id"] in imported_crop_ids
        ]
    else:
        all_crops = []
    crop_price_bounds = {
        crop["id"]: price_bounds(crop)
        for crop in commodities
        if crop["pricing_mode"]
    }
    return render_template(
        "admin_catalog.html",
        commodities=commodities,
        crop_price_bounds=crop_price_bounds,
        commodity_categories=commodity_categories,
        all_crop_categories=all_crop_categories,
        crop_filter_options=crop_filter_options,
        all_crops=all_crops,
        search=search,
        category_filter=category_filter,
        crop_filter=crop_filter,
        pricing_rule_row_count=1,
        has_imported_crops=bool(imported_crop_ids),
    )


def _remove_commodity_detail_image(filename):
    if not filename or os.path.basename(filename) != filename:
        return
    image_path = os.path.join(
        current_app.static_folder, "uploads", "commodity_details", filename
    )
    try:
        if os.path.isfile(image_path):
            os.remove(image_path)
    except OSError:
        current_app.logger.exception("Unable to remove replaced commodity image")


def _save_commodity_detail_image(uploaded_file):
    if not uploaded_file or not uploaded_file.filename:
        return None, None
    extension = os.path.splitext(uploaded_file.filename)[1].lower().lstrip(".")
    image_formats = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
    if extension not in image_formats:
        raise ValueError("Choose a PNG, JPG, JPEG, or WEBP commodity image.")

    image_directory = os.path.join(
        current_app.static_folder, "uploads", "commodity_details"
    )
    os.makedirs(image_directory, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{extension}"
    image_path = os.path.join(image_directory, filename)
    try:
        save_sanitized_public_image(
            uploaded_file,
            image_path,
            image_formats[extension],
            current_app.config["MAX_CROP_PHOTO_SIZE_BYTES"],
        )
    except ValueError:
        if os.path.isfile(image_path):
            os.remove(image_path)
        raise
    return filename, image_path


def _commodity_details_category_id():
    category_value = request.form.get("category_id", "").strip()
    if not category_value:
        return None
    category_id = _crop_category_id()
    if category_id is None:
        flash("Select a valid commodity category", "danger")
    return category_id


def _default_price_unit_for_category(category_id=None, category_name=None, conn=None):
    if category_id is not None:
        owns_connection = conn is None
        conn = conn or get_db()
        try:
            category = conn.cursor().execute(
                "SELECT name, default_price_unit FROM commodity_categories WHERE id=?",
                (category_id,),
            ).fetchone()
        finally:
            if owns_connection:
                conn.close()
        if category:
            return category["default_price_unit"] or _default_price_unit_for_category(
                category_name=category["name"]
            )
    normalized_name = str(category_name or "").strip().lower()
    return "pack" if "cigarette" in normalized_name else "kg"


def _price_unit_exists(price_unit, conn=None):
    owns_connection = conn is None
    conn = conn or get_db()
    try:
        return conn.cursor().execute(
            "SELECT unit FROM commodity_price_units WHERE unit=?",
            (price_unit,),
        ).fetchone() is not None
    finally:
        if owns_connection:
            conn.close()


def _price_unit_in_use(price_unit, conn):
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    for table_name, column_name, query in (
        (
            "commodity_categories",
            "default_price_unit",
            "SELECT 1 FROM commodity_categories WHERE default_price_unit=? LIMIT 1",
        ),
        (
            "commodities",
            "default_price_unit",
            "SELECT 1 FROM commodities WHERE default_price_unit=? LIMIT 1",
        ),
        (
            "commodity_pricing",
            "price_unit",
            "SELECT 1 FROM commodity_pricing WHERE price_unit=? LIMIT 1",
        ),
        ("marketplace", "unit", "SELECT 1 FROM marketplace WHERE unit=? LIMIT 1"),
    ):
        if table_name not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if column_name not in columns:
            continue
        if conn.cursor().execute(query, (price_unit,)).fetchone():
            return True
    return False


@_admin_required
def admin_commodity_details():
    conn = get_db()
    cur = conn.cursor()
    categories = cur.execute(
        """SELECT id, name, description, default_price_unit
           FROM commodity_categories ORDER BY name"""
    ).fetchall()
    commodities = cur.execute(
        """SELECT c.id, c.commodity_name, c.description, c.default_image,
                  c.category_id, COALESCE(cc.name, 'Uncategorized') AS category_name,
                  COALESCE(c.default_price_unit, 'kg') AS default_price_unit
           FROM commodities c
           LEFT JOIN commodity_categories cc ON cc.id=c.category_id
           ORDER BY COALESCE(cc.name, 'Uncategorized'), c.commodity_name"""
    ).fetchall()
    price_units = cur.execute(
        "SELECT unit FROM commodity_price_units ORDER BY unit"
    ).fetchall()
    conn.close()
    return render_template(
        "admin_commodity_details.html",
        categories=categories,
        commodities=commodities,
        price_units=price_units,
    )


@_admin_required
def create_commodity_detail_category():
    name = _form_value("name")
    default_price_unit = (
        request.form.get("default_price_unit", "").strip().lower()
        or _default_price_unit_for_category(category_name=name)
    )
    if not name:
        flash("A category name is required", "danger")
        return _redirect_admin("admin_commodity_details")
    if not _price_unit_exists(default_price_unit):
        flash("Choose a registered commodity price unit.", "danger")
        return _redirect_admin("admin_commodity_details")
    conn = get_db()
    try:
        conn.cursor().execute(
            """INSERT INTO commodity_categories(name, description, default_price_unit)
               VALUES (?, ?, ?)""",
            (name, _form_value("description") or None, default_price_unit),
        )
        conn.commit()
        flash("Commodity category created", "success")
    except (IntegrityError, sqlite3.IntegrityError):
        db.session.rollback()
        flash("That category name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin("admin_commodity_details")


@_admin_required
def edit_commodity_detail_category(category_id):
    name = _form_value("name")
    if not name:
        flash("A category name is required", "danger")
        return _redirect_admin("admin_commodity_details")
    default_price_unit = request.form.get("default_price_unit", "").strip().lower()
    conn = get_db()
    try:
        cur = conn.cursor()
        category = cur.execute(
            "SELECT default_price_unit FROM commodity_categories WHERE id=?",
            (category_id,),
        ).fetchone()
        if not category:
            flash("Commodity category not found", "danger")
            return _redirect_admin("admin_commodity_details")
        default_price_unit = (
            default_price_unit or category["default_price_unit"] or "kg"
        )
        if not _price_unit_exists(default_price_unit, conn=conn):
            flash("Choose a registered commodity price unit.", "danger")
            return _redirect_admin("admin_commodity_details")
        cur.execute(
            """UPDATE commodity_categories
               SET name=?, description=?, default_price_unit=? WHERE id=?""",
            (name, _form_value("description") or None, default_price_unit, category_id),
        )
        cur.execute(
            "UPDATE commodities SET default_price_unit=? WHERE category_id=?",
            (default_price_unit, category_id),
        )
        cur.execute(
            """UPDATE commodity_pricing SET price_unit=?
               WHERE commodity_id IN (
                   SELECT id FROM commodities WHERE category_id=?
               )""",
            (default_price_unit, category_id),
        )
        conn.commit()
        flash("Commodity category and its price units updated", "success")
    except (IntegrityError, sqlite3.IntegrityError):
        db.session.rollback()
        flash("That category name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin("admin_commodity_details")


@_admin_required
def create_commodity_detail():
    name = _form_value("name")
    category_value = request.form.get("category_id", "").strip()
    category_id = _commodity_details_category_id()
    if category_value and category_id is None:
        return _redirect_admin("admin_commodity_details")
    if not name:
        flash("A commodity name is required", "danger")
        return _redirect_admin("admin_commodity_details")

    selected_unit = request.form.get("default_price_unit", "").strip().lower()
    if not selected_unit:
        selected_unit = _default_price_unit_for_category(category_id)
    elif not _price_unit_exists(selected_unit):
        flash("Choose a registered commodity price unit.", "danger")
        return _redirect_admin("admin_commodity_details")

    try:
        image_filename, image_path = _save_commodity_detail_image(
            request.files.get("default_image")
        )
    except ValueError as error:
        flash(str(error), "danger")
        return _redirect_admin("admin_commodity_details")

    conn = get_db()
    try:
        conn.cursor().execute(
            """INSERT INTO commodities(
                   commodity_name, category_id, description, default_image, default_price_unit
               ) VALUES (?, ?, ?, ?, ?)""",
            (name, category_id, _form_value("description") or None, image_filename, selected_unit),
        )
        conn.commit()
        flash("Commodity created", "success")
    except (IntegrityError, sqlite3.IntegrityError):
        db.session.rollback()
        if image_path and os.path.isfile(image_path):
            os.remove(image_path)
        flash("That commodity name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin("admin_commodity_details")


@_admin_required
def edit_commodity_detail(commodity_id):
    name = _form_value("name")
    category_value = request.form.get("category_id", "").strip()
    category_id = _commodity_details_category_id()
    if category_value and category_id is None:
        return _redirect_admin("admin_commodity_details")
    if not name:
        flash("A commodity name is required", "danger")
        return _redirect_admin("admin_commodity_details")

    conn = get_db()
    commodity = conn.cursor().execute(
        "SELECT default_image, category_id, default_price_unit "
        "FROM commodities WHERE id=?",
        (commodity_id,),
    ).fetchone()
    if not commodity:
        conn.close()
        flash("Commodity not found", "danger")
        return _redirect_admin("admin_commodity_details")

    selected_unit = request.form.get("default_price_unit", "").strip().lower()
    if not selected_unit:
        selected_unit = (
            _default_price_unit_for_category(category_id, conn=conn)
            if category_id != commodity["category_id"]
            else commodity["default_price_unit"] or "kg"
        )
    elif not _price_unit_exists(selected_unit, conn=conn):
        conn.close()
        flash("Choose a registered commodity price unit.", "danger")
        return _redirect_admin("admin_commodity_details")

    try:
        image_filename, image_path = _save_commodity_detail_image(
            request.files.get("default_image")
        )
    except ValueError as error:
        conn.close()
        flash(str(error), "danger")
        return _redirect_admin("admin_commodity_details")
    image_filename = image_filename or commodity["default_image"]
    try:
        conn.cursor().execute(
            """UPDATE commodities
               SET commodity_name=?, category_id=?, description=?, default_image=?, default_price_unit=?
               WHERE id=?""",
            (
                name,
                category_id,
                _form_value("description") or None,
                image_filename,
                selected_unit,
                commodity_id,
            ),
        )
        conn.commit()
        if category_id != commodity["category_id"]:
            conn.cursor().execute(
                "UPDATE commodity_pricing SET price_unit=? WHERE commodity_id=?",
                (selected_unit, commodity_id),
            )
            conn.commit()
        if image_path and commodity["default_image"] != image_filename:
            _remove_commodity_detail_image(commodity["default_image"])
        flash("Commodity details updated", "success")
    except (IntegrityError, sqlite3.IntegrityError):
        db.session.rollback()
        if image_path and os.path.isfile(image_path):
            os.remove(image_path)
        flash("That commodity name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin("admin_commodity_details")


@_admin_required
def update_commodity_price_unit(commodity_id):
    price_unit = request.form.get("default_price_unit", "").strip().lower()
    if not _price_unit_exists(price_unit):
        flash("Choose a registered commodity price unit.", "danger")
        return redirect(url_for("admin_commodity_details") + "#commodityPriceUnitPanel")

    conn = get_db()
    try:
        result = conn.cursor().execute(
            "UPDATE commodities SET default_price_unit=? WHERE id=?",
            (price_unit, commodity_id),
        )
        if result.rowcount == 0:
            flash("Commodity not found", "danger")
        else:
            conn.cursor().execute(
                "UPDATE commodity_pricing SET price_unit=? WHERE commodity_id=?",
                (price_unit, commodity_id),
            )
            conn.commit()
            flash("Commodity price unit updated", "success")
    finally:
        conn.close()
    return redirect(url_for("admin_commodity_details") + "#commodityPriceUnitPanel")


@_admin_required
def create_commodity_price_unit():
    unit = request.form.get("unit", "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", unit):
        flash("Enter a unit name using 1–32 lowercase letters, numbers, hyphens, or underscores.", "danger")
        return redirect(url_for("admin_commodity_details") + "#commodityPriceUnitPanel")

    conn = get_db()
    try:
        conn.cursor().execute(
            "INSERT INTO commodity_price_units(unit) VALUES (?)",
            (unit,),
        )
        conn.commit()
        flash(f"Price unit '{unit}' created", "success")
    except (IntegrityError, sqlite3.IntegrityError):
        db.session.rollback()
        flash("That price unit already exists", "danger")
    finally:
        conn.close()
    return redirect(url_for("admin_commodity_details") + "#commodityPriceUnitPanel")


@_admin_required
def delete_commodity_price_unit(unit):
    if unit in {"kg", "pc", "pack"}:
        flash("Built-in price units cannot be deleted.", "warning")
        return redirect(url_for("admin_commodity_details") + "#commodityPriceUnitPanel")

    conn = get_db()
    try:
        if not _price_unit_exists(unit, conn=conn):
            flash("Price unit not found.", "danger")
        elif _price_unit_in_use(unit, conn):
            flash(
                "This price unit is still assigned to a category, commodity, "
                "pricing rule, or marketplace listing.",
                "danger",
            )
        else:
            conn.cursor().execute(
                "DELETE FROM commodity_price_units WHERE unit=?",
                (unit,),
            )
            conn.commit()
            flash(f"Price unit '{unit}' deleted.", "success")
    finally:
        conn.close()
    return redirect(url_for("admin_commodity_details") + "#commodityPriceUnitPanel")


@_admin_required
def delete_commodity_detail(commodity_id):
    conn = get_db()
    commodity = conn.cursor().execute(
        "SELECT default_image FROM commodities WHERE id=?", (commodity_id,)
    ).fetchone()
    if not commodity:
        conn.close()
        flash("Commodity not found", "danger")
        return _redirect_admin("admin_commodity_details")

    try:
        conn.cursor().execute("DELETE FROM commodities WHERE id=?", (commodity_id,))
        conn.commit()
        _remove_commodity_detail_image(commodity["default_image"])
        flash("Commodity deleted", "success")
    except (IntegrityError, sqlite3.IntegrityError):
        db.session.rollback()
        flash("This commodity is still in use and cannot be deleted", "danger")
    finally:
        conn.close()
    return _redirect_admin("admin_commodity_details")


@_admin_required
def admin_inventory():
    search = request.args.get("q", "").strip()
    conn = get_db()
    cur = conn.cursor()
    query = """SELECT i.id, i.quantity, i.farmer, i.location, i.date_received, i.source,
                      i.photo_path, i.verification_status, i.distance_from_user,
                      i.capture_time, i.verification_notes, i.reviewed_by,
                      c.commodity_name AS commodity_name
               FROM inventory i LEFT JOIN commodities c ON c.id=i.commodity_id"""
    params = []
    if search:
        query += " WHERE c.commodity_name LIKE ? OR i.farmer LIKE ? OR i.location LIKE ?"
        params = [f"%{search}%"] * 3
    query += " ORDER BY i.date_received DESC"
    inventory = cur.execute(query, params).fetchall()
    conn.close()
    return render_template("admin_inventory.html", inventory=inventory, search=search)


@_admin_required
def admin_marketplace():
    search = request.args.get("q", "").strip()
    conn = get_db()
    cur = conn.cursor()
    listings = cur.execute(
        """SELECT m.id, m.user_id, m.username, m.commodity_id, m.commodity_name,
                  m.amount, m.price, m.unit, m.status, m.buyer_username,
                  m.listing_type, m.available_date, m.description, m.listing_date,
                  m.main_image,
                  u.username AS seller_name
           FROM marketplace m LEFT JOIN users u ON u.id=m.user_id
           WHERE ? = '' OR m.commodity_name LIKE ? OR COALESCE(u.username, m.username, '') LIKE ?
             OR COALESCE(m.status, '') LIKE ?
           ORDER BY m.listing_date DESC, m.id DESC""",
        (search, f"%{search}%", f"%{search}%", f"%{search}%"),
    ).fetchall()
    users = cur.execute(
        "SELECT id, username, location FROM users "
        "WHERE COALESCE(role, 'user') <> 'buyer' ORDER BY username"
    ).fetchall()
    commodities = cur.execute("SELECT id, commodity_name FROM commodities ORDER BY commodity_name").fetchall()
    conn.close()
    return render_template(
        "admin_marketplace.html",
        listings=listings,
        users=users,
        commodities=commodities,
        search=search,
    )


def _save_admin_marketplace_thumbnail(uploaded_file):
    extension = os.path.splitext(uploaded_file.filename)[1].lower().lstrip(".")
    expected_format = ADMIN_MARKETPLACE_IMAGE_FORMATS.get(extension)
    if not expected_format:
        raise ValueError("Choose a PNG, JPG, JPEG, GIF, or WEBP thumbnail.")

    image_directory = os.path.join(
        current_app.static_folder, "uploads", "marketplace"
    )
    os.makedirs(image_directory, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{extension}"
    image_path = os.path.join(image_directory, filename)
    try:
        save_sanitized_public_image(
            uploaded_file,
            image_path,
            expected_format,
            current_app.config["MAX_CROP_PHOTO_SIZE_BYTES"],
        )
    except ValueError:
        if os.path.isfile(image_path):
            os.remove(image_path)
        raise
    return filename, image_path


@_admin_required
def update_admin_marketplace_thumbnail(listing_id):
    thumbnail = request.files.get("thumbnail")
    if not thumbnail or not thumbnail.filename:
        flash("Choose a thumbnail image to upload.", "danger")
        return _redirect_admin("admin_marketplace")

    conn = get_db()
    cur = conn.cursor()
    listing = cur.execute(
        "SELECT main_image FROM marketplace WHERE id=?",
        (listing_id,),
    ).fetchone()
    if not listing:
        conn.close()
        flash("Marketplace listing not found.", "danger")
        return _redirect_admin("admin_marketplace")

    try:
        filename, image_path = _save_admin_marketplace_thumbnail(thumbnail)
    except ValueError as error:
        conn.close()
        flash(str(error), "danger")
        return _redirect_admin("admin_marketplace")

    old_image = listing["main_image"]
    try:
        cur.execute(
            """UPDATE marketplace
               SET main_image=?, thumbnail_verified=0, thumbnail_latitude=NULL,
                   thumbnail_longitude=NULL, thumbnail_distance_meters=NULL,
                   thumbnail_captured_at=NULL
               WHERE id=?""",
            (filename, listing_id),
        )
        if old_image:
            cur.execute(
                "DELETE FROM marketplace_images WHERE listing_id=? AND image_filename=?",
                (listing_id, old_image),
            )
        cur.execute(
            "UPDATE marketplace_images SET display_order=display_order+1 WHERE listing_id=?",
            (listing_id,),
        )
        cur.execute(
            """INSERT INTO marketplace_images
               (listing_id, image_filename, display_order, created_at)
               VALUES (?, ?, 0, ?)""",
            (
                listing_id,
                filename,
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
    except Exception:
        conn.close()
        try:
            if os.path.isfile(image_path):
                os.remove(image_path)
        except OSError:
            current_app.logger.exception("Unable to remove uncommitted marketplace thumbnail")
        raise
    conn.close()

    if old_image and os.path.basename(old_image) == old_image:
        old_image_path = os.path.join(
            current_app.static_folder, "uploads", "marketplace", old_image
        )
        try:
            if os.path.isfile(old_image_path):
                os.remove(old_image_path)
        except OSError:
            current_app.logger.exception("Unable to remove replaced marketplace thumbnail")

    flash("Marketplace listing thumbnail updated.", "success")
    return _redirect_admin("admin_marketplace")


@_admin_required
def admin_marketplace_transactions():
    search = request.args.get("q", "").strip()
    completion_filter = request.args.get("completion", "").strip().lower()
    if completion_filter not in {"", "completed", "incomplete"}:
        completion_filter = ""

    conn = get_db()
    cur = conn.cursor()
    completion_sql = (
        f"CASE WHEN {MARKETPLACE_TRANSACTION_COMPLETED} "
        "THEN 'completed' ELSE 'incomplete' END"
    )
    # These predicates are fixed module-level SQL fragments; request data is bound.
    totals_query = (
        "SELECT COUNT(*) AS total,\n"  # nosec B608
        "       SUM(CASE WHEN " + MARKETPLACE_TRANSACTION_COMPLETED
        + " THEN 1 ELSE 0 END) AS completed\n"
        "FROM marketplace m\n"
        "WHERE " + MARKETPLACE_TRANSACTION_FILTER
    )
    totals = cur.execute(totals_query).fetchone()
    transactions_query = (
        "SELECT * FROM (\n"  # nosec B608
        "    SELECT m.id, m.commodity_name, m.username,\n"
        "           COALESCE(u.username, m.username) AS seller_name,\n"
        "           m.buyer_username, m.amount, m.preorder_quantity, m.unit, m.price,\n"
        "           m.listing_type, m.order_status, m.preorder_status, m.status,\n"
        "           m.order_date, m.delivery_date, m.delivery_confirmed,\n"
        "           m.buyer_confirmed, m.buyer_rating,\n"
        "           " + completion_sql + " AS completion_state,\n"
        "           COALESCE(m.preorder_quantity, m.amount) AS transaction_quantity\n"
        "    FROM marketplace m\n"
        "    LEFT JOIN users u ON u.id = m.user_id\n"
        "    WHERE " + MARKETPLACE_TRANSACTION_FILTER + "\n"
        ") marketplace_transactions\n"
        "WHERE (? = '' OR CAST(id AS TEXT) LIKE ? OR COALESCE(commodity_name, '') LIKE ?\n"
        "       OR COALESCE(seller_name, '') LIKE ? OR COALESCE(buyer_username, '') LIKE ?\n"
        "       OR COALESCE(order_status, '') LIKE ? OR COALESCE(preorder_status, '') LIKE ?)\n"
        "  AND (? = '' OR completion_state = ?)\n"
        "ORDER BY COALESCE(order_date, '') DESC, id DESC"
    )
    transactions = cur.execute(
        transactions_query,
        (
            search, f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%",
            f"%{search}%", f"%{search}%", completion_filter, completion_filter,
        ),
    ).fetchall()
    conn.close()

    total_count = totals["total"] or 0
    completed_count = totals["completed"] or 0
    return render_template(
        "admin_marketplace_transactions.html",
        transactions=transactions,
        search=search,
        completion_filter=completion_filter,
        total_count=total_count,
        completed_count=completed_count,
        incomplete_count=total_count - completed_count,
    )


@_admin_required
def admin_face_scan_monitor():
    search = request.args.get("q", "").strip()[:100]
    status_filter = request.args.get("status", "").strip().lower()
    allowed_statuses = {"", "in_progress", "expired", "failed", "consumed"}
    if status_filter not in allowed_statuses:
        status_filter = ""

    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.cursor()
    try:
        stats = {
            "verified_profiles": cur.execute(
                "SELECT COUNT(*) AS count FROM users "
                "WHERE profile_photo_scan_verified_at IS NOT NULL"
            ).fetchone()["count"],
            "active_challenges": cur.execute(
                "SELECT COUNT(*) AS count FROM profile_photo_challenges "
                "WHERE consumed_at IS NULL AND expires_at > ? "
                "AND failed_attempts < ?",
                (now, MAX_SCAN_ATTEMPTS),
            ).fetchone()["count"],
            "expired_challenges": cur.execute(
                "SELECT COUNT(*) AS count FROM profile_photo_challenges "
                "WHERE consumed_at IS NULL AND expires_at <= ?",
                (now,),
            ).fetchone()["count"],
            "failed_challenges": cur.execute(
                "SELECT COUNT(*) AS count FROM profile_photo_challenges "
                "WHERE failed_attempts >= ?",
                (MAX_SCAN_ATTEMPTS,),
            ).fetchone()["count"],
            "unverified_captured_photos": cur.execute(
                "SELECT COUNT(*) AS count FROM users "
                "WHERE profile_photo_captured_at IS NOT NULL "
                "AND profile_photo_scan_verified_at IS NULL"
            ).fetchone()["count"],
        }
        challenges = cur.execute(
            """SELECT c.username, u.role, c.created_at, c.last_stage_at,
                       c.expires_at, c.consumed_at, c.current_stage,
                       c.failed_attempts,
                       CASE WHEN c.failed_attempts >= ? THEN 'failed'
                            WHEN c.consumed_at IS NOT NULL THEN 'consumed'
                            WHEN c.expires_at <= ? THEN 'expired'
                            ELSE 'in_progress' END AS scan_status
                FROM profile_photo_challenges c
                LEFT JOIN users u ON u.username = c.username
                WHERE (? = '' OR LOWER(COALESCE(c.username, '')) LIKE LOWER(?))
                  AND (? = '' OR (
                       CASE WHEN c.failed_attempts >= ? THEN 'failed'
                            WHEN c.consumed_at IS NOT NULL THEN 'consumed'
                            WHEN c.expires_at <= ? THEN 'expired'
                            ELSE 'in_progress' END
                  ) = ?)
                ORDER BY c.created_at DESC
                LIMIT 100""",
            (
                MAX_SCAN_ATTEMPTS, now, search, f"%{search}%", status_filter,
                MAX_SCAN_ATTEMPTS, now, status_filter,
            ),
        ).fetchall()
        verified_profiles = cur.execute(
            """SELECT username, role, profile_photo_captured_at,
                      profile_photo_scan_verified_at
               FROM users
               WHERE profile_photo_scan_verified_at IS NOT NULL
                 AND (? = '' OR LOWER(COALESCE(username, '')) LIKE LOWER(?))
               ORDER BY profile_photo_scan_verified_at DESC
               LIMIT 100""",
            (search, f"%{search}%"),
        ).fetchall()
    finally:
        conn.close()

    return render_template(
        "admin_face_scan_monitor.html",
        stats=stats,
        challenges=challenges,
        verified_profiles=verified_profiles,
        search=search,
        status_filter=status_filter,
    )


@_admin_required
def admin_online_payments():
    search = request.args.get("q", "").strip()[:100]
    status_filter = request.args.get("status", "").strip().lower()
    allowed_statuses = {
        "", "awaiting_payment", "to_pay", "to_ship", "to_receive", "completed",
        "cancelled",
    }
    if status_filter not in allowed_statuses:
        status_filter = ""

    conn = get_db()
    cur = conn.cursor()
    try:
        online_payment_enabled = is_online_payment_enabled(cur)
        totals = cur.execute(
            """SELECT COUNT(*) AS total,
                       SUM(CASE WHEN m.order_status = 'awaiting_payment'
                                THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN m.payment_method = 'xendit'
                                      AND m.order_status <> 'awaiting_payment'
                                THEN 1 ELSE 0 END) AS confirmed,
                       SUM(CASE WHEN m.payment_method = 'xendit'
                                      AND m.order_status <> 'awaiting_payment'
                                THEN COALESCE(m.price, 0) * COALESCE(m.amount, 0)
                                ELSE 0 END) AS confirmed_value
                FROM marketplace m
                WHERE m.payment_method = 'xendit'
                   OR m.xendit_reference_id IS NOT NULL"""
        ).fetchone()
        payments = cur.execute(
            """SELECT m.id, m.username AS seller, m.buyer_username,
                       m.commodity_name, m.amount, m.unit, m.price,
                       COALESCE(m.price, 0) * COALESCE(m.amount, 0) AS payment_amount,
                       m.order_status, m.status AS listing_status, m.order_date,
                       m.payment_method, m.xendit_reference_id, m.xendit_session_id
                FROM marketplace m
                WHERE (m.payment_method = 'xendit'
                       OR m.xendit_reference_id IS NOT NULL)
                  AND (? = '' OR CAST(m.id AS TEXT) LIKE ?
                       OR COALESCE(m.xendit_reference_id, '') LIKE ?
                       OR COALESCE(m.xendit_session_id, '') LIKE ?
                       OR COALESCE(m.username, '') LIKE ?
                       OR COALESCE(m.buyer_username, '') LIKE ?
                       OR COALESCE(m.commodity_name, '') LIKE ?
                       OR COALESCE(m.order_status, '') LIKE ?)
                  AND (? = '' OR m.order_status = ?)
                ORDER BY COALESCE(m.order_date, '') DESC, m.id DESC
                LIMIT 200""",
            (
                search, f"%{search}%", f"%{search}%", f"%{search}%",
                f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%",
                status_filter, status_filter,
            ),
        ).fetchall()
        payment_events = cur.execute(
            """SELECT id, reference_id, order_ids, event_name, result,
                      session_id, amount, currency, received_at
               FROM xendit_payment_events
               WHERE (? = '' OR reference_id LIKE ? OR order_ids LIKE ?
                      OR event_name LIKE ? OR result LIKE ? OR session_id LIKE ?)
               ORDER BY received_at DESC, id DESC
               LIMIT 100""",
            (
                search, f"%{search}%", f"%{search}%", f"%{search}%",
                f"%{search}%", f"%{search}%",
            ),
        ).fetchall()
        failed_event_count = cur.execute(
            """SELECT COUNT(*) AS count
               FROM xendit_payment_events
               WHERE result IN (
                   'failed', 'not_succeeded', 'session_mismatch',
                   'amount_mismatch', 'currency_mismatch', 'unknown'
               )"""
        ).fetchone()["count"]
    finally:
        conn.close()

    return render_template(
        "admin_online_payments.html",
        payments=payments,
        payment_events=payment_events,
        search=search,
        status_filter=status_filter,
        total_count=totals["total"] or 0,
        pending_count=totals["pending"] or 0,
        confirmed_count=totals["confirmed"] or 0,
        confirmed_value=totals["confirmed_value"] or 0,
        failed_event_count=failed_event_count,
        online_payment_enabled=online_payment_enabled,
    )


@_admin_required
def toggle_online_payments():
    enabled = request.form.get("enabled")
    if enabled not in {"0", "1"}:
        flash("Choose whether online payments should be enabled or disabled.", "danger")
        return redirect(url_for("admin_online_payments"))

    conn = get_db()
    try:
        conn.cursor().execute(
            "INSERT INTO app_settings(setting_key, setting_value) "
            "VALUES ('online_payments_enabled', ?) "
            "ON CONFLICT(setting_key) DO UPDATE "
            "SET setting_value = excluded.setting_value",
            (enabled,),
        )
        conn.commit()
    finally:
        conn.close()

    flash(
        "Online payments enabled." if enabled == "1" else "Online payments disabled.",
        "success",
    )
    return redirect(url_for("admin_online_payments"))


def _admin_marketplace_values():
    username = _form_value("username")
    crop_id_value = _form_value("commodity_id") or _form_value("crop_id")
    unit = "kg"
    description = _form_value("description")[:2000]
    listing_type = _form_value("listing_type")
    status = _form_value("status") or "available"

    if not username or not crop_id_value:
        raise ValueError("Choose a seller and commodity.")
    if listing_type not in {"standard", "preorder", "looking_for"}:
        raise ValueError("Choose a valid listing type.")
    if status not in {"available", "expired", "cancelled"}:
        raise ValueError("Choose a valid listing status.")
    try:
        commodity_id = int(crop_id_value)
        amount = int(_form_value("amount"))
        price = float(_form_value("price"))
        expiry_days = int(_form_value("expiry_days") or "30")
    except ValueError as error:
        raise ValueError("Choose a valid commodity and enter valid quantity, price, and expiry numbers.") from error
    if amount <= 0 or not math.isfinite(price) or price <= 0:
        raise ValueError("Quantity and price must be greater than zero.")
    if expiry_days < 1 or expiry_days > 365:
        raise ValueError("Expiry must be between 1 and 365 days.")

    available_date = _form_value("available_date")
    if listing_type == "preorder":
        try:
            datetime.strptime(available_date, "%Y-%m-%dT%H:%M")
        except ValueError as error:
            raise ValueError("Pre-orders require a valid ready date and time.") from error
        available_date = available_date.replace("T", " ")
    else:
        available_date = None

    return username, commodity_id, amount, price, unit, description, listing_type, status, available_date, expiry_days


@_admin_required
def create_admin_marketplace_listing():
    try:
        values = _admin_marketplace_values()
    except ValueError as error:
        flash(str(error), "danger")
        return _redirect_admin("admin_marketplace")

    username, commodity_id, amount, price, unit, description, listing_type, status, available_date, expiry_days = values
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(
        "SELECT id, username, location, role FROM users WHERE username=?",
        (username,),
    ).fetchone()
    crop = cur.execute(
        "SELECT id, commodity_name FROM commodities WHERE id=?",
        (commodity_id,),
    ).fetchone()
    if not user or not crop or user["role"] == "buyer":
        conn.close()
        flash("Choose an existing seller and commodity.", "danger")
        return _redirect_admin("admin_marketplace")
    if listing_type != "looking_for":
        pricing = cur.execute(
            "SELECT pricing_mode, price_unit, reference_price, price_range, "
            "minimum_price, maximum_price FROM commodity_pricing WHERE commodity_id=?",
            (commodity_id,),
        ).fetchone()
        price_error = seller_price_error(price, unit, pricing)
        if price_error:
            conn.close()
            flash(price_error, "danger")
            return _redirect_admin("admin_marketplace")

    now = datetime.now(timezone.utc)
    cur.execute(
        """INSERT INTO marketplace(
               user_id, username, commodity_id, commodity_name, amount, price, unit, status,
               listing_date, expiry_date, description, location, listing_type, available_date
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user["id"], user["username"], crop["id"], crop["commodity_name"], amount, price,
            unit, status, now.strftime("%Y-%m-%d %H:%M:%S"),
            (now + timedelta(days=expiry_days)).strftime("%Y-%m-%d %H:%M:%S"),
            description, user["location"], listing_type, available_date,
        ),
    )
    conn.commit()
    conn.close()
    flash("Marketplace listing created.", "success")
    return _redirect_admin("admin_marketplace")


@_admin_required
def edit_admin_marketplace_listing(listing_id):
    try:
        values = _admin_marketplace_values()
    except ValueError as error:
        flash(str(error), "danger")
        return _redirect_admin("admin_marketplace")

    username, commodity_id, amount, price, unit, description, listing_type, status, available_date, _ = values
    conn = get_db()
    cur = conn.cursor()
    listing = cur.execute(
        "SELECT buyer_username, status, username FROM marketplace WHERE id=?",
        (listing_id,),
    ).fetchone()
    if not listing:
        conn.close()
        flash("Marketplace listing not found.", "danger")
        return _redirect_admin("admin_marketplace")
    if listing["buyer_username"] or listing["status"] not in ADMIN_EDITABLE_MARKETPLACE_STATUSES:
        conn.close()
        flash("Listings with an order or completed transaction cannot be edited.", "danger")
        return _redirect_admin("admin_marketplace")

    user = cur.execute(
        "SELECT id, username, location, role FROM users WHERE username=?",
        (username,),
    ).fetchone()
    crop = cur.execute(
        "SELECT id, commodity_name FROM commodities WHERE id=?",
        (commodity_id,),
    ).fetchone()
    if not user or not crop or user["role"] == "buyer":
        conn.close()
        flash("Choose an existing seller and commodity.", "danger")
        return _redirect_admin("admin_marketplace")
    if listing_type != "looking_for":
        pricing = cur.execute(
            "SELECT pricing_mode, price_unit, reference_price, price_range, "
            "minimum_price, maximum_price FROM commodity_pricing WHERE commodity_id=?",
            (commodity_id,),
        ).fetchone()
        price_error = seller_price_error(price, unit, pricing)
        if price_error:
            conn.close()
            flash(price_error, "danger")
            return _redirect_admin("admin_marketplace")

    seller_changed = username != listing["username"]
    update_fields = (
            user["id"], user["username"], crop["id"], crop["commodity_name"], amount, price,
            unit, status, description, user["location"], listing_type, available_date,
        )
    if seller_changed:
        cur.execute(
            """UPDATE marketplace
               SET user_id=?, username=?, commodity_id=?, commodity_name=?, amount=?, price=?, unit=?,
                   status=?, description=?, location=?, listing_type=?, available_date=?,
                   main_image=NULL, thumbnail_verified=0, thumbnail_latitude=NULL,
                   thumbnail_longitude=NULL, thumbnail_distance_meters=NULL,
                   thumbnail_captured_at=NULL
               WHERE id=?""",
            update_fields + (listing_id,),
        )
    else:
        cur.execute(
            """UPDATE marketplace
               SET user_id=?, username=?, commodity_id=?, commodity_name=?, amount=?, price=?, unit=?,
                   status=?, description=?, location=?, listing_type=?, available_date=?
               WHERE id=?""",
            update_fields + (listing_id,),
        )
    conn.commit()
    conn.close()
    flash("Marketplace listing updated.", "success")
    return _redirect_admin("admin_marketplace")


@_admin_required
def delete_admin_marketplace_listing(listing_id):
    conn = get_db()
    cur = conn.cursor()
    listing = cur.execute(
        "SELECT commodity_name, buyer_username, status FROM marketplace WHERE id=?",
        (listing_id,),
    ).fetchone()
    if not listing:
        conn.close()
        flash("Marketplace listing not found.", "danger")
        return _redirect_admin("admin_marketplace")
    if listing["buyer_username"] or listing["status"] not in ADMIN_EDITABLE_MARKETPLACE_STATUSES:
        conn.close()
        flash("Listings with an order or completed transaction cannot be deleted.", "danger")
        return _redirect_admin("admin_marketplace")

    cur.execute("DELETE FROM marketplace WHERE id=?", (listing_id,))
    conn.commit()
    conn.close()
    flash(f"Marketplace listing for {listing['commodity_name']} deleted.", "success")
    return _redirect_admin("admin_marketplace")


@_admin_required
def admin_review_geotag(item_id):
    decision = _form_value("decision")
    if decision not in {"approved", "rejected"}:
        flash("Choose approve or reject for this harvest review", "danger")
        return redirect(url_for("admin_inventory"))

    conn = get_db()
    cur = conn.cursor()
    record = cur.execute(
        "SELECT verification_notes, source FROM inventory WHERE id=?",
        (item_id,),
    ).fetchone()
    if not record:
        conn.close()
        flash("Harvest record not found", "danger")
        return redirect(url_for("admin_inventory"))
    if record["source"] not in (None, "harvest"):
        conn.close()
        flash("Only harvest submissions can receive a geotag decision", "danger")
        return redirect(url_for("admin_inventory"))

    reviewed_at = datetime.now(timezone.utc).isoformat()
    review_note = _form_value("review_note")[:1000]
    existing_note = record["verification_notes"] or ""
    if review_note:
        review_note = f"{existing_note} Admin review: {review_note}".strip()
    else:
        review_note = existing_note or None
    cur.execute(
        "UPDATE inventory SET verification_status=?, reviewed_by=?, reviewed_at=?, "
        "verification_notes=? "
        "WHERE id=?",
        (
            decision,
            session["user"],
            reviewed_at,
            review_note,
            item_id,
        ),
    )
    conn.commit()
    conn.close()
    feedback_category = "success" if decision == "approved" else "danger"
    flash(f"Harvest submission {decision}.", feedback_category)
    return redirect(url_for("admin_inventory"))


@_admin_required
def admin_knowledge_categories():
    search = request.args.get("q", "").strip()
    conn = get_db()
    cur = conn.cursor()
    categories = cur.execute(
        """SELECT category_id, category_name FROM knowledge_categories
           WHERE ? = '' OR category_name LIKE ? ORDER BY category_name""",
        (search, f"%{search}%"),
    ).fetchall()
    conn.close()
    return render_template("admin_knowledge_categories.html", categories=categories, search=search)


def _audit_log_filters():
    search = request.args.get("q", "").strip()[:200]
    category = request.args.get("category", "").strip()
    method = request.args.get("method", "").strip().upper()
    result = request.args.get("result", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    valid_categories = {
        "Administration", "Application", "API", "Authentication",
        "Inventory", "Knowledge", "Marketplace", "Messages", "Notifications", "Profile",
    }
    valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}
    if category and category not in valid_categories:
        abort(400, description="Invalid audit-log category.")
    if method and method not in valid_methods:
        abort(400, description="Invalid audit-log method.")
    if result and result not in {"success", "failure"}:
        abort(400, description="Invalid audit-log result filter.")

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if end_date else None
    except ValueError:
        abort(400, description="Audit-log dates must use YYYY-MM-DD.")
    if start and end and start > end:
        abort(400, description="The start date must not be after the end date.")

    filters = []
    if search:
        pattern = f"%{search}%"
        filters.append(or_(
            AuditEvent.actor.ilike(pattern),
            AuditEvent.action.ilike(pattern),
            AuditEvent.category.ilike(pattern),
            AuditEvent.endpoint.ilike(pattern),
            AuditEvent.path.ilike(pattern),
            AuditEvent.ip_address.ilike(pattern),
        ))
    if category:
        filters.append(AuditEvent.category == category)
    if method:
        filters.append(AuditEvent.method == method)
    if result == "success":
        filters.append(AuditEvent.status_code < 400)
    elif result == "failure":
        filters.append(AuditEvent.status_code >= 400)
    if start:
        filters.append(AuditEvent.occurred_at >= start)
    if end:
        filters.append(AuditEvent.occurred_at < end + timedelta(days=1))

    return {
        "filters": filters,
        "search": search,
        "category": category,
        "method": method,
        "result": result,
        "start_date": start_date,
        "end_date": end_date,
    }


def _csv_cell(value):
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


@_superadmin_required
def admin_audit_logs():
    filter_values = _audit_log_filters()
    filters = filter_values["filters"]
    base_query = select(AuditEvent).where(*filters)

    if request.args.get("export") == "csv":
        def generate_csv():
            yield "\ufeff"
            with db.engine.connect() as connection:
                statement = (
                    select(AuditEvent.__table__)
                    .where(*filters)
                    .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
                )
                rows = connection.execution_options(stream_results=True).execute(statement)
                output = io.StringIO(newline="")
                writer = csv.writer(output)
                writer.writerow((
                    "Occurred at (UTC)", "Actor", "Role", "Action", "Category",
                    "Method", "Endpoint", "Path", "Status code", "Duration (ms)",
                    "IP address", "User agent", "Route parameters",
                ))
                yield output.getvalue()
                for row in rows:
                    event = row._mapping
                    output = io.StringIO(newline="")
                    writer = csv.writer(output)
                    writer.writerow(_csv_cell(value) for value in (
                        event["occurred_at"].isoformat() if event["occurred_at"] else "",
                        event["actor"],
                        event["role"],
                        event["action"],
                        event["category"],
                        event["method"],
                        event["endpoint"],
                        event["path"],
                        event["status_code"],
                        event["duration_ms"],
                        event["ip_address"],
                        event["user_agent"],
                        event["details"],
                    ))
                    yield output.getvalue()

        filename = f"agri-direct-audit-log-{datetime.now(timezone.utc):%Y%m%d}.csv"
        return Response(
            stream_with_context(generate_csv()),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    page = max(request.args.get("page", 1, type=int), 1)
    page_size = 50
    total = db.session.scalar(
        select(func.count()).select_from(AuditEvent).where(*filters)
    ) or 0
    pages = max(math.ceil(total / page_size), 1)
    events = db.session.scalars(
        base_query
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = db.session.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.occurred_at >= today_start)
    ) or 0
    failure_count = db.session.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.status_code >= 400)
    ) or 0
    categories = db.session.scalars(
        select(AuditEvent.category).distinct().order_by(AuditEvent.category)
    ).all()

    return render_template(
        "admin_audit_logs.html",
        events=events,
        total=total,
        today_count=today_count,
        failure_count=failure_count,
        categories=categories,
        page=page,
        pages=pages,
        page_size=page_size,
        **{key: value for key, value in filter_values.items() if key != "filters"},
    )


@_superadmin_required
def admin_slow_queries():
    stats = db.session.execute(
        select(
            SlowQueryStat.statement,
            SlowQueryStat.call_count,
            SlowQueryStat.total_time_ms,
            SlowQueryStat.max_time_ms,
            SlowQueryStat.last_seen_at,
        )
        .order_by(SlowQueryStat.total_time_ms.desc())
        .limit(100)
    ).mappings().all()
    totals = db.session.execute(
        select(
            func.coalesce(func.sum(SlowQueryStat.call_count), 0).label("calls"),
            func.coalesce(func.sum(SlowQueryStat.total_time_ms), 0).label("total_time_ms"),
        )
    ).one()

    return render_template(
        "admin_slow_queries.html",
        stats=stats,
        total_calls=totals.calls,
        total_time_ms=totals.total_time_ms,
        threshold_ms=current_app.config["SLOW_QUERY_THRESHOLD_MS"],
    )


@_admin_required
def admin_profile_reports():
    reports = db.session.scalars(
        select(ProfileReport).order_by(
            ProfileReport.created_at.desc(),
            ProfileReport.id.desc(),
        )
    ).all()
    return render_template("admin_profile_reports.html", reports=reports)


@_admin_required
def download_profile_report_evidence(report_id):
    report = db.session.get(ProfileReport, report_id)
    if not report or not report.evidence_filename:
        abort(404)
    evidence_dir = os.path.join(
        current_app.config["UPLOAD_FOLDER"],
        "profile_report_evidence",
    )
    return send_from_directory(
        evidence_dir,
        report.evidence_filename,
        as_attachment=True,
        download_name=report.evidence_original_name or "evidence",
        mimetype="application/octet-stream",
    )


@_admin_required
def review_profile_report(report_id):
    report = db.session.get(ProfileReport, report_id)
    if not report:
        abort(404)
    if report.status == "open":
        report.status = "reviewed"
        report.reviewed_by = session["user"]
        report.reviewed_at = datetime.now(timezone.utc)
        db.session.commit()
        flash("Report marked as reviewed", "success")
    return redirect(url_for("admin_profile_reports"))


@_admin_required
def admin_listing_photo_alerts():
    alerts = db.session.scalars(
        select(ListingPhotoLocationAlert).order_by(
            ListingPhotoLocationAlert.created_at.desc(),
            ListingPhotoLocationAlert.id.desc(),
        )
    ).all()
    return render_template("admin_listing_photo_alerts.html", alerts=alerts)


@_admin_required
def review_listing_photo_alert(alert_id):
    alert = db.session.get(ListingPhotoLocationAlert, alert_id)
    if not alert:
        abort(404)
    if alert.status == "open":
        alert.status = "reviewed"
        alert.reviewed_by = session["user"]
        alert.reviewed_at = datetime.now(timezone.utc)
        db.session.commit()
        flash("Listing photo alert marked as reviewed", "success")
    return redirect(url_for("admin_listing_photo_alerts"))


def page_not_found(e):
    return render_template('404.html'), 404

def internal_error(e):
    return render_template('500.html'), 500

def register(application):
    """Register this domain's routes on the existing Flask app."""
    application.add_url_rule('/admin/knowledge', endpoint='admin_knowledge', view_func=admin_knowledge)
    application.add_url_rule('/admin/knowledge/create', endpoint='create_knowledge_post', view_func=create_knowledge_post, methods=['GET', 'POST'])
    application.add_url_rule('/admin/knowledge/edit/<int:post_id>', endpoint='edit_knowledge_post', view_func=edit_knowledge_post, methods=['GET', 'POST'])
    application.add_url_rule('/admin/knowledge/delete/<int:post_id>', endpoint='delete_knowledge_post', view_func=delete_knowledge_post, methods=['POST'])
    application.add_url_rule('/admin', endpoint='admin', view_func=admin)
    application.add_url_rule('/admin/audit-logs', endpoint='admin_audit_logs', view_func=admin_audit_logs)
    application.add_url_rule('/admin/profile-reports', endpoint='admin_profile_reports', view_func=admin_profile_reports)
    application.add_url_rule('/admin/profile-reports/<int:report_id>/evidence', endpoint='download_profile_report_evidence', view_func=download_profile_report_evidence)
    application.add_url_rule('/admin/profile-reports/<int:report_id>/review', endpoint='review_profile_report', view_func=review_profile_report, methods=['POST'])
    application.add_url_rule('/admin/listing-photo-alerts', endpoint='admin_listing_photo_alerts', view_func=admin_listing_photo_alerts)
    application.add_url_rule('/admin/listing-photo-alerts/<int:alert_id>/review', endpoint='review_listing_photo_alert', view_func=review_listing_photo_alert, methods=['POST'])
    application.add_url_rule('/admin/slow-queries', endpoint='admin_slow_queries', view_func=admin_slow_queries)
    application.add_url_rule('/admin/users', endpoint='admin_users', view_func=admin_users)
    application.add_url_rule('/admin/catalog', endpoint='admin_catalog', view_func=admin_catalog)
    application.add_url_rule('/admin/commodity-details', endpoint='admin_commodity_details', view_func=admin_commodity_details)
    application.add_url_rule('/admin/commodity-details/categories', endpoint='create_commodity_detail_category', view_func=create_commodity_detail_category, methods=['POST'])
    application.add_url_rule('/admin/commodity-details/categories/<int:category_id>', endpoint='edit_commodity_detail_category', view_func=edit_commodity_detail_category, methods=['POST'])
    application.add_url_rule('/admin/commodity-details/price-units', endpoint='create_commodity_price_unit', view_func=create_commodity_price_unit, methods=['POST'])
    application.add_url_rule('/admin/commodity-details/price-units/<unit>/delete', endpoint='delete_commodity_price_unit', view_func=delete_commodity_price_unit, methods=['POST'])
    application.add_url_rule('/admin/commodity-details/commodities', endpoint='create_commodity_detail', view_func=create_commodity_detail, methods=['POST'])
    application.add_url_rule('/admin/commodity-details/commodities/<int:commodity_id>', endpoint='edit_commodity_detail', view_func=edit_commodity_detail, methods=['POST'])
    application.add_url_rule('/admin/commodity-details/commodities/<int:commodity_id>/price-unit', endpoint='update_commodity_price_unit', view_func=update_commodity_price_unit, methods=['POST'])
    application.add_url_rule('/admin/commodity-details/commodities/<int:commodity_id>/delete', endpoint='delete_commodity_detail', view_func=delete_commodity_detail, methods=['POST'])
    application.add_url_rule('/admin/catalog/pricing/template', endpoint='download_crop_pricing_template', view_func=download_crop_pricing_template)
    application.add_url_rule('/admin/catalog/pricing/import', endpoint='import_crop_pricing', view_func=import_crop_pricing, methods=['POST'])
    application.add_url_rule('/admin/inventory', endpoint='admin_inventory', view_func=admin_inventory)
    application.add_url_rule('/admin/marketplace', endpoint='admin_marketplace', view_func=admin_marketplace)
    application.add_url_rule('/admin/marketplace/transactions', endpoint='admin_marketplace_transactions', view_func=admin_marketplace_transactions)
    application.add_url_rule('/admin/face-scan-monitor', endpoint='admin_face_scan_monitor', view_func=admin_face_scan_monitor)
    application.add_url_rule('/admin/online-payments', endpoint='admin_online_payments', view_func=admin_online_payments)
    application.add_url_rule(
        '/admin/online-payments/availability',
        endpoint='toggle_online_payments',
        view_func=toggle_online_payments,
        methods=['POST'],
    )
    application.add_url_rule('/admin/marketplace/create', endpoint='create_admin_marketplace_listing', view_func=create_admin_marketplace_listing, methods=['POST'])
    application.add_url_rule('/admin/marketplace/edit/<int:listing_id>', endpoint='edit_admin_marketplace_listing', view_func=edit_admin_marketplace_listing, methods=['POST'])
    application.add_url_rule('/admin/marketplace/thumbnail/<int:listing_id>', endpoint='update_admin_marketplace_thumbnail', view_func=update_admin_marketplace_thumbnail, methods=['POST'])
    application.add_url_rule('/admin/marketplace/delete/<int:listing_id>', endpoint='delete_admin_marketplace_listing', view_func=delete_admin_marketplace_listing, methods=['POST'])
    application.add_url_rule('/admin/geotag/<int:item_id>/review', endpoint='admin_review_geotag', view_func=admin_review_geotag, methods=['POST'])
    application.add_url_rule('/admin/knowledge-categories', endpoint='admin_knowledge_categories', view_func=admin_knowledge_categories)
    application.add_url_rule('/admin/users/create', endpoint='create_admin_user', view_func=create_admin_user, methods=['POST'])
    application.add_url_rule('/admin/users/edit/<int:user_id>', endpoint='edit_admin_user', view_func=edit_admin_user, methods=['POST'])
    application.add_url_rule('/admin/users/<int:user_id>/profile-photo', endpoint='update_admin_user_profile_photo', view_func=update_admin_user_profile_photo, methods=['POST'])
    application.add_url_rule('/admin/users/delete/<int:user_id>', endpoint='delete_admin_user', view_func=delete_admin_user, methods=['POST'])
    application.add_url_rule('/admin/crop-categories/create', endpoint='create_crop_category', view_func=create_crop_category, methods=['POST'])
    application.add_url_rule('/admin/crop-categories/edit/<int:category_id>', endpoint='edit_crop_category', view_func=edit_crop_category, methods=['POST'])
    application.add_url_rule('/admin/crop-categories/delete/<int:category_id>', endpoint='delete_crop_category', view_func=delete_crop_category, methods=['POST'])
    application.add_url_rule('/admin/commodity-details/categories/<int:category_id>/delete', endpoint='delete_commodity_detail_category', view_func=delete_crop_category, methods=['POST'])
    application.add_url_rule('/admin/commodities/create', endpoint='create_crop', view_func=create_crop, methods=['POST'])
    application.add_url_rule('/admin/commodities/edit/<int:commodity_id>', endpoint='edit_crop', view_func=edit_crop, methods=['POST'])
    application.add_url_rule('/admin/commodities/<int:commodity_id>/pricing', endpoint='save_crop_pricing', view_func=save_crop_pricing, methods=['POST'])
    application.add_url_rule('/admin/catalog/pricing/batch', endpoint='save_crop_pricing_batch', view_func=save_crop_pricing_batch, methods=['POST'])
    application.add_url_rule('/admin/commodities/delete/<int:commodity_id>', endpoint='delete_crop', view_func=delete_crop, methods=['POST'])
    application.add_url_rule('/admin/crops/create', endpoint='create_crop_legacy', view_func=create_crop, methods=['POST'])
    application.add_url_rule('/admin/crops/edit/<int:commodity_id>', endpoint='edit_crop_legacy', view_func=edit_crop, methods=['POST'])
    application.add_url_rule('/admin/crops/<int:commodity_id>/pricing', endpoint='save_crop_pricing_legacy', view_func=save_crop_pricing, methods=['POST'])
    application.add_url_rule('/admin/crops/delete/<int:commodity_id>', endpoint='delete_crop_legacy', view_func=delete_crop, methods=['POST'])
    application.add_url_rule('/admin/knowledge-categories/create', endpoint='create_knowledge_category', view_func=create_knowledge_category, methods=['POST'])
    application.add_url_rule('/admin/knowledge-categories/edit/<int:category_id>', endpoint='edit_knowledge_category', view_func=edit_knowledge_category, methods=['POST'])
    application.add_url_rule('/admin/knowledge-categories/delete/<int:category_id>', endpoint='delete_knowledge_category', view_func=delete_knowledge_category, methods=['POST'])
    application.register_error_handler(404, page_not_found)
    application.register_error_handler(500, internal_error)
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = [
    'admin_knowledge', 'create_knowledge_post', 'edit_knowledge_post', 'delete_knowledge_post',
    'admin', 'admin_users', 'admin_catalog', 'admin_inventory', 'admin_marketplace', 'admin_marketplace_transactions',
    'admin_face_scan_monitor', 'admin_online_payments', 'toggle_online_payments',
    'admin_audit_logs',
    'admin_profile_reports', 'review_profile_report',
    'admin_listing_photo_alerts', 'review_listing_photo_alert',
    'create_admin_marketplace_listing', 'edit_admin_marketplace_listing', 'delete_admin_marketplace_listing',
    'update_admin_marketplace_thumbnail',
    'admin_review_geotag', 'admin_knowledge_categories',
    'create_admin_user', 'edit_admin_user', 'delete_admin_user',
    'update_admin_user_profile_photo',
    'create_crop_category', 'edit_crop_category', 'delete_crop_category',
    'create_crop', 'edit_crop', 'save_crop_pricing', 'save_crop_pricing_batch', 'import_crop_pricing',
    'download_crop_pricing_template', 'delete_crop',
    'admin_commodity_details', 'create_commodity_detail_category',
    'create_commodity_price_unit', 'delete_commodity_price_unit',
    'edit_commodity_detail_category', 'create_commodity_detail',
    'edit_commodity_detail', 'update_commodity_price_unit',
    'delete_commodity_detail',
    'create_knowledge_category', 'edit_knowledge_category', 'delete_knowledge_category',
    'page_not_found', 'internal_error'
]
