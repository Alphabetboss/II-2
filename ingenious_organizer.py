#!/usr/bin/env python3
"""
Ingenious Irrigation Organizer — Hybrid, Pi-Ready

Core:
- Creates standard Ingenious Irrigation folder tree
- Classifies by keyword + extension
- EXIF-based date sorting for images (optional)
- PDF text extraction for smarter routing (optional)
- Duplicate detection via content hash
- Dry-run mode
- Rollback log (moves recorded)
- JSON + text logs

Online Boosters (optional, non-blocking):
- Cloud AI classification hook (stubbed; you wire your API later)
- OneDrive sync via rclone remote "onedrive:"

Runtime target:
- Raspberry Pi 5 (Linux)

Requires (install on Pi):
  sudo apt update
  sudo apt install -y python3-pip exiftool rclone
  pip3 install pillow PyPDF2
"""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ExifTags
from PyPDF2 import PdfReader

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

SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", ".DS_Store"}
SKIP_EXTENSIONS = {".tmp", ".part", ".crdownload", ".download"}

# -----------------------------
# 3) Data structures
# -----------------------------
@dataclass
class PlanItem:
    src: Path
    dest: Path
    reason: str
    hash: Optional[str] = None  # for duplicate detection

# -----------------------------
# 4) Helpers
# -----------------------------
def ensure_tree(dest_root: Path) -> None:
    for rel in FOLDER_TREE:
        (dest_root / rel).mkdir(parents=True, exist_ok=True)

def safe_destination(dest_path: Path) -> Path:
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

def file_hash(path: Path, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def extract_exif_date(path: Path) -> Optional[str]:
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif:
            return None
        tag_map = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
        date_str = tag_map.get("DateTimeOriginal") or tag_map.get("DateTime")
        if not date_str:
            return None
        # Format: "YYYY:MM:DD HH:MM:SS"
        parts = date_str.split(" ")[0].split(":")
        if len(parts) >= 3:
            y, m, d = parts[:3]
            return f"{y}-{m}-{d}"
    except Exception:
        return None
    return None

def extract_pdf_text_snippet(path: Path, max_chars: int = 2000) -> str:
    try:
        reader = PdfReader(str(path))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
            if len(text) >= max_chars:
                break
        return text[:max_chars]
    except Exception:
        return ""

def ai_classify_stub(filename: str, text_snippet: str) -> Optional[str]:
    """
    Hybrid hook: this is where you'd call a cloud LLM if online.
    For now, it's a stub that returns None (no override).
    Later you can:
      - Check connectivity
      - Call your API
      - Map response to folder
    """
    # Example pseudo-logic:
    # if not online(): return None
    # response = call_llm_api(filename, text_snippet)
    # return map_response_to_folder(response)
    return None

def classify(file_path: Path) -> Tuple[str, str]:
    """
    Returns: (relative_folder, reason)
    Hybrid logic:
      1) Keyword rules
      2) Extension rules
      3) EXIF / PDF hints
      4) AI stub (optional)
      5) Default inbox
    """
    name = file_path.name

    # 1) Keyword rules
    for pattern, target in KEYWORD_RULES:
        if pattern.search(name):
            return target, f"keyword:{pattern.pattern}"

    # 2) Extension rules
    ext = file_path.suffix.lower()
    if ext in EXTENSION_RULES:
        base_folder = EXTENSION_RULES[ext]
    else:
        base_folder = "99_Inbox_Sort_Later"

    reason_parts = []

    # 3) EXIF for images
    if ext in {".jpg", ".jpeg", ".png", ".heic"}:
        date_str = extract_exif_date(file_path)
        if date_str:
            # Example: route by year under Photos
            year = date_str.split("-")[0]
            base_folder = f"06_Field_Documentation/01_Photos/{year}"
            reason_parts.append(f"exif:{date_str}")

    # 3b) PDF text snippet (for future AI / smarter rules)
    text_snippet = ""
    if ext == ".pdf":
        text_snippet = extract_pdf_text_snippet(file_path)
        # You could add extra regex rules on text_snippet here if you want.

    # 4) AI stub (optional override)
    ai_folder = ai_classify_stub(name, text_snippet)
    if ai_folder:
        return ai_folder, "ai:cloud"

    # 5) Fallback
    if not reason_parts:
        reason_parts.append(f"extension:{ext}" if ext in EXTENSION_RULES else "default")

    return base_folder, "+".join(reason_parts)

def should_skip(path: Path) -> bool:
    if path.is_dir():
        return path.name in SKIP_DIR_NAMES
    if path.name in SKIP_DIR_NAMES:
        return True
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return True
    return False

def build_plan(
    sources: List[Path],
    dest_root: Path,
    recursive: bool,
    enable_hashes: bool = True,
) -> List[PlanItem]:
    plan: List[PlanItem] = []
    seen_hashes: dict[str, Path] = {}

    for src_root in sources:
        if not src_root.exists():
            continue

        it = src_root.rglob("*") if recursive else src_root.glob("*")
        for p in it:
            if should_skip(p):
                continue
            if p.is_dir():
                continue

            rel_folder, reason = classify(p)
            dest_dir = dest_root / rel_folder
            dest_dir.mkdir(parents=True, exist_ok=True)

            h = file_hash(p) if enable_hashes else None
            if h and h in seen_hashes:
                # Duplicate detected
                reason = f"{reason}+duplicate_of:{seen_hashes[h]}"
                # You can choose to skip duplicates instead of moving:
                # plan.append(PlanItem(src=p, dest=p, reason=reason, hash=h))
                # continue
            else:
                if h:
                    seen_hashes[h] = p

            dest_path = safe_destination(dest_dir / p.name)
            plan.append(PlanItem(src=p, dest=dest_path, reason=reason, hash=h))

    return plan

def write_logs(dest_root: Path, items: List[PlanItem], dry_run: bool) -> Tuple[Path, Path, Path]:
    logs_dir = dest_root / "09_IT/01_Backups" / "Organizer_Logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    text_log = logs_dir / f"organizer_{'DRYRUN_' if dry_run else ''}{stamp}.log"
    json_log = logs_dir / f"organizer_{'DRYRUN_' if dry_run else ''}{stamp}.json"
    rollback_log = logs_dir / f"rollback_{'DRYRUN_' if dry_run else ''}{stamp}.json"

    with text_log.open("w", encoding="utf-8") as f:
        f.write(f"Dry run: {dry_run}\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Total items: {len(items)}\n\n")
        for item in items:
            f.write(f"{item.src}  ->  {item.dest}   [{item.reason}]\n")

    with json_log.open("w", encoding="utf-8") as f:
        json.dump([asdict(i) for i in items], f, indent=2, default=str)

    # rollback log: only src/dest
    with rollback_log.open("w", encoding="utf-8") as f:
        json.dump(
            [{"src": str(i.src), "dest": str(i.dest)} for i in items],
            f,
            indent=2,
        )

    return text_log, json_log, rollback_log

def execute_plan(items: List[PlanItem], dry_run: bool) -> None:
    for item in items:
        if dry_run:
            continue
        item.dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item.src), str(item.dest))

def cleanup_empty_dirs(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)
        if p.name in SKIP_DIR_NAMES:
            continue
        try:
            if not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass

def run_onedrive_sync(local_root: Path, remote_name: str = "onedrive", remote_path: str = "Ingenious_Irrigation") -> None:
    """
    Non-blocking OneDrive sync via rclone.
    Assumes you've configured a remote called 'onedrive'.
    Example command:
      rclone sync /path/to/root onedrive:Ingenious_Irrigation
    If rclone or remote is missing, this should fail silently.
    """
    try:
        cmd = [
            "rclone",
            "sync",
            str(local_root),
            f"{remote_name}:{remote_path}",
            "--fast-list",
        ]
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        # Silent fail; core system must never depend on cloud
        pass

def rollback_from_log(rollback_log: Path, dry_run: bool = False) -> None:
    """
    Rollback moves using a rollback log generated earlier.
    This assumes dest files still exist.
    """
    with rollback_log.open("r", encoding="utf-8") as f:
        entries = json.load(f)

    for entry in entries:
        src = Path(entry["src"])
        dest = Path(entry["dest"])
        # To rollback, we move dest back to src
        if not dest.exists():
            continue
        if dry_run:
            print(f"[ROLLBACK DRY] {dest} -> {src}")
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest), str(src))

# -----------------------------
# 5) Main
# -----------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Organize files into Ingenious Irrigation folder tree (Hybrid, Pi-ready).")
    parser.add_argument("--source", action="append", required=False,
                        help="Source directory to scan (repeatable). Example: --source ~/Downloads")
    parser.add_argument("--dest", required=True,
                        help="Destination root. Example: --dest ~/Ingenious_Irrigation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would happen without moving files.")
    parser.add_argument("--non-recursive", action="store_true",
                        help="Only scan the top-level of each source directory (no subfolders).")
    parser.add_argument("--no-hash", action="store_true",
                        help="Disable content hashing (faster, but no duplicate detection).")
    parser.add_argument("--sync-onedrive", action="store_true",
                        help="Attempt OneDrive sync via rclone after organizing.")
    parser.add_argument("--rollback", metavar="ROLLBACK_LOG",
                        help="Rollback moves using a rollback log JSON file.")
    parser.add_argument("--sources-from-file", metavar="FILE",
                        help="Optional: file containing one source path per line.")

    args = parser.parse_args()

    dest_root = Path(os.path.expanduser(args.dest)).resolve()

    # Rollback mode
    if args.rollback:
        rollback_log = Path(args.rollback).resolve()
        print(f"\nRollback mode using log: {rollback_log}")
        rollback_from_log(rollback_log, dry_run=args.dry_run)
        print("\nRollback DRY RUN complete." if args.dry_run else "\nRollback complete.")
        return 0

    # Normal organize mode
    sources: List[Path] = []
    if args.source:
        sources.extend(Path(os.path.expanduser(s)).resolve() for s in args.source)

    if args.sources_from_file:
        src_file = Path(os.path.expanduser(args.sources_from_file)).resolve()
        if src_file.exists():
            with src_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    sources.append(Path(os.path.expanduser(line)).resolve())

    if not sources:
        print("No sources provided. Use --source or --sources-from-file.")
        return 1

    ensure_tree(dest_root)
    plan = build_plan(
        sources,
        dest_root,
        recursive=not args.non_recursive,
        enable_hashes=not args.no_hash,
    )

    text_log, json_log, rollback_log = write_logs(dest_root, plan, dry_run=args.dry_run)

    # Summary
    print(f"\nIngenious Irrigation Organizer (Hybrid)")
    print(f"Destination: {dest_root}")
    print(f"Sources: {', '.join(str(s) for s in sources)}")
    print(f"Files planned: {len(plan)}")
    print(f"Log: {text_log}")
    print(f"JSON: {json_log}")
    print(f"Rollback log: {rollback_log}")

    preview = plan[:25]
    if preview:
        print("\nPreview (first 25):")
        for item in preview:
            try:
                rel_dest = item.dest.relative_to(dest_root)
            except ValueError:
                rel_dest = item.dest
            print(f"- {item.src.name} -> {rel_dest} [{item.reason}]")
        if len(plan) > 25:
            print(f"... plus {len(plan) - 25} more")

    execute_plan(plan, dry_run=args.dry_run)
    cleanup_empty_dirs(dest_root)

    if args.dry_run:
        print("\nDRY RUN complete. Nothing moved.")
        print("If it looks right, run again without --dry-run.")
    else:
        print("\nDone. Files moved.")

    if args.sync_onedrive and not args.dry_run:
        print("\nAttempting OneDrive sync via rclone (non-blocking)...")
        run_onedrive_sync(dest_root)
        print("OneDrive sync triggered (if configured).")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
