"""Master inventory catalog.

Loads the user's existing Toast inventory export (a CSV of every item already in
their Toast account) and lets us look an invoice item up by barcode or by name.
When we find a match, we carry over the item's category, subcategory, pos name,
brand, etc. so the operator doesn't re-enter information Toast already has.

The master file lives at data/master_inventory.csv. It can be refreshed from the
app's upload page at any time (export a fresh "Retail Items" report from Toast).
"""

import csv
import math
import os
import re
from collections import Counter, defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MASTER_PATH = os.path.join(DATA_DIR, "master_inventory.csv")

# Tokens that carry no category signal (units, pack words, filler).
_STOP_TOKENS = {
    "gr", "g", "kg", "lb", "lbs", "oz", "ml", "l", "ct", "pc", "pcs", "ea",
    "cs", "pkt", "pk", "pack", "case", "ctn", "box", "jar", "jars", "can",
    "cans", "btl", "bottle", "bag", "bags", "the", "and", "with", "of", "for",
    "pl", "size", "new", "org", "organic", "ea.",
}


def _tokens(name):
    """Lowercase alpha tokens >=3 chars, dropping units/numbers/filler."""
    out = []
    for tok in re.split(r"[^A-Za-z]+", (name or "").lower()):
        if len(tok) >= 3 and tok not in _STOP_TOKENS:
            out.append(tok)
    return out


# Size/quantity signature, e.g. "ULKER LEBNI 550 GR" -> "550g". Used as a HARD
# filter so a fuzzy name match never merges two different sizes (400g vs 800g).
_UNIT = r"(?:kg|g(?:r|ram|rams)?|lb|lbs|oz|ml|l|ct|pc|pcs|pk)"
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(" + _UNIT + r")\b", re.I)
_UNIT_CANON = {"gram": "g", "grams": "g", "gr": "g", "lbs": "lb", "pcs": "pc"}


def _size_sig(*texts):
    toks = set()
    for t in texts:
        for m in _SIZE_RE.finditer(t or ""):
            num = float(m.group(1))
            num = int(num) if num == int(num) else num
            unit = m.group(2).lower()
            unit = _UNIT_CANON.get(unit, unit)
            toks.add(f"{num}{unit}")
    return " ".join(sorted(toks))


def _sizes_compatible(a, b):
    """Two size signatures may belong to the same item only if they're equal,
    or one side has no size info at all."""
    if not a or not b:
        return True
    return a == b


# Minimum word-overlap (Jaccard) for a fuzzy name match to count.
_FUZZY_THRESHOLD = 0.67

# Toast export column  ->  our internal field name
COLUMN_MAP = {
    "name": "name",
    "add optional (variation)": "variation",
    "pos name": "pos_name",
    "description": "description",
    "category group": "category_group",
    "category": "category",
    "subcategory": "subcategory",
    "plu": "plu",
    "brand": "brand",
    "supplier": "supplier",
    "selling strategy": "selling_strategy",
    "unit of measure": "unit_of_measure",
    "image url": "image_url",
    "barcode": "barcode",
}

# Fields we hand back to the rest of the app when a match is found.
CARRY_FIELDS = [
    "pos_name", "description", "category_group", "category", "subcategory",
    "plu", "brand", "supplier", "selling_strategy", "unit_of_measure",
    "image_url", "barcode",
]


def _norm(s):
    return " ".join((s or "").strip().lower().split())


class Catalog:
    def __init__(self):
        self.records = []           # list of {rec, raw, toks, sig}
        self.idx_by_barcode = {}
        self.idx_by_name = {}       # normalized exact name -> record index
        self.idx_by_namekey = {}    # (sorted token tuple, size sig) -> index
        self.idx_by_id = {}         # toast item id -> record index
        self.tok_index = defaultdict(list)  # token -> [record indices]
        self.df = Counter()         # token -> document frequency (for IDF)
        self.fieldnames = []        # original export header order
        self.count = 0
        # category guessing
        self.token_cats = defaultdict(Counter)   # token -> Counter[(group,cat)]
        self.token_total = Counter()             # token -> times seen
        self.default_group = "RETAIL"
        self.load()

    def load(self):
        self.records = []
        self.idx_by_barcode = {}
        self.idx_by_name = {}
        self.idx_by_namekey = {}
        self.idx_by_id = {}
        self.tok_index = defaultdict(list)
        self.df = Counter()
        self.fieldnames = []
        self.count = 0
        self.token_cats = defaultdict(Counter)
        self.token_total = Counter()
        group_counts = Counter()
        if not os.path.exists(MASTER_PATH):
            return
        with open(MASTER_PATH, newline="", encoding="utf-8-sig",
                  errors="replace") as f:
            reader = csv.DictReader(f)
            self.fieldnames = list(reader.fieldnames or [])
            headers = {h.strip().lower(): h for h in self.fieldnames}
            for raw in reader:
                rec = {}
                for toast_col, field in COLUMN_MAP.items():
                    src = headers.get(toast_col)
                    rec[field] = (raw.get(src) or "").strip() if src else ""
                self.count += 1
                name = rec.get("name", "")
                toks = frozenset(_tokens(name))
                # size lives in the name and/or the variation column
                sig = _size_sig(name, rec.get("variation", ""))
                iid = (raw.get(headers.get("item id"), "") or "").strip() \
                    if headers.get("item id") else ""
                idx = len(self.records)
                self.records.append(
                    {"rec": rec, "raw": raw, "toks": toks, "sig": sig, "id": iid})

                bc = rec.get("barcode", "")
                if bc:
                    self.idx_by_barcode.setdefault(bc, idx)
                if iid:
                    self.idx_by_id.setdefault(iid, idx)
                nm = _norm(name)
                if nm:
                    self.idx_by_name.setdefault(nm, idx)
                if toks:
                    self.idx_by_namekey.setdefault((tuple(sorted(toks)), sig), idx)
                    for t in toks:
                        self.tok_index[t].append(idx)
                        self.df[t] += 1

                # train the category guesser
                grp = rec.get("category_group", "") or "RETAIL"
                cat = rec.get("category", "")
                if cat:
                    group_counts[grp] += 1
                    key = (grp, cat)
                    for tok in toks:
                        self.token_cats[tok][key] += 1
                        self.token_total[tok] += 1
        if group_counts:
            self.default_group = group_counts.most_common(1)[0][0]

    def _idf(self, tok):
        return math.log(max(self.count, 1) / (1 + self.df.get(tok, 0)))

    def record_by_id(self, item_id):
        if not item_id:
            return None
        idx = self.idx_by_id.get(item_id.strip())
        return self.records[idx] if idx is not None else None

    def _find_record(self, name=None, sku=None):
        """CONFIDENT match only (high precision): barcode → exact name → same
        set of words + same size. Looser candidates go through suggest()."""
        if sku and sku.strip() and sku.strip().upper() != "N/A":
            idx = self.idx_by_barcode.get(sku.strip())
            if idx is not None:
                return self.records[idx]
        if not name:
            return None
        idx = self.idx_by_name.get(_norm(name))
        if idx is not None:
            return self.records[idx]
        # same word set + same size (handles reorder & punctuation only)
        qtoks = frozenset(_tokens(name))
        if qtoks:
            idx = self.idx_by_namekey.get(
                (tuple(sorted(qtoks)), _size_sig(name)))
            if idx is not None:
                return self.records[idx]
        return None

    def suggest(self, name, sku=None, topk=3):
        """Return up to `topk` candidate inventory items for a name that did NOT
        confidently match, ranked by IDF-weighted word overlap (size-guarded).
        These are shown to the operator to confirm — never auto-applied.
        """
        qtoks = frozenset(_tokens(name))
        if not qtoks:
            return []
        qsig = _size_sig(name)
        cand = set()
        for t in qtoks:
            cand.update(self.tok_index.get(t, ()))
        scored = []
        for i in cand:
            rec = self.records[i]
            if not rec["toks"] or not _sizes_compatible(qsig, rec["sig"]):
                continue
            shared = qtoks & rec["toks"]
            if not shared:
                continue
            union = qtoks | rec["toks"]
            # weighted Jaccard: distinctive shared words count for more
            score = (sum(self._idf(t) for t in shared)
                     / sum(self._idf(t) for t in union))
            scored.append((score, rec))
        scored.sort(key=lambda x: -x[0])
        out = []
        seen = set()
        for score, rec in scored:
            iid = rec["rec"].get("barcode", "") + rec["rec"].get("name", "")
            if iid in seen:
                continue
            seen.add(iid)
            out.append({"record": rec, "score": round(score, 3)})
            if len(out) >= topk:
                break
        return out

    def get_full_row(self, name=None, sku=None):
        """Return the item's original full export row (for in-place price
        updates). None if not in inventory."""
        rec = self._find_record(name=name, sku=sku)
        return rec["raw"] if rec else None

    def get_full_row_by_id(self, item_id):
        rec = self.record_by_id(item_id)
        return rec["raw"] if rec else None

    def guess_category(self, name):
        """Best-guess (category_group, category) for a new item, learned from
        the inventory. Each word votes for the categories it tends to appear in,
        normalized so common words don't dominate. Returns ("", "") if no signal.
        """
        scores = Counter()
        for tok in set(_tokens(name)):
            total = self.token_total.get(tok, 0)
            if total < 2:
                continue  # too rare to trust
            for key, cnt in self.token_cats[tok].items():
                scores[key] += cnt / total  # token's probability mass for key
        if not scores:
            return (self.default_group, "")
        (grp, cat), _ = scores.most_common(1)[0]
        return (grp or self.default_group, cat)

    def lookup(self, name=None, sku=None):
        """Find an existing inventory item by barcode, exact name, or fuzzy
        name (word-order / spelling / vendor-naming tolerant, size-guarded).

        Returns a dict of carry-over fields, or None if no match.
        """
        rec = self._find_record(name=name, sku=sku)
        if rec:
            return {k: rec["rec"].get(k, "") for k in CARRY_FIELDS}
        return None


# Singleton, reloaded when a new master file is uploaded.
_catalog = None


def get_catalog():
    global _catalog
    if _catalog is None:
        _catalog = Catalog()
    return _catalog


def reload_catalog():
    global _catalog
    _catalog = Catalog()
    return _catalog
