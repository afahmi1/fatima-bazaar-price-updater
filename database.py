"""SQLite-backed 'memory' of items.

The point of this table is so the app asks the weight/quantity question, the SKU
question, and the category/Toast-detail questions only the FIRST time it sees an
item. After that the stored answers are reused automatically.

The DB file lives under data/items.db (created on first run). It is plain
SQLite, so copying the whole project folder to another Mac carries the memory
with it.
"""

import os
import sqlite3

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "items.db")

# Toast detail fields remembered alongside each item.
EXTRA_FIELDS = [
    "pos_name", "description", "category_group", "category", "subcategory",
    "plu", "brand", "supplier", "selling_strategy", "unit_of_measure",
    "image_url", "barcode",
]


def _connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name_key      TEXT UNIQUE NOT NULL,   -- normalized name for matching
            display_name  TEXT NOT NULL,          -- original-cased name
            pricing_type  TEXT NOT NULL,          -- 'weight' or 'quantity'
            sku           TEXT NOT NULL,          -- barcode or 'N/A'
            created_at    TEXT DEFAULT (datetime('now')),
            updated_at    TEXT DEFAULT (datetime('now'))
        )
        """
    )
    # Add the Toast detail columns if they don't exist yet (simple migration).
    existing = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    for col in EXTRA_FIELDS:
        if col not in existing:
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} TEXT DEFAULT ''")

    # Learned aliases: a confirmed invoice-name -> Toast item id mapping, so a
    # vendor's wording is matched automatically on future invoices.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS aliases (
            name_key   TEXT PRIMARY KEY,
            item_id    TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    conn.close()


def get_alias(name: str):
    """Return a previously-confirmed Toast item id for this invoice name."""
    conn = _connect()
    row = conn.execute(
        "SELECT item_id FROM aliases WHERE name_key = ?", (normalize_name(name),)
    ).fetchone()
    conn.close()
    return row["item_id"] if row else None


def set_alias(name: str, item_id: str):
    conn = _connect()
    conn.execute(
        """INSERT INTO aliases (name_key, item_id, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(name_key) DO UPDATE SET
               item_id = excluded.item_id, updated_at = datetime('now')""",
        (normalize_name(name), item_id),
    )
    conn.commit()
    conn.close()


def normalize_name(name: str) -> str:
    """Normalize an item name so 'Roma Tomato' == 'roma   tomato '."""
    return " ".join((name or "").strip().lower().split())


def get_item(name: str):
    """Return the stored row for an item name, or None if it's new."""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM items WHERE name_key = ?", (normalize_name(name),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_item(name: str, pricing_type: str, sku: str, extras: dict = None):
    """Insert a new item or update an existing one's stored answers."""
    extras = extras or {}
    key = normalize_name(name)
    conn = _connect()
    existing = conn.execute(
        "SELECT id FROM items WHERE name_key = ?", (key,)
    ).fetchone()

    extra_cols = ", ".join(f"{c} = ?" for c in EXTRA_FIELDS)
    extra_vals = [extras.get(c, "") or "" for c in EXTRA_FIELDS]

    if existing:
        conn.execute(
            f"""UPDATE items
                  SET display_name = ?, pricing_type = ?, sku = ?,
                      {extra_cols}, updated_at = datetime('now')
                WHERE name_key = ?""",
            [name.strip(), pricing_type, sku, *extra_vals, key],
        )
    else:
        cols = ", ".join(EXTRA_FIELDS)
        placeholders = ", ".join("?" for _ in EXTRA_FIELDS)
        conn.execute(
            f"""INSERT INTO items
                    (name_key, display_name, pricing_type, sku, {cols})
                VALUES (?, ?, ?, ?, {placeholders})""",
            [key, name.strip(), pricing_type, sku, *extra_vals],
        )
    conn.commit()
    conn.close()


def all_items():
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM items ORDER BY display_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_item(item_id: int):
    conn = _connect()
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def clear_all_items():
    """Forget every remembered item and learned alias. Returns items removed."""
    conn = _connect()
    n = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.execute("DELETE FROM items")
    conn.execute("DELETE FROM aliases")
    conn.commit()
    conn.close()
    return n
