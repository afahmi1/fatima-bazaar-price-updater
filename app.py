"""Fatima Bazaar Price Updater — local web app.

Run with:  python3 app.py   (or use the Start.command launcher)
Then open: http://127.0.0.1:5000

Everything runs locally on this Mac. No data leaves the computer.
"""

import json
import os
import uuid
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for, send_file, flash, jsonify
)
from werkzeug.utils import secure_filename

import database as db
import parser as invoice_parser
import catalog
from pricing import compute_prices

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
BATCH_DIR = os.path.join(DATA_DIR, "batches")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")

for d in (DATA_DIR, UPLOAD_DIR, BATCH_DIR, EXPORT_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)
app.secret_key = "fatima-bazaar-local-secret"  # local-only app; fine to hardcode
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB uploads

db.init_db()

# Fallback header set, used only if no inventory export has been loaded yet.
# Normally the export reproduces your Item Library export's own columns so the
# file is a true round-trip (update existing by item id + create new).
DEFAULT_FIELDNAMES = [
    "item id", "name", "category group", "category", "price", "barcode",
    "unit of measure",
]

# Fields carried over from the master inventory through the review form. Only
# the majority-filled, Toast-required detail columns: category group + category.
CARRY_FIELDS = ["category_group", "category"]


# ---------------------------------------------------------------------------
# Batch helpers (working set is stored on disk so it survives page navigation)
# ---------------------------------------------------------------------------

def _save_batch(batch):
    path = os.path.join(BATCH_DIR, batch["id"] + ".json")
    with open(path, "w") as f:
        json.dump(batch, f)


def _load_batch(batch_id):
    path = os.path.join(BATCH_DIR, secure_filename(batch_id) + ".json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


# A top suggestion at/above this weighted-overlap score is pre-selected on the
# review screen (operator can still change it); below it, default is "new item".
_PRESELECT_SCORE = 0.5


def _option_from_record(rec, tag):
    """Build a dropdown option for an inventory candidate record."""
    r = rec["rec"]
    bits = [r.get("name", "")]
    if rec.get("sig"):
        bits.append(rec["sig"])
    if r.get("barcode"):
        bits.append(r["barcode"])
    return {
        "value": rec["id"],
        "label": " · ".join(bits) + f"  ({tag})",
        "category_group": r.get("category_group", ""),
        "category": r.get("category", ""),
        "barcode": r.get("barcode", ""),
    }


def _build_row(name, invoice_barcode=None):
    """Assemble one review row: match options (confident match / learned alias /
    suggestions / create-new), the pre-selected choice, and category prefill.
    """
    cat = catalog.get_catalog()
    mem = db.get_item(name)

    # 1) confident link: learned alias -> confident catalog match
    confident = None
    alias_id = db.get_alias(name)
    if alias_id:
        confident = cat.record_by_id(alias_id)
    if not confident:
        confident = cat._find_record(name=name, sku=invoice_barcode)

    # 2) softer candidates to offer for confirmation
    suggestions = cat.suggest(name, sku=invoice_barcode, topk=3)

    options = [{"value": "NEW", "label": "➕ Create as NEW item",
                "category_group": "", "category": "", "barcode": ""}]
    seen = set()
    if confident:
        options.append(_option_from_record(confident, "match"))
        seen.add(confident["id"])
    for s in suggestions:
        rec = s["record"]
        if rec["id"] and rec["id"] not in seen:
            options.append(_option_from_record(rec, "suggested"))
            seen.add(rec["id"])

    # which option is pre-selected
    if confident:
        selected = confident["id"]
    elif suggestions and suggestions[0]["score"] >= _PRESELECT_SCORE:
        selected = suggestions[0]["record"]["id"]
    else:
        selected = "NEW"

    sel_opt = next(o for o in options if o["value"] == selected)

    # category prefill from the selected match, else memory, else a guess
    guessed = False
    if selected != "NEW":
        category_group = sel_opt["category_group"]
        category = sel_opt["category"]
    elif mem and mem.get("category"):
        category_group, category = mem.get("category_group", ""), mem["category"]
    else:
        g_group, g_cat = cat.guess_category(name)
        category_group, category = g_group, g_cat
        guessed = bool(g_cat)

    return {
        "options": options,
        "selected": selected,
        "matched": selected != "NEW",
        "confident": bool(confident),
        "known": bool(mem),
        "guessed": guessed,
        "category_group": category_group,
        "category": category,
        "pricing_type": (mem or {}).get("pricing_type"),
        "sku": (mem or {}).get("sku") or invoice_barcode
        or sel_opt.get("barcode") or "",
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template(
        "index.html",
        item_count=len(db.all_items()),
        catalog_count=catalog.get_catalog().count,
    )


@app.route("/master", methods=["POST"])
def master_upload():
    file = request.files.get("master")
    if not file or file.filename == "":
        flash("Please choose your Toast inventory CSV export.")
        return redirect(url_for("index"))
    file.save(catalog.MASTER_PATH)
    cat = catalog.reload_catalog()
    flash(f"Inventory list updated — {cat.count} items loaded.")
    return redirect(url_for("index"))


@app.route("/upload", methods=["POST"])
def upload():
    state = request.form.get("state", "other")
    file = request.files.get("invoice")
    if not file or file.filename == "":
        flash("Please choose an invoice file.")
        return redirect(url_for("index"))

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in invoice_parser.SUPPORTED_EXTENSIONS:
        flash(f"Unsupported file type '{ext}'. Use PDF, Excel, CSV or Word.")
        return redirect(url_for("index"))

    save_path = os.path.join(UPLOAD_DIR, filename)
    file.save(save_path)

    try:
        extracted = invoice_parser.extract_invoice(save_path)
    except Exception as e:  # noqa: BLE001 - surface any parse error to the user
        flash(f"Could not read that file: {e}")
        return redirect(url_for("index"))

    if not extracted:
        flash("No line items were detected. Check the file format.")

    rows = []
    for it in extracted:
        info = _build_row(it["name"], invoice_barcode=it.get("barcode"))
        # Remembered choice wins; otherwise use what the parser detected from the
        # invoice's UOM column (e.g. "lb" -> weight), else default to quantity.
        pricing_type = (info["pricing_type"] or it.get("pricing_type")
                        or "quantity")
        row = {
            "name": it["name"],
            "qty": it.get("qty"),
            "cost": it.get("cost"),
            "known": info["known"],
            "matched": info["matched"],
            "confident": info["confident"],
            "pricing_type": pricing_type,
            "sku": info["sku"],
            "guessed": info["guessed"],
            "options": info["options"],
            "selected": info["selected"],
            "category_group": info["category_group"],
            "category": info["category"],
        }
        rows.append(row)

    batch = {
        "id": uuid.uuid4().hex[:12],
        "state": state,
        "filename": filename,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
    }
    _save_batch(batch)
    return redirect(url_for("review", batch_id=batch["id"]))


@app.route("/lookup_sku")
def lookup_sku():
    """Live SKU/barcode search of the inventory (used by the review screen)."""
    sku = (request.args.get("sku") or "").strip()
    if not sku or sku.upper() == "N/A":
        return jsonify({"found": False})
    rec = catalog.get_catalog()._find_record(sku=sku)  # barcode-only match
    if not rec:
        return jsonify({"found": False})
    r = rec["rec"]
    label = " · ".join(b for b in (r.get("name"), rec.get("sig"),
                                   r.get("barcode")) if b) + "  (SKU match)"
    return jsonify({
        "found": True,
        "item_id": rec["id"],
        "label": label,
        "category_group": r.get("category_group", ""),
        "category": r.get("category", ""),
    })


@app.route("/review/<batch_id>")
def review(batch_id):
    batch = _load_batch(batch_id)
    if not batch:
        flash("That batch expired. Please upload again.")
        return redirect(url_for("index"))
    return render_template("review.html", batch=batch)


@app.route("/finalize/<batch_id>", methods=["POST"])
def finalize(batch_id):
    batch = _load_batch(batch_id)
    if not batch:
        flash("That batch expired. Please upload again.")
        return redirect(url_for("index"))

    state = batch["state"]
    n = int(request.form.get("row_count", 0))
    results = []

    for i in range(n):
        if request.form.get(f"include_{i}") != "on":
            continue
        name = (request.form.get(f"name_{i}") or "").strip()
        if not name:
            continue
        pricing_type = request.form.get(f"type_{i}", "quantity")
        sku = (request.form.get(f"sku_{i}") or "N/A").strip() or "N/A"
        cost = request.form.get(f"cost_{i}")
        divisor = request.form.get(f"divisor_{i}")
        try:
            cost = float(cost)
        except (TypeError, ValueError):
            continue
        try:
            divisor = float(divisor) if divisor else 1.0
        except (TypeError, ValueError):
            divisor = 1.0

        # Gather the Toast detail fields (visible + hidden passthrough).
        extras = {}
        for f in CARRY_FIELDS:
            extras[f] = (request.form.get(f"{f}_{i}") or "").strip()

        # The operator's chosen match: a Toast item id, or "NEW".
        cat = catalog.get_catalog()
        chosen = (request.form.get(f"match_{i}") or "NEW").strip()
        full_row = None
        matched = False
        if chosen and chosen != "NEW":
            full_row = cat.get_full_row_by_id(chosen)
            matched = bool(full_row)
            mrec = cat.record_by_id(chosen)
            if mrec:
                for f in CARRY_FIELDS:
                    if not extras.get(f) and mrec["rec"].get(f):
                        extras[f] = mrec["rec"][f]
            # Learn this vendor wording -> item id, keyed on the ORIGINAL
            # invoice name so the same vendor description matches next time.
            orig_name = batch["rows"][i]["name"] if i < len(batch["rows"]) else name
            db.set_alias(orig_name, chosen)
            if orig_name.strip().lower() != name.strip().lower():
                db.set_alias(name, chosen)

        prices = compute_prices(cost, divisor, state)

        # Manual override: if the operator typed a price, use it verbatim.
        sell_price = prices["sell_price"]
        overridden = False
        ov = request.form.get(f"price_override_{i}")
        if ov not in (None, ""):
            try:
                ov = float(ov)
                if ov > 0:
                    sell_price = round(ov, 2)
                    overridden = True
            except (TypeError, ValueError):
                pass

        # Unit of measure: "LB" for weight items so Toast sells them by the
        # pound; left blank for quantity items (Toast defaults to each).
        unit_of_measure = "LB" if pricing_type == "weight" else ""

        # barcode for export: blank if N/A (Toast shouldn't store "N/A")
        barcode = "" if sku.upper() == "N/A" else sku
        extras["barcode"] = barcode

        # Remember everything for next time.
        db.upsert_item(name, pricing_type, sku, extras)

        results.append({
            "name": name,
            "sku": sku,
            "barcode": barcode,
            "pricing_type": pricing_type,
            "unit_label": "per lb" if pricing_type == "weight" else "per item",
            "cost": cost,
            "divisor": divisor,
            "base_unit_cost": prices["base_unit_cost"],
            "adjusted_cost": prices["adjusted_cost"],
            "sell_price": sell_price,
            "overridden": overridden,
            "unit_of_measure": unit_of_measure,
            "matched": matched,
            "full_row": full_row,
            **{f: extras.get(f, "") for f in CARRY_FIELDS},
        })

    if not results:
        flash("No items were selected to process.")
        return redirect(url_for("review", batch_id=batch_id))

    export_name = _write_item_library_csv(results)
    n_update = sum(1 for r in results if r.get("full_row"))
    return render_template(
        "results.html",
        results=results,
        state=state,
        export_name=export_name,
        n_update=n_update,
        n_new=len(results) - n_update,
    )


def _write_item_library_csv(results):
    """Write ONE Toast Item Library round-trip CSV.

    Columns match your Item Library export exactly. For items already in your
    inventory, the original row is reproduced with only the price changed (the
    row keeps its `item id`, so Toast updates it in place). For new items, a row
    with a blank `item id` is written so Toast creates it. Importing this single
    file therefore updates existing prices AND adds new items in one pass.
    """
    import csv

    cat = catalog.get_catalog()
    fieldnames = cat.fieldnames or DEFAULT_FIELDNAMES
    low = {f.lower(): f for f in fieldnames}

    def col(target):
        return low.get(target.lower())

    c_name = col("name")
    c_group = col("category group")
    c_cat = col("category")
    c_price = col("price")
    c_barcode = col("barcode")
    c_uom = col("unit of measure")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"toast_item_library_{stamp}.csv"
    path = os.path.join(EXPORT_DIR, fname)

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            price_str = f"${r['sell_price']:.2f}"
            if r.get("full_row"):
                # Existing item: copy its real row, change only the price.
                row = dict(r["full_row"])
                if c_price:
                    row[c_price] = price_str
            else:
                # New item: blank row (no item id) so Toast creates it.
                row = {fn: "" for fn in fieldnames}
                if c_name:
                    row[c_name] = r["name"]
                if c_group:
                    row[c_group] = r.get("category_group", "")
                if c_cat:
                    row[c_cat] = r.get("category", "")
                if c_price:
                    row[c_price] = price_str
                if c_barcode:
                    row[c_barcode] = r.get("barcode", "")
                if c_uom:
                    row[c_uom] = r.get("unit_of_measure", "")
            writer.writerow(row)
    return fname


@app.route("/download/<name>")
def download(name):
    path = os.path.join(EXPORT_DIR, secure_filename(name))
    if not os.path.exists(path):
        flash("Export not found.")
        return redirect(url_for("index"))
    return send_file(path, as_attachment=True)


@app.route("/items")
def items():
    return render_template("items.html", items=db.all_items())


@app.route("/items/delete/<int:item_id>", methods=["POST"])
def delete_item(item_id):
    db.delete_item(item_id)
    flash("Item removed from memory.")
    return redirect(url_for("items"))


@app.route("/items/clear", methods=["POST"])
def clear_items():
    n = db.clear_all_items()
    flash(f"Cleared item memory — {n} item(s) forgotten.")
    return redirect(url_for("items"))


if __name__ == "__main__":
    import webbrowser
    import threading

    url = "http://127.0.0.1:5000"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print("\n" + "=" * 54)
    print("  Fatima Bazaar Price Updater is running")
    print(f"  Open this in your browser:  {url}")
    print("  (Press Control-C in this window to stop)")
    print("=" * 54 + "\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
