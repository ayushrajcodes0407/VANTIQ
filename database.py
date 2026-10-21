"""
VANTIQ: AI-Powered Business Intelligence Assistant — Persistent Database Module
File: database.py
Description:
    Provides production-grade SQLite local persistence for VANTIQ:
    - Versioned schema migrations
    - Datasets, worksheets, structured records, analysis runs, and report storage
    - SHA-256 deduplication
    - Safe JSON serialization (handling NaNs, Timestamps, Infinities)
    - Cascade foreign key enforcement
    - Atomic transactional operations
    - SQLite online backup & restore
"""

import os
import sqlite3
import json
import uuid
import datetime
import hashlib
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("VANTIQ-Database")

# Configurable database path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
DEFAULT_DB_PATH = os.path.join(DEFAULT_INSTANCE_DIR, "vantiq_business.db" if os.path.exists(os.path.join(DEFAULT_INSTANCE_DIR, "vantiq_business.db")) or not os.path.exists(os.path.join(DEFAULT_INSTANCE_DIR, "jarvis_business.db")) else "jarvis_business.db")

MAX_STORED_ROWS_PER_DATASET = int(os.environ.get("VANTIQ_MAX_STORED_ROWS", os.environ.get("JARVIS_MAX_STORED_ROWS", "50000")))
CURRENT_SCHEMA_VERSION = 2
ANALYSIS_ENGINE_VERSION = "v1.0.0"

def get_db_path() -> str:
    """Returns the absolute path to the configured SQLite database file."""
    return os.environ.get("VANTIQ_DB_PATH", os.environ.get("JARVIS_DB_PATH", DEFAULT_DB_PATH))

def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Creates and returns a SQLite connection configured with:
    - Foreign key constraints enabled
    - Row factory enabled for dictionary-style access
    - Timeout for concurrency resilience
    """
    path = db_path or get_db_path()
    parent_dir = os.path.dirname(path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    conn = sqlite3.connect(path, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.row_factory = sqlite3.Row
    return conn

# ==============================================================================
# SAFE JSON SERIALIZER
# ==============================================================================

def safe_json_default(obj):
    """Custom JSON serializer for objects not serializable by default json code."""
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    if hasattr(obj, 'tolist'):
        return obj.tolist()
    if hasattr(obj, 'item'):
        return obj.item()
    return str(obj)

def safe_json_dumps(data: Any) -> str:
    """Safely dumps data to JSON string, replacing NaN/Inf with None."""
    def clean(val):
        if val is None:
            return None
        if isinstance(val, float):
            import math
            if math.isnan(val) or math.isinf(val):
                return None
            return val
        if isinstance(val, dict):
            return {k: clean(v) for k, v in val.items()}
        if isinstance(val, (list, tuple)):
            return [clean(v) for v in val]
        return val

    cleaned_data = clean(data)
    return json.dumps(cleaned_data, default=safe_json_default, ensure_ascii=False)

def safe_json_loads(json_str: Optional[str], default_val=None) -> Any:
    """Safely parses JSON string with fallback."""
    if not json_str:
        return default_val
    try:
        return json.loads(json_str)
    except Exception as e:
        logger.warning(f"Error parsing JSON: {e}")
        return default_val

# ==============================================================================
# SCHEMA MIGRATIONS
# ==============================================================================

MIGRATION_V1_SQL = """
-- Versioned Migrations Table
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Datasets Table
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    file_hash_sha256 TEXT NOT NULL,
    dataset_type TEXT NOT NULL,
    source_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    sheet_count INTEGER,
    page_count INTEGER,
    row_count INTEGER,
    column_count INTEGER,
    extraction_summary_json TEXT,
    analysis_status TEXT NOT NULL DEFAULT 'none',
    last_analyzed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_datasets_hash ON datasets(file_hash_sha256);
CREATE INDEX IF NOT EXISTS idx_datasets_created ON datasets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_datasets_type ON datasets(file_type);

-- Dataset Sheets Table (for Excel Worksheets)
CREATE TABLE IF NOT EXISTS dataset_sheets (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    sheet_index INTEGER NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    column_count INTEGER NOT NULL DEFAULT 0,
    columns_json TEXT,
    preview_json TEXT,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sheets_dataset ON dataset_sheets(dataset_id);

-- Dataset Records Table (Structured Rows)
CREATE TABLE IF NOT EXISTS dataset_records (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    sheet_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE,
    FOREIGN KEY(sheet_id) REFERENCES dataset_sheets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_records_lookup ON dataset_records(dataset_id, sheet_id, row_index);

-- Analysis Runs Table
CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    analysis_version TEXT NOT NULL,
    analysis_status TEXT NOT NULL,
    metrics_json TEXT,
    insights_json TEXT,
    quality_report_json TEXT,
    warnings_json TEXT,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runs_dataset ON analysis_runs(dataset_id, created_at DESC);

-- Reports Table
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    analysis_run_id TEXT NOT NULL,
    report_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    report_format TEXT NOT NULL DEFAULT 'json',
    report_content_json TEXT NOT NULL,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE,
    FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reports_dataset ON reports(dataset_id, created_at DESC);
"""

MIGRATION_V2_SQL = """
-- Suppliers Table
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact_name TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);

-- Products Table
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    brand TEXT,
    unit TEXT DEFAULT 'piece',
    supplier_id INTEGER,
    purchase_price REAL DEFAULT 0.0 CHECK(purchase_price >= 0),
    selling_price REAL DEFAULT 0.0 CHECK(selling_price >= 0),
    currency TEXT DEFAULT 'INR',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_dataset_id TEXT,
    FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL,
    FOREIGN KEY(source_dataset_id) REFERENCES datasets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active);

-- Inventory Table (one balance per product)
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL UNIQUE,
    quantity_on_hand REAL NOT NULL DEFAULT 0.0 CHECK(quantity_on_hand >= 0),
    reorder_level REAL NOT NULL DEFAULT 0.0 CHECK(reorder_level >= 0),
    unit TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory(product_id);

-- Inventory Movements Table
CREATE TABLE IF NOT EXISTS inventory_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    movement_type TEXT NOT NULL,
    quantity_delta REAL NOT NULL,
    quantity_before REAL NOT NULL,
    quantity_after REAL NOT NULL,
    reason TEXT NOT NULL,
    reference TEXT,
    created_at TEXT NOT NULL,
    source_dataset_id TEXT,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY(source_dataset_id) REFERENCES datasets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_movements_product ON inventory_movements(product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_movements_type ON inventory_movements(movement_type);
"""

def init_db(db_path: Optional[str] = None) -> None:
    """
    Initializes the database schema if not already present.
    Safe to execute multiple times (idempotent).
    """
    conn = get_connection(db_path)
    try:
        with conn:
            # Check current version
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
            has_table = cursor.fetchone() is not None

            current_version = 0
            if has_table:
                cursor.execute("SELECT MAX(version) FROM schema_migrations")
                row = cursor.fetchone()
                if row and row[0] is not None:
                    current_version = row[0]

            if current_version < 1:
                logger.info("Applying database migration V1...")
                conn.executescript(MIGRATION_V1_SQL)
                now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (1, now_str)
                )
                logger.info("Database migration V1 applied successfully.")

            if current_version < 2:
                logger.info("Applying database migration V2 (Catalogue & Inventory)...")
                conn.executescript(MIGRATION_V2_SQL)
                now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (2, now_str)
                )
                logger.info("Database migration V2 applied successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    finally:
        conn.close()

# ==============================================================================
# HASHING & DUPLICATE CHECK
# ==============================================================================

def compute_sha256(file_bytes: bytes) -> str:
    """Computes SHA-256 hex digest of raw file bytes."""
    return hashlib.sha256(file_bytes).hexdigest()

def find_dataset_by_hash(file_hash: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Finds an existing dataset by its SHA-256 content hash."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM datasets 
            WHERE file_hash_sha256 = ? AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
            """,
            (file_hash,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        if close_after:
            conn.close()

# ==============================================================================
# DATASET PERSISTENCE: EXCEL
# ==============================================================================

def save_excel_dataset(
    file_bytes: bytes,
    original_filename: str,
    file_type: str,
    sha256_hash: str,
    sheets_data: List[Dict[str, Any]],
    bi_report: Optional[Dict[str, Any]] = None,
    source_name: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Persists an Excel dataset transactionally:
    1. Dataset record
    2. Worksheet records
    3. Structured rows (bounded by MAX_STORED_ROWS_PER_DATASET)
    4. Initial Analysis Run
    5. Generated Report
    """
    conn = get_connection(db_path)
    dataset_id = f"ds_{uuid.uuid4().hex[:12]}"
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    total_rows = sum(s.get("row_count", 0) for s in sheets_data)
    max_cols = max((len(s.get("columns", [])) for s in sheets_data), default=0)

    is_preview_only = total_rows > MAX_STORED_ROWS_PER_DATASET
    detected_type = "Excel Dataset"
    if bi_report and isinstance(bi_report.get("classification"), dict):
        detected_type = bi_report["classification"].get("detected_type", detected_type)

    summary_meta = {
        "sheet_count": len(sheets_data),
        "total_rows": total_rows,
        "total_columns": max_cols,
        "is_preview_only": is_preview_only,
        "storage_mode": "preview_only_exceeded_limit" if is_preview_only else "full_structured"
    }

    try:
        with conn:
            cur = conn.cursor()

            # 1. Insert dataset
            cur.execute(
                """
                INSERT INTO datasets (
                    id, original_filename, file_type, file_size_bytes, file_hash_sha256,
                    dataset_type, source_name, created_at, updated_at, status,
                    sheet_count, page_count, row_count, column_count,
                    extraction_summary_json, analysis_status, last_analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    original_filename,
                    file_type,
                    len(file_bytes),
                    sha256_hash,
                    detected_type,
                    source_name,
                    now_str,
                    now_str,
                    "active",
                    len(sheets_data),
                    None,
                    total_rows,
                    max_cols,
                    safe_json_dumps(summary_meta),
                    "completed" if bi_report else "none",
                    now_str if bi_report else None
                )
            )

            # 2. Insert worksheets & rows
            for sheet_idx, sdata in enumerate(sheets_data):
                sheet_id = f"sheet_{uuid.uuid4().hex[:12]}"
                cols = sdata.get("columns", [])
                preview = sdata.get("preview_rows", [])
                all_rows = sdata.get("all_rows", preview) # If all_rows provided, persist them

                cur.execute(
                    """
                    INSERT INTO dataset_sheets (
                        id, dataset_id, sheet_name, sheet_index,
                        row_count, column_count, columns_json, preview_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sheet_id,
                        dataset_id,
                        sdata.get("sheet_name", f"Sheet{sheet_idx+1}"),
                        sheet_idx,
                        sdata.get("row_count", len(all_rows)),
                        len(cols),
                        safe_json_dumps(cols),
                        safe_json_dumps(preview[:10])
                    )
                )

                # Persist records (up to limit or preview only)
                rows_to_store = preview if is_preview_only else all_rows
                records_batch = []
                for r_idx, r_dict in enumerate(rows_to_store):
                    rec_id = f"rec_{uuid.uuid4().hex[:12]}"
                    records_batch.append((
                        rec_id,
                        dataset_id,
                        sheet_id,
                        r_idx,
                        safe_json_dumps(r_dict)
                    ))

                if records_batch:
                    cur.executemany(
                        """
                        INSERT INTO dataset_records (
                            id, dataset_id, sheet_id, row_index, record_json
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        records_batch
                    )

            # 3. Insert initial Analysis Run & Report if bi_report is available
            run_id = None
            if bi_report:
                run_id = f"run_{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO analysis_runs (
                        id, dataset_id, created_at, analysis_version,
                        analysis_status, metrics_json, insights_json,
                        quality_report_json, warnings_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        dataset_id,
                        now_str,
                        ANALYSIS_ENGINE_VERSION,
                        "success",
                        safe_json_dumps({
                            "pricing": bi_report.get("pricing"),
                            "inventory": bi_report.get("inventory"),
                            "sales": bi_report.get("sales"),
                            "statistical_analysis": bi_report.get("statistical_analysis"),
                            "dataset_profiling": bi_report.get("dataset_profiling")
                        }),
                        safe_json_dumps(bi_report.get("insights", [])),
                        safe_json_dumps(bi_report.get("data_quality", {})),
                        safe_json_dumps(bi_report.get("data_quality", {}).get("issues", []))
                    )
                )

                # 4. Insert Report
                rep_id = f"rep_{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO reports (
                        id, dataset_id, analysis_run_id, report_type,
                        created_at, report_format, report_content_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rep_id,
                        dataset_id,
                        run_id,
                        "full_bi",
                        now_str,
                        "json",
                        safe_json_dumps(bi_report)
                    )
                )

        logger.info(f"Excel dataset {dataset_id} successfully persisted to SQLite.")
        return {
            "dataset_id": dataset_id,
            "analysis_run_id": run_id,
            "created_at": now_str,
            "status": "persisted"
        }
    finally:
        conn.close()

# ==============================================================================
# DATASET PERSISTENCE: PDF
# ==============================================================================

def save_pdf_dataset(
    file_bytes: bytes,
    original_filename: str,
    sha256_hash: str,
    page_count: int,
    char_count: int,
    has_text: bool,
    text_preview: str,
    bi_report: Optional[Dict[str, Any]] = None,
    source_name: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Persists a PDF document transactionally:
    1. Dataset record
    2. Initial Analysis Run
    3. Generated Report
    """
    conn = get_connection(db_path)
    dataset_id = f"ds_{uuid.uuid4().hex[:12]}"
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    detected_type = "PDF Document"
    if bi_report and isinstance(bi_report.get("classification"), dict):
        detected_type = bi_report["classification"].get("detected_type", detected_type)

    summary_meta = {
        "page_count": page_count,
        "char_count": char_count,
        "has_text": has_text,
        "text_preview": text_preview[:2000] if text_preview else ""
    }

    try:
        with conn:
            cur = conn.cursor()

            # 1. Insert dataset
            cur.execute(
                """
                INSERT INTO datasets (
                    id, original_filename, file_type, file_size_bytes, file_hash_sha256,
                    dataset_type, source_name, created_at, updated_at, status,
                    sheet_count, page_count, row_count, column_count,
                    extraction_summary_json, analysis_status, last_analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    original_filename,
                    "pdf",
                    len(file_bytes),
                    sha256_hash,
                    detected_type,
                    source_name,
                    now_str,
                    now_str,
                    "active",
                    0,
                    page_count,
                    0,
                    0,
                    safe_json_dumps(summary_meta),
                    "completed" if bi_report else "none",
                    now_str if bi_report else None
                )
            )

            # 2. Insert initial Analysis Run & Report if bi_report
            run_id = None
            if bi_report:
                run_id = f"run_{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO analysis_runs (
                        id, dataset_id, created_at, analysis_version,
                        analysis_status, metrics_json, insights_json,
                        quality_report_json, warnings_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        dataset_id,
                        now_str,
                        ANALYSIS_ENGINE_VERSION,
                        "success",
                        safe_json_dumps({
                            "pdf_document_intelligence": bi_report.get("pdf_document_intelligence"),
                            "resume_intelligence": bi_report.get("resume_intelligence")
                        }),
                        safe_json_dumps(bi_report.get("insights", [])),
                        safe_json_dumps(bi_report.get("data_quality", {})),
                        safe_json_dumps(bi_report.get("data_quality", {}).get("issues", []))
                    )
                )

                # Report
                rep_id = f"rep_{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO reports (
                        id, dataset_id, analysis_run_id, report_type,
                        created_at, report_format, report_content_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rep_id,
                        dataset_id,
                        run_id,
                        "pdf_intelligence",
                        now_str,
                        "json",
                        safe_json_dumps(bi_report)
                    )
                )

        logger.info(f"PDF dataset {dataset_id} successfully persisted to SQLite.")
        return {
            "dataset_id": dataset_id,
            "analysis_run_id": run_id,
            "created_at": now_str,
            "status": "persisted"
        }
    finally:
        conn.close()

# ==============================================================================
# RETRIEVAL & QUERY FUNCTIONS
# ==============================================================================

def list_datasets(
    page: int = 1,
    page_size: int = 10,
    search: str = "",
    file_type: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Returns a paginated list of saved datasets with total count."""
    page = max(1, page)
    page_size = min(max(1, page_size), 100) # Safe bound 1-100
    offset = (page - 1) * page_size

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        query = "SELECT * FROM datasets WHERE status = 'active'"
        params: List[Any] = []

        if search:
            query += " AND (original_filename LIKE ? OR dataset_type LIKE ?)"
            pattern = f"%{search.strip()}%"
            params.extend([pattern, pattern])

        if file_type:
            query += " AND file_type = ?"
            params.append(file_type.lower().strip())

        # Count total
        count_query = f"SELECT COUNT(*) FROM ({query})"
        cur.execute(count_query, params)
        total_count = cur.fetchone()[0]

        # Fetch page
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([page_size, offset])
        cur.execute(query, params)
        rows = cur.fetchall()

        datasets = []
        for r in rows:
            item = dict(r)
            item["extraction_summary"] = safe_json_loads(item.get("extraction_summary_json"))
            item.pop("extraction_summary_json", None)
            datasets.append(item)

        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

        return {
            "datasets": datasets,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_count,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        }
    finally:
        conn.close()

def get_dataset_by_id(dataset_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns metadata, worksheets, and summary for a specific dataset."""
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM datasets WHERE id = ? AND status = 'active'", (dataset_id,))
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        data["extraction_summary"] = safe_json_loads(data.get("extraction_summary_json"))
        data.pop("extraction_summary_json", None)

        # Fetch sheets
        cur.execute(
            """
            SELECT id, sheet_name, sheet_index, row_count, column_count, columns_json, preview_json
            FROM dataset_sheets WHERE dataset_id = ? ORDER BY sheet_index ASC
            """,
            (dataset_id,)
        )
        sheet_rows = cur.fetchall()
        sheets = []
        for s in sheet_rows:
            s_dict = dict(s)
            s_dict["columns"] = safe_json_loads(s_dict.get("columns_json"), [])
            s_dict["preview_rows"] = safe_json_loads(s_dict.get("preview_json"), [])
            s_dict.pop("columns_json", None)
            s_dict.pop("preview_json", None)
            sheets.append(s_dict)

        data["sheets"] = sheets
        return data
    finally:
        conn.close()

def get_dataset_records(
    dataset_id: str,
    sheet_name: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Returns paginated structured records for an Excel dataset."""
    page = max(1, page)
    page_size = min(max(1, page_size), 200) # Safe bound 1-200
    offset = (page - 1) * page_size

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        # Find sheet_id
        if sheet_name:
            cur.execute(
                "SELECT id, columns_json, row_count FROM dataset_sheets WHERE dataset_id = ? AND sheet_name = ?",
                (dataset_id, sheet_name)
            )
        else:
            cur.execute(
                "SELECT id, columns_json, row_count FROM dataset_sheets WHERE dataset_id = ? ORDER BY sheet_index ASC LIMIT 1",
                (dataset_id,)
            )

        sheet_row = cur.fetchone()
        if not sheet_row:
            return {
                "records": [],
                "columns": [],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_items": 0,
                    "total_pages": 1,
                    "has_next": False,
                    "has_prev": False
                }
            }

        sheet_id = sheet_row["id"]
        columns = safe_json_loads(sheet_row["columns_json"], [])
        total_items = sheet_row["row_count"]

        cur.execute(
            """
            SELECT row_index, record_json FROM dataset_records
            WHERE dataset_id = ? AND sheet_id = ?
            ORDER BY row_index ASC LIMIT ? OFFSET ?
            """,
            (dataset_id, sheet_id, page_size, offset)
        )
        rows = cur.fetchall()
        records = [safe_json_loads(r["record_json"], {}) for r in rows]

        total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1

        return {
            "sheet_id": sheet_id,
            "columns": columns,
            "records": records,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        }
    finally:
        conn.close()

def load_dataset_dataframe(
    dataset_id: str,
    sheet_name: Optional[str] = None,
    db_path: Optional[str] = None
) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """
    Loads all records of an Excel dataset (or specific sheet) from SQLite into a pandas DataFrame.
    Returns (df, dataset_dict).
    If dataset is a PDF or has no records, returns (None, dataset_dict).
    """
    import pandas as pd
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        ds_row = cur.fetchone()
        if not ds_row:
            return None, None
        ds = dict(ds_row)
        ds["extraction_summary"] = safe_json_loads(ds.get("extraction_summary_json"), {})

        if ds.get("file_type") == 'pdf':
            return None, ds

        # Find sheet
        if sheet_name:
            cur.execute(
                "SELECT id, sheet_name, columns_json, row_count FROM dataset_sheets WHERE dataset_id = ? AND sheet_name = ?",
                (dataset_id, sheet_name)
            )
        else:
            cur.execute(
                "SELECT id, sheet_name, columns_json, row_count FROM dataset_sheets WHERE dataset_id = ? ORDER BY sheet_index ASC LIMIT 1",
                (dataset_id,)
            )
        sheet_row = cur.fetchone()
        if not sheet_row:
            return pd.DataFrame(), ds

        sheet_id = sheet_row["id"]
        columns = safe_json_loads(sheet_row["columns_json"], [])

        cur.execute(
            "SELECT record_json FROM dataset_records WHERE dataset_id = ? AND sheet_id = ? ORDER BY row_index ASC",
            (dataset_id, sheet_id)
        )
        records = [safe_json_loads(r["record_json"], {}) for r in cur.fetchall()]
        if not records:
            df = pd.DataFrame(columns=columns)
        else:
            df = pd.DataFrame(records)
            existing_cols = [c for c in columns if c in df.columns]
            other_cols = [c for c in df.columns if c not in existing_cols]
            df = df[existing_cols + other_cols]

        ds["active_sheet"] = sheet_row["sheet_name"]
        ds["columns"] = columns
        ds["total_rows"] = len(df)
        return df, ds
    finally:
        conn.close()

def get_dataset_reports(dataset_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns analysis runs and saved reports for a dataset."""
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 
                r.id as report_id,
                r.report_type,
                r.created_at,
                r.report_format,
                ar.id as analysis_run_id,
                ar.analysis_version,
                ar.analysis_status
            FROM reports r
            JOIN analysis_runs ar ON r.analysis_run_id = ar.id
            WHERE r.dataset_id = ?
            ORDER BY r.created_at DESC
            """,
            (dataset_id,)
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_report_by_id(report_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns the full report content by report_id."""
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT r.*, d.original_filename, d.file_type, d.dataset_type, ar.analysis_version
            FROM reports r
            JOIN datasets d ON r.dataset_id = d.id
            JOIN analysis_runs ar ON r.analysis_run_id = ar.id
            WHERE r.id = ?
            """,
            (report_id,)
        )
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        data["report_content"] = safe_json_loads(data.get("report_content_json"))
        data.pop("report_content_json", None)
        return data
    finally:
        conn.close()

def get_latest_report_for_dataset(dataset_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetches the latest report content for a dataset."""
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT r.*, d.original_filename, d.file_type, d.dataset_type, ar.analysis_version
            FROM reports r
            JOIN datasets d ON r.dataset_id = d.id
            JOIN analysis_runs ar ON r.analysis_run_id = ar.id
            WHERE r.dataset_id = ?
            ORDER BY r.created_at DESC LIMIT 1
            """,
            (dataset_id,)
        )
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        data["report_content"] = safe_json_loads(data.get("report_content_json"))
        data.pop("report_content_json", None)
        return data
    finally:
        conn.close()

# ==============================================================================
# RE-ANALYSIS & RUN PERSISTENCE
# ==============================================================================

def create_analysis_run(
    dataset_id: str,
    bi_report: Dict[str, Any],
    version: str = ANALYSIS_ENGINE_VERSION,
    report_type: str = "full_bi",
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Persists a new analysis run and generated report for an existing dataset.
    Preserves all previous analysis runs.
    """
    conn = get_connection(db_path)
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    rep_id = f"rep_{uuid.uuid4().hex[:12]}"
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        with conn:
            cur = conn.cursor()
            # 1. Insert analysis run
            cur.execute(
                """
                INSERT INTO analysis_runs (
                    id, dataset_id, created_at, analysis_version,
                    analysis_status, metrics_json, insights_json,
                    quality_report_json, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    dataset_id,
                    now_str,
                    version,
                    "success",
                    safe_json_dumps({
                        "pricing": bi_report.get("pricing"),
                        "inventory": bi_report.get("inventory"),
                        "sales": bi_report.get("sales"),
                        "statistical_analysis": bi_report.get("statistical_analysis"),
                        "dataset_profiling": bi_report.get("dataset_profiling"),
                        "pdf_document_intelligence": bi_report.get("pdf_document_intelligence"),
                        "resume_intelligence": bi_report.get("resume_intelligence")
                    }),
                    safe_json_dumps(bi_report.get("insights", [])),
                    safe_json_dumps(bi_report.get("data_quality", {})),
                    safe_json_dumps(bi_report.get("data_quality", {}).get("issues", []))
                )
            )

            # 2. Insert report
            cur.execute(
                """
                INSERT INTO reports (
                    id, dataset_id, analysis_run_id, report_type,
                    created_at, report_format, report_content_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rep_id,
                    dataset_id,
                    run_id,
                    report_type,
                    now_str,
                    "json",
                    safe_json_dumps(bi_report)
                )
            )

            # 3. Update dataset's last_analyzed_at and analysis_status
            cur.execute(
                """
                UPDATE datasets
                SET last_analyzed_at = ?, analysis_status = 'completed', updated_at = ?
                WHERE id = ?
                """,
                (now_str, now_str, dataset_id)
            )

        return {
            "analysis_run_id": run_id,
            "report_id": rep_id,
            "created_at": now_str,
            "version": version
        }
    finally:
        conn.close()

# ==============================================================================
# SAFE DATASET DELETION
# ==============================================================================

def delete_dataset(dataset_id: str, db_path: Optional[str] = None) -> bool:
    """
    Safely deletes a dataset and its cascading child records (sheets, rows, runs, reports)
    within a transaction.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM datasets WHERE id = ?", (dataset_id,))
            if not cur.fetchone():
                return False

            # With foreign_keys = ON and ON DELETE CASCADE, child records are removed cleanly.
            cur.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
            return True
    finally:
        conn.close()

# ==============================================================================
# BACKUP & RESTORE UTILITIES
# ==============================================================================

def backup_database(target_path: Optional[str] = None, source_db_path: Optional[str] = None) -> str:
    """
    Creates a consistent SQLite online backup using connection.backup().
    Returns the absolute path to the backup file.
    """
    src_path = source_db_path or get_db_path()
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Source database file does not exist: {src_path}")

    if not target_path:
        backups_dir = os.path.join(BASE_DIR, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = os.path.join(backups_dir, f"jarvis_backup_{timestamp}.db")
    else:
        target_dir = os.path.dirname(target_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)

    src_conn = sqlite3.connect(src_path)
    dst_conn = sqlite3.connect(target_path)
    try:
        src_conn.backup(dst_conn)
        logger.info(f"Database backup created successfully at: {target_path}")
        return target_path
    finally:
        dst_conn.close()
        src_conn.close()

def restore_database(backup_path: str, target_db_path: Optional[str] = None) -> str:
    """
    Restores a database from a backup file into target_db_path using connection.backup().
    Fails safely if backup_path is invalid.
    """
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    dst_path = target_db_path or get_db_path()
    dst_dir = os.path.dirname(dst_path)
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)

    src_conn = sqlite3.connect(backup_path)
    dst_conn = sqlite3.connect(dst_path)
    try:
        src_conn.backup(dst_conn)
        logger.info(f"Database successfully restored from {backup_path} to {dst_path}")
        return dst_path
    finally:
        dst_conn.close()
        src_conn.close()


# ==============================================================================
# J.A.R.V.I.S. STEP 4 — CATALOGUE & INVENTORY MANAGEMENT ENGINE
# ==============================================================================

def calculate_margins(purchase_price: Optional[float], selling_price: Optional[float]) -> Dict[str, Optional[float]]:
    """
    Calculates unit gross profit, gross margin percentage, and markup percentage.
    - Unit gross profit: Selling Price - Purchase Cost
    - Gross margin %: ((Selling Price - Purchase Cost) / Selling Price) * 100
    - Markup %: ((Selling Price - Purchase Cost) / Purchase Cost) * 100
    Handles zero-division and missing values safely.
    """
    if purchase_price is None or selling_price is None:
        return {"gross_profit": None, "gross_margin_pct": None, "markup_pct": None}
    try:
        p = float(purchase_price)
        s = float(selling_price)
    except (ValueError, TypeError):
        return {"gross_profit": None, "gross_margin_pct": None, "markup_pct": None}

    profit = round(s - p, 2)
    margin = round(((s - p) / s) * 100.0, 2) if s > 0 else 0.0
    markup = round(((s - p) / p) * 100.0, 2) if p > 0 else 0.0
    return {
        "gross_profit": profit,
        "gross_margin_pct": margin,
        "markup_pct": markup
    }


def create_or_get_supplier(name: str, contact_name: Optional[str] = None, phone: Optional[str] = None,
                           email: Optional[str] = None, address: Optional[str] = None,
                           notes: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Finds an existing supplier by name (case-insensitive) or creates a new one."""
    if not name or not str(name).strip():
        raise ValueError("Supplier name cannot be empty")
    cleaned_name = str(name).strip()
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM suppliers WHERE LOWER(TRIM(name)) = LOWER(?)", (cleaned_name,))
        row = cur.fetchone()
        if row:
            return dict(row)

        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO suppliers (name, contact_name, phone, email, address, notes, created_at, updated_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (cleaned_name, contact_name, phone, email, address, notes, now_str, now_str)
        )
        sup_id = cur.lastrowid
        if close_after:
            conn.commit()
        cur.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,))
        return dict(cur.fetchone())
    finally:
        if close_after:
            conn.close()


def list_suppliers(is_active: Optional[bool] = None, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Returns a list of suppliers ordered by name."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        if is_active is None:
            cur.execute("SELECT * FROM suppliers ORDER BY name ASC")
        else:
            cur.execute("SELECT * FROM suppliers WHERE is_active = ? ORDER BY name ASC", (1 if is_active else 0,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        if close_after:
            conn.close()


def create_product(product_data: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Creates a new product with an atomic initial inventory balance and opening-balance movement.
    """
    name = product_data.get("name")
    if not name or not str(name).strip():
        raise ValueError("Product name is required and cannot be empty")
    name = str(name).strip()

    sku = str(product_data.get("sku") or "").strip() or None
    description = str(product_data.get("description") or "").strip() or None
    category = str(product_data.get("category") or "").strip() or None
    brand = str(product_data.get("brand") or "").strip() or None
    unit = str(product_data.get("unit") or "piece").strip().lower() or "piece"
    currency = str(product_data.get("currency") or "INR").strip().upper() or "INR"
    supplier_id = product_data.get("supplier_id")
    source_dataset_id = product_data.get("source_dataset_id")

    try:
        purchase_price = round(float(product_data.get("purchase_price") or 0.0), 2)
        if purchase_price < 0:
            raise ValueError("Purchase price cannot be negative")
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid purchase price: {e}")

    try:
        selling_price = round(float(product_data.get("selling_price") or 0.0), 2)
        if selling_price < 0:
            raise ValueError("Selling price cannot be negative")
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid selling price: {e}")

    try:
        opening_stock = round(float(product_data.get("opening_stock") or 0.0), 4)
        if opening_stock < 0:
            raise ValueError("Opening stock quantity cannot be negative")
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid opening stock quantity: {e}")

    try:
        reorder_level = round(float(product_data.get("reorder_level") or 0.0), 4)
        if reorder_level < 0:
            raise ValueError("Reorder level cannot be negative")
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid reorder level: {e}")

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        with conn:
            cur = conn.cursor()

            # Enforce SKU uniqueness when SKU is provided
            if sku:
                cur.execute("SELECT id, name FROM products WHERE LOWER(TRIM(sku)) = LOWER(TRIM(?))", (sku,))
                existing_sku = cur.fetchone()
                if existing_sku:
                    raise ValueError(f"SKU '{sku}' is already assigned to product '{existing_sku['name']}' (ID: {existing_sku['id']})")

            if supplier_id is not None and supplier_id != "":
                cur.execute("SELECT id FROM suppliers WHERE id = ?", (int(supplier_id),))
                if not cur.fetchone():
                    supplier_id = None
            else:
                supplier_id = None

            cur.execute(
                """
                INSERT INTO products (
                    sku, name, description, category, brand, unit, supplier_id,
                    purchase_price, selling_price, currency, is_active,
                    created_at, updated_at, source_dataset_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (sku, name, description, category, brand, unit, supplier_id,
                 purchase_price, selling_price, currency, now_str, now_str, source_dataset_id)
            )
            prod_id = cur.lastrowid

            cur.execute(
                """
                INSERT INTO inventory (product_id, quantity_on_hand, reorder_level, unit, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (prod_id, opening_stock, reorder_level, unit, now_str)
            )

            if opening_stock > 0:
                cur.execute(
                    """
                    INSERT INTO inventory_movements (
                        product_id, movement_type, quantity_delta, quantity_before, quantity_after,
                        reason, reference, created_at, source_dataset_id
                    ) VALUES (?, 'opening_balance', ?, 0.0, ?, 'Initial opening balance', 'INIT', ?, ?)
                    """,
                    (prod_id, opening_stock, opening_stock, now_str, source_dataset_id)
                )

        return get_product_by_id(prod_id, conn=conn)
    finally:
        if close_after:
            conn.close()


def update_product(product_id: int, updates: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Updates permitted product fields. Rejects direct modifications to stock quantities.
    """
    for forbidden in ("quantity_on_hand", "stock", "opening_stock", "quantity"):
        if forbidden in updates:
            raise ValueError("Direct modification of stock quantity is not permitted via product update. Use the inventory movement service.")

    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        existing = cur.fetchone()
        if not existing:
            raise ValueError(f"Product with ID {product_id} not found")

        prod_fields = {}
        inv_fields = {}
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if "name" in updates:
            val = str(updates["name"] or "").strip()
            if not val:
                raise ValueError("Product name cannot be empty")
            prod_fields["name"] = val

        if "sku" in updates:
            new_sku = str(updates["sku"] or "").strip() or None
            if new_sku:
                cur.execute("SELECT id, name FROM products WHERE LOWER(TRIM(sku)) = LOWER(TRIM(?)) AND id != ?", (new_sku, product_id))
                existing_sku = cur.fetchone()
                if existing_sku:
                    raise ValueError(f"SKU '{new_sku}' is already assigned to product '{existing_sku['name']}' (ID: {existing_sku['id']})")
            prod_fields["sku"] = new_sku

        if "description" in updates:
            prod_fields["description"] = str(updates["description"] or "").strip() or None

        if "category" in updates:
            prod_fields["category"] = str(updates["category"] or "").strip() or None

        if "brand" in updates:
            prod_fields["brand"] = str(updates["brand"] or "").strip() or None

        if "unit" in updates:
            val = str(updates["unit"] or "piece").strip().lower() or "piece"
            prod_fields["unit"] = val
            inv_fields["unit"] = val

        if "currency" in updates:
            prod_fields["currency"] = str(updates["currency"] or "INR").strip().upper() or "INR"

        if "supplier_id" in updates:
            s_id = updates["supplier_id"]
            if s_id is not None and s_id != "":
                cur.execute("SELECT id FROM suppliers WHERE id = ?", (int(s_id),))
                if not cur.fetchone():
                    raise ValueError(f"Supplier ID {s_id} does not exist")
                prod_fields["supplier_id"] = int(s_id)
            else:
                prod_fields["supplier_id"] = None

        if "purchase_price" in updates:
            try:
                p = round(float(updates["purchase_price"]), 2)
                if p < 0:
                    raise ValueError("Purchase price cannot be negative")
                prod_fields["purchase_price"] = p
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid purchase price: {e}")

        if "selling_price" in updates:
            try:
                s = round(float(updates["selling_price"]), 2)
                if s < 0:
                    raise ValueError("Selling price cannot be negative")
                prod_fields["selling_price"] = s
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid selling price: {e}")

        if "is_active" in updates:
            prod_fields["is_active"] = 1 if updates["is_active"] else 0

        if "reorder_level" in updates:
            try:
                r = round(float(updates["reorder_level"]), 4)
                if r < 0:
                    raise ValueError("Reorder level cannot be negative")
                inv_fields["reorder_level"] = r
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid reorder level: {e}")

        with conn:
            if prod_fields:
                prod_fields["updated_at"] = now_str
                set_clauses = [f"{col} = ?" for col in prod_fields.keys()]
                values = list(prod_fields.values()) + [product_id]
                cur.execute(f"UPDATE products SET {', '.join(set_clauses)} WHERE id = ?", values)

            if inv_fields:
                inv_fields["updated_at"] = now_str
                inv_clauses = [f"{col} = ?" for col in inv_fields.keys()]
                inv_values = list(inv_fields.values()) + [product_id]
                cur.execute(f"UPDATE inventory SET {', '.join(inv_clauses)} WHERE product_id = ?", inv_values)

        return get_product_by_id(product_id, conn=conn)
    finally:
        if close_after:
            conn.close()


def deactivate_product(product_id: int, conn: Optional[sqlite3.Connection] = None) -> bool:
    """Marks a product as inactive without hard deleting it."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with conn:
            cur = conn.cursor()
            cur.execute("UPDATE products SET is_active = 0, updated_at = ? WHERE id = ?", (now_str, product_id))
            return cur.rowcount > 0
    finally:
        if close_after:
            conn.close()


def get_product_by_id(product_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Retrieves full product details including inventory balance, margins, and recent movements."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT p.*,
                   s.name as supplier_name, s.contact_name as supplier_contact, s.email as supplier_email,
                   s.phone as supplier_phone,
                   i.quantity_on_hand, i.reorder_level, i.unit as inventory_unit, i.updated_at as inventory_updated_at
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.id = ?
            """,
            (product_id,)
        )
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        margins = calculate_margins(data.get("purchase_price"), data.get("selling_price"))
        data.update(margins)

        qty = float(data.get("quantity_on_hand") or 0.0)
        reorder = float(data.get("reorder_level") or 0.0)
        cost = float(data.get("purchase_price") or 0.0)
        data["is_low_stock"] = (qty <= reorder and qty > 0)
        data["is_out_of_stock"] = (qty <= 0)
        data["provisional_stock_value"] = round(qty * cost, 2)
        data["stock_valuation_label"] = "Provisional (Stored Purchase Price)"

        cur.execute(
            """
            SELECT * FROM inventory_movements
            WHERE product_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 10
            """,
            (product_id,)
        )
        data["recent_movements"] = [dict(m) for m in cur.fetchall()]

        return data
    finally:
        if close_after:
            conn.close()


def list_products(search: Optional[str] = None, category: Optional[str] = None,
                  is_active: Optional[bool] = None, low_stock: Optional[bool] = None,
                  out_of_stock: Optional[bool] = None, sort_by: str = "name",
                  sort_order: str = "asc", page: int = 1, page_size: int = 20,
                  conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Lists products with comprehensive search, filtering, sorting, and pagination."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        where_clauses = []
        params = []

        if is_active is not None:
            where_clauses.append("p.is_active = ?")
            params.append(1 if is_active else 0)

        if category and str(category).strip():
            where_clauses.append("LOWER(p.category) = LOWER(?)")
            params.append(str(category).strip())

        if search and str(search).strip():
            s = f"%{str(search).strip()}%"
            where_clauses.append("(p.name LIKE ? OR p.sku LIKE ? OR p.category LIKE ? OR p.brand LIKE ?)")
            params.extend([s, s, s, s])

        if low_stock:
            where_clauses.append("i.quantity_on_hand <= i.reorder_level AND i.quantity_on_hand > 0")

        if out_of_stock:
            where_clauses.append("i.quantity_on_hand <= 0")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        cur.execute(
            f"""
            SELECT COUNT(*) FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            {where_sql}
            """,
            params
        )
        total_count = cur.fetchone()[0]

        allowed_sorts = {
            "name": "p.name",
            "sku": "p.sku",
            "price": "p.selling_price",
            "selling_price": "p.selling_price",
            "purchase_price": "p.purchase_price",
            "stock": "i.quantity_on_hand",
            "quantity_on_hand": "i.quantity_on_hand",
            "created_at": "p.created_at",
            "updated_at": "p.updated_at"
        }
        order_col = allowed_sorts.get(str(sort_by).lower(), "p.name")
        direction = "DESC" if str(sort_order).lower() == "desc" else "ASC"

        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        offset = (page - 1) * page_size

        cur.execute(
            f"""
            SELECT p.*,
                   s.name as supplier_name,
                   i.quantity_on_hand, i.reorder_level, i.unit as inventory_unit, i.updated_at as inventory_updated_at
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            {where_sql}
            ORDER BY {order_col} {direction}
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset]
        )
        rows = cur.fetchall()

        items = []
        for r in rows:
            d = dict(r)
            margins = calculate_margins(d.get("purchase_price"), d.get("selling_price"))
            d.update(margins)
            qty = float(d.get("quantity_on_hand") or 0.0)
            reorder = float(d.get("reorder_level") or 0.0)
            cost = float(d.get("purchase_price") or 0.0)
            d["is_low_stock"] = (qty <= reorder and qty > 0)
            d["is_out_of_stock"] = (qty <= 0)
            d["provisional_stock_value"] = round(qty * cost, 2)
            d["stock_valuation_label"] = "Provisional (Stored Purchase Price)"
            items.append(d)

        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

        return {
            "items": items,
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }
    finally:
        if close_after:
            conn.close()


def record_inventory_movement(product_id: int, movement_type: str, quantity_delta: float,
                              reason: str, reference: Optional[str] = None,
                              source_dataset_id: Optional[str] = None,
                              allow_negative: bool = False,
                              conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Atomically updates inventory balance and writes an immutable movement log entry.
    Rejects stock adjustments that lead to negative balances unless allow_negative=True.
    """
    valid_types = {"opening_balance", "receipt", "sale", "adjustment", "return"}
    m_type = str(movement_type or "").strip().lower()
    if m_type not in valid_types:
        raise ValueError(f"Invalid movement type '{movement_type}'. Permitted: {', '.join(sorted(valid_types))}")

    if not reason or not str(reason).strip():
        raise ValueError("Reason is mandatory for inventory stock movements")
    reason_clean = str(reason).strip()

    try:
        delta = round(float(quantity_delta), 4)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid quantity delta: {quantity_delta}")

    if delta == 0:
        raise ValueError("Quantity change must be non-zero")

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT quantity_on_hand, unit, reorder_level FROM inventory WHERE product_id = ?", (product_id,))
            inv_row = cur.fetchone()
            if not inv_row:
                raise ValueError(f"No inventory record found for product ID {product_id}")

            current_qty = round(float(inv_row["quantity_on_hand"]), 4)
            new_qty = round(current_qty + delta, 4)

            if new_qty < 0 and not allow_negative:
                raise ValueError(
                    f"Stock adjustment rejected: business rule prohibits negative balance. "
                    f"Current stock: {current_qty}, delta: {delta}, resulting balance: {new_qty}."
                )

            cur.execute(
                "UPDATE inventory SET quantity_on_hand = ?, updated_at = ? WHERE product_id = ?",
                (new_qty, now_str, product_id)
            )

            cur.execute(
                """
                INSERT INTO inventory_movements (
                    product_id, movement_type, quantity_delta, quantity_before, quantity_after,
                    reason, reference, created_at, source_dataset_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (product_id, m_type, delta, current_qty, new_qty, reason_clean, reference, now_str, source_dataset_id)
            )
            movement_id = cur.lastrowid

            cur.execute("SELECT * FROM inventory_movements WHERE id = ?", (movement_id,))
            movement_record = dict(cur.fetchone())

        return {
            "movement": movement_record,
            "product_id": product_id,
            "quantity_before": current_qty,
            "quantity_after": new_qty,
            "quantity_delta": delta
        }
    finally:
        if close_after:
            conn.close()


def get_inventory_movements(product_id: Optional[int] = None, limit: int = 50,
                            page: int = 1, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Retrieves paginated movement history with product information."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        where_clauses = []
        params = []
        if product_id is not None:
            where_clauses.append("m.product_id = ?")
            params.append(product_id)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        cur.execute(f"SELECT COUNT(*) FROM inventory_movements m {where_sql}", params)
        total_count = cur.fetchone()[0]

        page = max(1, int(page))
        limit = max(1, min(200, int(limit)))
        offset = (page - 1) * limit

        cur.execute(
            f"""
            SELECT m.*, p.name as product_name, p.sku as product_sku, p.unit as product_unit
            FROM inventory_movements m
            JOIN products p ON m.product_id = p.id
            {where_sql}
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset]
        )
        items = [dict(r) for r in cur.fetchall()]
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1

        return {
            "items": items,
            "total_count": total_count,
            "page": page,
            "page_size": limit,
            "total_pages": total_pages
        }
    finally:
        if close_after:
            conn.close()


def get_inventory_summary(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Returns HUD summary telemetry for products and inventory balances."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
        active_products = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(quantity_on_hand), 0) FROM inventory i JOIN products p ON i.product_id = p.id WHERE p.is_active = 1")
        total_stock = round(float(cur.fetchone()[0]), 2)

        cur.execute(
            """
            SELECT COUNT(*) FROM inventory i
            JOIN products p ON i.product_id = p.id
            WHERE p.is_active = 1 AND i.quantity_on_hand <= i.reorder_level AND i.quantity_on_hand > 0
            """
        )
        low_stock_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*) FROM inventory i
            JOIN products p ON i.product_id = p.id
            WHERE p.is_active = 1 AND i.quantity_on_hand <= 0
            """
        )
        out_of_stock_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*) FROM products
            WHERE is_active = 1 AND (purchase_price <= 0 OR selling_price <= 0 OR purchase_price IS NULL OR selling_price IS NULL)
            """
        )
        missing_price_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COALESCE(category, 'Uncategorized') as category, COUNT(*) as count
            FROM products
            WHERE is_active = 1
            GROUP BY category
            ORDER BY count DESC
            LIMIT 10
            """
        )
        categories = [dict(r) for r in cur.fetchall()]

        return {
            "active_products": active_products,
            "total_stock_units": total_stock,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "missing_price_count": missing_price_count,
            "categories": categories
        }
    finally:
        if close_after:
            conn.close()


def suggest_column_mappings(columns: List[str]) -> Dict[str, str]:
    """Suggests intelligent mappings from extracted spreadsheet column headers to catalogue fields."""
    mapping = {}
    clean_cols = {col.lower().strip().replace("_", " ").replace("-", " "): col for col in columns}

    rules = {
        "sku": ["sku", "item code", "product code", "code", "barcode", "art no", "article"],
        "name": ["product name", "item name", "product", "item", "description", "title", "name"],
        "category": ["category", "dept", "department", "group", "product group", "type"],
        "brand": ["brand", "manufacturer", "make"],
        "supplier": ["supplier", "vendor", "distributor", "provider"],
        "purchase_price": ["purchase price", "cost price", "purchase cost", "unit cost", "buy price", "cost", "buying price"],
        "selling_price": ["selling price", "sell price", "retail price", "price", "mrp", "unit price", "rate"],
        "unit": ["unit", "uom", "measurement", "unit of measure"],
        "opening_stock": ["opening stock", "stock", "quantity", "qty", "balance", "on hand", "inventory"],
        "reorder_level": ["reorder level", "reorder", "min stock", "minimum stock", "safety stock", "threshold"]
    }

    used_cols = set()
    for field, candidates in rules.items():
        matched = False
        for cand in candidates:
            if cand in clean_cols and clean_cols[cand] not in used_cols:
                mapping[field] = clean_cols[cand]
                used_cols.add(clean_cols[cand])
                matched = True
                break
        if matched:
            continue
        for cand in candidates:
            for clean_name, orig_name in clean_cols.items():
                if orig_name not in used_cols and cand in clean_name:
                    mapping[field] = orig_name
                    used_cols.add(orig_name)
                    matched = True
                    break
            if matched:
                break

    return mapping


def preview_product_spreadsheet_import(dataset_id: str, column_mapping: Dict[str, str],
                                       sheet_name: Optional[str] = None,
                                       conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Parses and validates spreadsheet records against the provided column mapping.
    Categorizes rows into valid, duplicate, and invalid, returning row-level diagnostic messages.
    """
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM datasets WHERE id = ?", (dataset_id,))
        if not cur.fetchone():
            raise ValueError(f"Dataset {dataset_id} not found")

        # Get records
        if sheet_name:
            cur.execute(
                """
                SELECT r.row_index, r.record_json
                FROM dataset_records r
                JOIN dataset_sheets s ON r.sheet_id = s.id
                WHERE r.dataset_id = ? AND s.sheet_name = ?
                ORDER BY r.row_index ASC
                """,
                (dataset_id, sheet_name)
            )
        else:
            cur.execute(
                """
                SELECT row_index, record_json
                FROM dataset_records
                WHERE dataset_id = ?
                ORDER BY row_index ASC
                """,
                (dataset_id,)
            )

        rows = cur.fetchall()
        if not rows:
            raise ValueError(f"No structured records found in dataset {dataset_id}")

        # Fetch existing products for duplicate detection
        cur.execute("SELECT sku, name FROM products")
        existing_skus = set()
        existing_names = set()
        for p in cur.fetchall():
            if p["sku"]:
                existing_skus.add(p["sku"].strip().lower())
            if p["name"]:
                existing_names.add(p["name"].strip().lower())

        total_rows = len(rows)
        valid_count = 0
        duplicate_count = 0
        invalid_count = 0
        errors = []
        sample_preview = []

        seen_batch_skus = set()
        seen_batch_names = set()

        for r in rows:
            row_idx = r["row_index"] + 1
            rec = safe_json_loads(r["record_json"], {})
            row_errors = []

            # Extract fields
            name_col = column_mapping.get("name")
            name_val = str(rec.get(name_col) or "").strip() if name_col else ""

            if not name_val:
                row_errors.append("Product name is missing or empty")

            sku_col = column_mapping.get("sku")
            sku_val = str(rec.get(sku_col) or "").strip() if sku_col else ""

            # Check prices
            purchase_price = 0.0
            p_col = column_mapping.get("purchase_price")
            if p_col and rec.get(p_col) is not None and str(rec.get(p_col)).strip() != "":
                try:
                    purchase_price = round(float(rec[p_col]), 2)
                    if purchase_price < 0:
                        row_errors.append("Purchase price cannot be negative")
                except (ValueError, TypeError):
                    row_errors.append(f"Invalid purchase price: '{rec[p_col]}'")

            selling_price = 0.0
            s_col = column_mapping.get("selling_price")
            if s_col and rec.get(s_col) is not None and str(rec.get(s_col)).strip() != "":
                try:
                    selling_price = round(float(rec[s_col]), 2)
                    if selling_price < 0:
                        row_errors.append("Selling price cannot be negative")
                except (ValueError, TypeError):
                    row_errors.append(f"Invalid selling price: '{rec[s_col]}'")

            opening_stock = 0.0
            st_col = column_mapping.get("opening_stock")
            if st_col and rec.get(st_col) is not None and str(rec.get(st_col)).strip() != "":
                try:
                    opening_stock = round(float(rec[st_col]), 4)
                    if opening_stock < 0:
                        row_errors.append("Opening stock cannot be negative")
                except (ValueError, TypeError):
                    row_errors.append(f"Invalid opening stock: '{rec[st_col]}'")

            reorder_level = 0.0
            ro_col = column_mapping.get("reorder_level")
            if ro_col and rec.get(ro_col) is not None and str(rec.get(ro_col)).strip() != "":
                try:
                    reorder_level = round(float(rec[ro_col]), 4)
                    if reorder_level < 0:
                        row_errors.append("Reorder level cannot be negative")
                except (ValueError, TypeError):
                    row_errors.append(f"Invalid reorder level: '{rec[ro_col]}'")

            # Duplicate check
            is_duplicate = False
            if sku_val:
                sku_lower = sku_val.lower()
                if sku_lower in existing_skus or sku_lower in seen_batch_skus:
                    is_duplicate = True
                seen_batch_skus.add(sku_lower)

            if name_val:
                name_lower = name_val.lower()
                if name_lower in existing_names or name_lower in seen_batch_names:
                    is_duplicate = True
                seen_batch_names.add(name_lower)

            status = "invalid" if row_errors else ("duplicate" if is_duplicate else "valid")
            if status == "invalid":
                invalid_count += 1
                errors.append({"row": row_idx, "message": "; ".join(row_errors)})
            elif status == "duplicate":
                duplicate_count += 1
            else:
                valid_count += 1

            if len(sample_preview) < 10:
                sample_preview.append({
                    "row_index": row_idx,
                    "name": name_val,
                    "sku": sku_val,
                    "purchase_price": purchase_price,
                    "selling_price": selling_price,
                    "opening_stock": opening_stock,
                    "reorder_level": reorder_level,
                    "status": status,
                    "errors": row_errors
                })

        return {
            "dataset_id": dataset_id,
            "total_rows": total_rows,
            "valid_count": valid_count,
            "duplicate_count": duplicate_count,
            "invalid_count": invalid_count,
            "errors": errors[:50],
            "sample_preview": sample_preview
        }
    finally:
        if close_after:
            conn.close()


def commit_product_spreadsheet_import(dataset_id: str, column_mapping: Dict[str, str],
                                      duplicate_strategy: str = "skip_existing",
                                      sheet_name: Optional[str] = None,
                                      conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Applies confirmed spreadsheet import to the product catalogue transactionally.
    Respects duplicate_strategy ('skip_existing' or 'update_permitted_fields').
    Prevents duplicate opening stock movements on repeated imports.
    """
    valid_strategies = {"skip_existing", "update_permitted_fields"}
    if duplicate_strategy not in valid_strategies:
        raise ValueError(f"Invalid duplicate strategy '{duplicate_strategy}'. Allowed: {', '.join(sorted(valid_strategies))}")

    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM datasets WHERE id = ?", (dataset_id,))
        if not cur.fetchone():
            raise ValueError(f"Dataset {dataset_id} not found")

        # Check if already imported from this dataset to protect against repeat opening stock
        cur.execute("SELECT COUNT(*) FROM products WHERE source_dataset_id = ?", (dataset_id,))
        previously_imported_count = cur.fetchone()[0]

        # Fetch records
        if sheet_name:
            cur.execute(
                """
                SELECT r.row_index, r.record_json
                FROM dataset_records r
                JOIN dataset_sheets s ON r.sheet_id = s.id
                WHERE r.dataset_id = ? AND s.sheet_name = ?
                ORDER BY r.row_index ASC
                """,
                (dataset_id, sheet_name)
            )
        else:
            cur.execute(
                """
                SELECT row_index, record_json
                FROM dataset_records
                WHERE dataset_id = ?
                ORDER BY row_index ASC
                """,
                (dataset_id,)
            )

        rows = cur.fetchall()
        created_count = 0
        updated_count = 0
        skipped_count = 0
        errors = []
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with conn:
            for r in rows:
                row_idx = r["row_index"] + 1
                rec = safe_json_loads(r["record_json"], {})

                name_col = column_mapping.get("name")
                name_val = str(rec.get(name_col) or "").strip() if name_col else ""
                if not name_val:
                    errors.append({"row": row_idx, "message": "Product name is missing"})
                    continue

                sku_col = column_mapping.get("sku")
                sku_val = str(rec.get(sku_col) or "").strip() if sku_col else None

                desc_col = column_mapping.get("description")
                desc_val = str(rec.get(desc_col) or "").strip() if desc_col else None

                cat_col = column_mapping.get("category")
                cat_val = str(rec.get(cat_col) or "").strip() if cat_col else None

                brand_col = column_mapping.get("brand")
                brand_val = str(rec.get(brand_col) or "").strip() if brand_col else None

                unit_col = column_mapping.get("unit")
                unit_val = str(rec.get(unit_col) or "piece").strip().lower() or "piece" if unit_col else "piece"

                supplier_col = column_mapping.get("supplier")
                supplier_id = None
                if supplier_col and rec.get(supplier_col):
                    sup_name = str(rec.get(supplier_col)).strip()
                    if sup_name:
                        sup_record = create_or_get_supplier(sup_name, conn=conn)
                        supplier_id = sup_record.get("id")

                # Parse prices
                try:
                    p_col = column_mapping.get("purchase_price")
                    purchase_price = round(float(rec.get(p_col) or 0.0), 2) if p_col else 0.0
                    if purchase_price < 0:
                        errors.append({"row": row_idx, "message": "Purchase price cannot be negative"})
                        continue
                except Exception:
                    errors.append({"row": row_idx, "message": "Invalid purchase price"})
                    continue

                try:
                    s_col = column_mapping.get("selling_price")
                    selling_price = round(float(rec.get(s_col) or 0.0), 2) if s_col else 0.0
                    if selling_price < 0:
                        errors.append({"row": row_idx, "message": "Selling price cannot be negative"})
                        continue
                except Exception:
                    errors.append({"row": row_idx, "message": "Invalid selling price"})
                    continue

                try:
                    st_col = column_mapping.get("opening_stock")
                    opening_stock = round(float(rec.get(st_col) or 0.0), 4) if st_col else 0.0
                    if opening_stock < 0:
                        errors.append({"row": row_idx, "message": "Opening stock cannot be negative"})
                        continue
                except Exception:
                    errors.append({"row": row_idx, "message": "Invalid opening stock"})
                    continue

                try:
                    ro_col = column_mapping.get("reorder_level")
                    reorder_level = round(float(rec.get(ro_col) or 0.0), 4) if ro_col else 0.0
                    if reorder_level < 0:
                        errors.append({"row": row_idx, "message": "Reorder level cannot be negative"})
                        continue
                except Exception:
                    errors.append({"row": row_idx, "message": "Invalid reorder level"})
                    continue

                # Check if product exists
                existing_prod = None
                if sku_val:
                    cur.execute("SELECT * FROM products WHERE LOWER(TRIM(sku)) = LOWER(TRIM(?))", (sku_val,))
                    existing_prod = cur.fetchone()

                if not existing_prod:
                    cur.execute("SELECT * FROM products WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (name_val,))
                    existing_prod = cur.fetchone()

                if existing_prod:
                    if duplicate_strategy == "skip_existing":
                        skipped_count += 1
                        continue
                    elif duplicate_strategy == "update_permitted_fields":
                        # Update permitted fields only (DO NOT overwrite stock or prices)
                        cur.execute(
                            """
                            UPDATE products SET
                                description = COALESCE(?, description),
                                category = COALESCE(?, category),
                                brand = COALESCE(?, brand),
                                unit = COALESCE(?, unit),
                                supplier_id = COALESCE(?, supplier_id),
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (desc_val, cat_val, brand_val, unit_val, supplier_id, now_str, existing_prod["id"])
                        )
                        updated_count += 1
                        continue

                # Create new product
                cur.execute(
                    """
                    INSERT INTO products (
                        sku, name, description, category, brand, unit, supplier_id,
                        purchase_price, selling_price, currency, is_active,
                        created_at, updated_at, source_dataset_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'INR', 1, ?, ?, ?)
                    """,
                    (sku_val, name_val, desc_val, cat_val, brand_val, unit_val, supplier_id,
                     purchase_price, selling_price, now_str, now_str, dataset_id)
                )
                new_prod_id = cur.lastrowid

                # Inventory balance
                cur.execute(
                    """
                    INSERT INTO inventory (product_id, quantity_on_hand, reorder_level, unit, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (new_prod_id, opening_stock, reorder_level, unit_val, now_str)
                )

                # Opening balance movement (only if opening stock > 0)
                if opening_stock > 0:
                    cur.execute(
                        """
                        INSERT INTO inventory_movements (
                            product_id, movement_type, quantity_delta, quantity_before, quantity_after,
                            reason, reference, created_at, source_dataset_id
                        ) VALUES (?, 'opening_balance', ?, 0.0, ?, 'Imported spreadsheet opening stock', 'IMPORT', ?, ?)
                        """,
                        (new_prod_id, opening_stock, opening_stock, now_str, dataset_id)
                    )

                created_count += 1

        return {
            "success": True,
            "dataset_id": dataset_id,
            "created_count": created_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "error_count": len(errors),
            "errors": errors[:50],
            "previously_imported_count": previously_imported_count
        }
    finally:
        if close_after:
            conn.close()

