#!/usr/bin/env python3
"""
Ingenious Irrigation File Organizer

- Creates a standard Ingenious Irrigation folder tree
- Scans a source directory and moves files into the tree
- Uses keyword + extension rules
- Dry-run mode available (recommended first)
- Avoids overwrites by renaming duplicates
- Writes a log file of all actions

USAGE EXAMPLES:
  # Dry run (preview actions) sorting your Downloads into ~/Ingenious_Irrigation
  python3 ingenious_organizer.py --source ~/Downloads --dest ~/Ingenious_Irrigation --dry-run

  # Real run
  python3 ingenious_organizer.py --source ~/Downloads --dest ~/Ingenious_Irrigation

  # Sort multiple sources (repeat --source)
  python3 ingenious_organizer.py --source ~/Downloads --source ~/Desktop --dest ~/Ingenious_Irrigation --dry-run
"""

from __future__ import annotations
import argparse
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# -----------------------------
# 1) Folder tree definition
# -----------------------------
FOLDER_TREE = [
    "00_Admin/01_Legal",
    "00_Admin/02_Insurance",
    "00_Admin/03_Taxes",
    "00_Admin/04_Licenses_Permits",
    "00_Admin/05_Policies_Procedures",

    "01_Finance/01_Invoices_In",
    "01_Finance/02_Invoices_Out",
    "01_Finance/03_Receipts",
    "01_Finance/04_Banking",
    "01_Finance/05_Payroll",
    "01_Finance/06_Budgets_Forecasts",

    "02_Sales_Marketing/01_Leads",
    "02_Sales_Marketing/02_Proposals_Quotes",
    "02_Sales_Marketing/03_Contracts",
    "02_Sales_Marketing/04_Customer_Communications",
    "02_Sales_Marketing/05_Brand_Assets",
    "02_Sales_Marketing/06_Website_Social",

    "03_Operations/01_SOPs_Checklists",
    "03_Operations/02_Scheduling",
    "03_Operations/03_Vendors",
    "03_Operations/04_Tools_Equipment",
    "03_Operations/05_Job_Costing",

    "04_Projects/01_Active",
    "04_Projects/02_Completed",
    "04_Projects/03_Templates",

    "05_Engineering_Design/01_CAD",
    "05_Engineering_Design/02_Drawings",
    "05_Engineering_Design/03_Specs",
    "05_Engineering_Design/04_Electrical",
    "05_Engineering_Design/05_Hydraulics",
    "05_Engineering_Design/06_BOM_Parts_Lists",

    "06_Field_Documentation/01_Photos",
    "06_Field_Documentation/02_Videos",
    "06_Field_Documentation/03_Site_Notes",
    "06_Field_Documentation/04_As_Builts",

    "07_Product/01_Product_Notes",
    "07_Product/02_RnD",
    "07_Product/03_Testing",
    "07_Product/04_Manufacturing",

    "08_HR/01_Hiring",
    "08_HR/02_Employee_Records",
    "08_HR/03_Training",

    "09_IT/01_Backups",
    "09_IT/02_Software_Licenses",
    "09_IT/03_Hardware_Inventory",

    "99_Inbox_Sort_Later",
]

# -----------------------------
# 2) Classification rules
# -----------------------------

# Extension -> folder mapping (fallback / baseline)
EXTENSION_RULES = {
    # Docs
    ".pdf": "99_Inbox_Sort_Later",
    ".doc": "99_Inbox_Sort_Later",
    ".docx": "99_Inbox_Sort_Later",
    ".txt": "99_Inbox_Sort_Later",
    ".rtf": "99_Inbox_Sort_Later",

    # Spreadsheets
    ".xls": "99_Inbox_Sort_Later",
    ".xlsx": "99_Inbox_Sort_Later",
    ".csv": "99_Inbox_Sort_Later",

    # Images / media
    ".jpg": "06_Field_Documentation/01_Photos",
    ".jpeg": "06_Field_Documentation/01_Photos",
    ".png": "06_Field_Documentation/01_Photos",
    ".gif": "06_Field_Documentation/01_Photos",
    ".heic": "06_Field_Documentation/01_Photos",
    ".mp4": "06_Field_Documentation/02_Videos",
    ".mov": "06_Field_Documentation/02_Videos",

    # CAD / design
    ".dxf": "05_Engineering_Design/01_CAD",
    ".dwg": "05_Engineering_Design/01_CAD",
    ".step": "05_Engineering_Design/01_CAD",
    ".stp": "05_Engineering_Design/01_CAD",
    ".stl": "05_Engineering_Design/01_CAD",
    ".igs": "05_Engineering_Design/01_CAD",
    ".iges": "05_Engineering_Design/01_CAD",

    # Archives
    ".zip": "09_IT/01_Backups",
    ".7z": "09_IT/01_Backups",
    ".rar": "09_IT/01_Backups",
}

# Keyword rules (higher priority than extension rules)
# If filename contains a keyword pattern, it routes to a specific folder.
KEYWORD_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(invoice|inv)\b", re.I), "01_Finance/02_Invoices_Out"),
    (re.compile(r"\b(receipt|paid|payment)\b", re.I), "01_Finance/03_Receipts"),
    (re.compile(r"\b(quote|proposal|estimate)\b", re.I), "02_Sales_Marketing/02_Proposals_Quotes"),
    (re.compile(r"\b(contract|agreement|msa|nda)\b", re.I), "02_Sales_Marketing/03_Contracts"),
    (re.compile(r"\b(lead|prospect)\b", re.I), "02_Sales_Marketing/01_Leads"),
    (re.compile(r"\b(logo|brand|identity|palette|typography)\b", re.I), "02_Sales_Marketing/05_Brand_Assets"),
    (re.compile(r"\b(sop|checklist|procedure|process)\b", re.I), "03_Operations/01_SOPs_Checklists"),
    (re.compile(r"\b(schedule|calendar|route)\b", re.I), "03_Operations/02_Scheduling"),
    (re.compile(r"\b(vendor|supplier|purchase\s*order|po\b)\b", re.I), "03_Operations/03_Vendors"),
    (re.compile(r"\b(job\s*cost|costing|budget)\b", re.I), "03_Operations/05_Job_Costing"),
    (re.compile(r"\b(cad|dwg|dxf|step|stp|drawing)\b", re.I), "05_Engineering_Design/01_CAD"),
    (re.compile(r"\b(spec|specification|datasheet)\b", re.I), "05_Engineering_Design/03_Specs"),
    (re.compile(r"\b(wiring|electrical|schematic)\b", re.I), "05_Engineering_Design/04_Electrical"),
    (re.compile(r"\b(hydraulic|flow|pressure|pump|valve)\b", re.I), "05_Engineering_Design/05_Hydraulics"),
    (re.compile(r"\b(bom|parts?\s*list|bill\s*of\s*materials)\b", re.I), "05_Engineering_Design/06_BOM_Parts_Lists"),
    (re.compile(r"\b(as[-\s]?built)\b", re.I), "06_Field_Documentation/04_As_Builts"),
    (re.compile(r"\b(r&d|research|prototype)\b", re.I), "07_Product/02_RnD"),
    (re.compile(r"\b(test|testing|validation)\b", re.I), "07_Product/03_Testing"),
    (re.compile(r"\b(manufactur|assembly|production)\b", re.I), "07_Product/04_Manufacturing"),
    (re.compile(r"\b(tax|irs|w-?9|1099)\b", re.I), "00_Admin/03_Taxes"),
    (re.compile(r"\b(insurance)\b", re.I), "00_Admin/02_Insurance"),
    (re.compile(r"\b(license|permit)\b", re.I), "00_Admin/04_Licenses_Permits"),
    (re.compile(r"\b(backup)\b", re.I), "09_IT/01_Backups"),
    (re.compile(r"\b(license\s*key|serial|activation)\b", re.I), "09_IT/02_Software_Licenses"),
]

# Things we usually should NOT move (system / app stuff)
SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", ".DS_Store"}
SKIP_EXTENSIONS = {".tmp", ".part", ".crdownload", ".download"}

@dataclass
class PlanItem:
    src: Path
    dest: Path
    reason: str

def ensure_tree(dest_root: Path) -> None:
    for rel in FOLDER_TREE:
        (dest_root / rel).mkdir(parents=True, exist_ok=True)

def safe_destination(dest_path: Path) -> Path:
    """
    If dest already exists, auto-rename:
      file.pdf -> file (1).pdf, file (2).pdf, etc.
    """
    if not dest_path.exists():
        return dest_path

    stem = dest_path.stem
    suffix = dest_path.suffix
    parent = dest_path.parent

    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1

def classify(file_path: Path) -> Tuple[str, str]:
    """
    Returns: (relative_folder, reason)
    """
    name = file_path.name

    # Keyword rules first (highest confidence)
    for pattern, target in KEYWORD_RULES:
        if pattern.search(name):
            return target, f"keyword:{pattern.pattern}"

    # Extension rules next
    ext = file_path.suffix.lower()
    if ext in EXTENSION_RULES:
        return EXTENSION_RULES[ext], f"extension:{ext}"

    # Default
    return "99_Inbox_Sort_Later", "default"

def should_skip(path: Path) -> bool:
    if path.is_dir():
        return path.name in SKIP_DIR_NAMES
    # files
    if path.name in SKIP_DIR_NAMES:
        return True
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return True
    return False

def build_plan(sources: List[Path], dest_root: Path, recursive: bool) -> List[PlanItem]:
    plan: List[PlanItem] = []

    for src_root in sources:
        if not src_root.exists():
            continue

        it = src_root.rglob("*") if recursive else src_root.glob("*")
        for p in it:
            if should_skip(p):
                continue
            if p.is_dir():
                continue  # only moving files

            rel_folder, reason = classify(p)
            dest_dir = dest_root / rel_folder
            dest_dir.mkdir(parents=True, exist_ok=True)

            dest_path = safe_destination(dest_dir / p.name)
            plan.append(PlanItem(src=p, dest=dest_path, reason=reason))

    return plan

def write_log(dest_root: Path, items: List[PlanItem], dry_run: bool) -> Path:
    logs_dir = dest_root / "09_IT/01_Backups" / "Organizer_Logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = logs_dir / f"organizer_{'DRYRUN_' if dry_run else ''}{stamp}.log"

    with log_path.open("w", encoding="utf-8") as f:
        f.write(f"Dry run: {dry_run}\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Total items: {len(items)}\n\n")
        for item in items:
            f.write(f"{item.src}  ->  {item.dest}   [{item.reason}]\n")

    return log_path

def execute_plan(items: List[PlanItem], dry_run: bool) -> None:
    for item in items:
        if dry_run:
            continue
        item.dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item.src), str(item.dest))

def main() -> int:
    parser = argparse.ArgumentParser(description="Organize files into Ingenious Irrigation folder tree.")
    parser.add_argument("--source", action="append", required=True,
                        help="Source directory to scan (repeatable). Example: --source ~/Downloads")
    parser.add_argument("--dest", required=True,
                        help="Destination root. Example: --dest ~/Ingenious_Irrigation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would happen without moving files.")
    parser.add_argument("--non-recursive", action="store_true",
                        help="Only scan the top-level of each source directory (no subfolders).")

    args = parser.parse_args()

    sources = [Path(os.path.expanduser(s)).resolve() for s in args.source]
    dest_root = Path(os.path.expanduser(args.dest)).resolve()

    ensure_tree(dest_root)
    plan = build_plan(sources, dest_root, recursive=not args.non_recursive)

    log_path = write_log(dest_root, plan, dry_run=args.dry_run)

    # Print summary
    print(f"\nIngenious Irrigation Organizer")
    print(f"Destination: {dest_root}")
    print(f"Sources: {', '.join(str(s) for s in sources)}")
    print(f"Files planned: {len(plan)}")
    print(f"Log: {log_path}")

    # Show top 25 planned moves for quick sanity check
    preview = plan[:25]
    if preview:
        print("\nPreview (first 25):")
        for item in preview:
            print(f"- {item.src.name} -> {item.dest.relative_to(dest_root)} [{item.reason}]")
        if len(plan) > 25:
            print(f"... plus {len(plan) - 25} more")

    execute_plan(plan, dry_run=args.dry_run)

    if args.dry_run:
        print("\nDRY RUN complete. Nothing moved.")
        print("If it looks right, run again without --dry-run.")
    else:
        print("\nDone. Files moved.")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
