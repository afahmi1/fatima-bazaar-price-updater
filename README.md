# Fatima Bazaar — Price Updater

A small, fully-local Mac app that turns supplier invoices (PDF / Excel / CSV /
Word) into a finished price list. It figures your cost per item or per pound,
adds the state markup, applies your sell-price formula, and exports an Excel
table with **Item Name, SKU, Price**.

Everything runs on your computer. No data is sent anywhere.

---

## Install on a new Mac (one time)

1. Copy this whole **`Fatima Bazaar Price Updater`** folder to the Mac (USB,
   AirDrop, Dropbox — anything).
2. Double-click **`setup.command`**. It installs everything into the folder
   itself. (If macOS blocks it, right-click → **Open**.)
   - Needs Python 3. If it's missing, get it from
     <https://www.python.org/downloads/> and run setup again.

## Use it

1. Double-click **`Start.command`**. The app opens in your web browser at
   `http://127.0.0.1:5000`. Keep that small black window open while you work.
2. **Upload an invoice** and choose where the items are coming from:
   - California → **+5%** added to cost
   - Another state → **+10%** added to cost
3. **Review the items.** For every item the app sees for the **first time** it
   asks two things (only once, then it's remembered):
   - **Priced by weight or quantity** (per lb vs per item)
   - **SKU** — click the SKU box and **scan the barcode** with a scanner plugged
     into the Mac (the scanner just types the number), or leave it **N/A**.
   - Confirm the **cost** and the **units / pounds** so the per-unit cost is right.
4. Click **Calculate prices & build Excel**, then **Download Excel**.

## Toast import

The download is an Excel file whose columns exactly match Toast's **Retail
Template** (sheet `Template`): `name, … category group, category, subcategory,
price, cost, barcode, …`. In it:

- **price** = your calculated sell price
- **cost** = your landed cost (invoice cost + state markup), so Toast's margin is right
- **barcode** = the SKU you scanned (blank if N/A)
- **category / subcategory / pos name / brand …** are carried over automatically
  from your existing inventory list (see below)

To load it into Toast Web:

- **New items:** Item Library → ⋯ menu → **Import item**
- **Price updates to items you already have:** Menus → Bulk menu imports →
  **Item update** template (matches on barcode). Rows shown as
  *IN INVENTORY* already exist — use this path for them to avoid duplicates.

## Your Toast inventory list (auto carry-over)

The app keeps a copy of your current Toast inventory at
`data/master_inventory.csv`. Every invoice item is matched against it — first by
**barcode**, then by **name** — and any match pulls in that item's category,
subcategory, POS name, brand, supplier, PLU and unit of measure so you don't
retype them.

To refresh it, export your Retail Items report as CSV from Toast and upload it on
the app's home page ("Update inventory list").

## The math

```
per-unit cost = invoice line cost ÷ (units or pounds)
adjusted cost = per-unit cost × (1.05 California | 1.10 other state)
sell price    = adjusted cost ÷ 0.625
```

## Memory

The app remembers each item's weight/quantity choice and SKU in
`data/items.db`, so it never asks twice. Manage or delete remembered items from
the **Item Memory** page. Because the database lives inside this folder, copying
the folder to another Mac carries the memory with it.

## Where things are saved

- `data/items.db` — remembered items (the "memory")
- `data/exports/` — the Excel price lists you generate
- `data/uploads/` — the invoices you upload

## Notes on invoice reading

Invoices come in many layouts, so the app makes its best guess and **always lets
you review and correct** every item before prices are calculated. If an invoice
parses poorly, fix the rows on the review screen — the numbers you confirm are
what get used.

## Running manually (optional)

```bash
./.venv/bin/python app.py
```
