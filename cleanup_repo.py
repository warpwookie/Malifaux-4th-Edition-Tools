"""
cleanup_repo.py — Archive one-off scripts to a subfolder.
Lists everything it would move, then asks for confirmation.

Usage:
    python cleanup_repo.py              # List files to archive (dry run)
    python cleanup_repo.py --archive    # Move files after confirmation
"""
import argparse
import shutil
from pathlib import Path

ARCHIVE_DIR = Path("archive_scripts")

# Core pipeline files to KEEP (in scripts/ subdirectory)
KEEP_IN_SCRIPTS = {
    "pdf_text_extractor.py",
    "pdf_text_batch.py",
    "merger.py",
    "validator.py",
    "db_loader.py",
    "denormalize.py",
    "detect_m3e.py",
    "load_rules_data.py",
    "generate_token_reference.py",
}

# Core files to KEEP in root
KEEP_IN_ROOT = {
    "final_audit.py",
    "cleanup_repo.py",
}

# Prefixes that indicate known one-off scripts
KNOWN_PREFIXES = [
    "fix_",
    "reextract_",
    "check_",
    "list_",
    "mark_",
    "diagnose_",
]

def find_archivable(root="."):
    """Find all .py scripts in root that aren't core files."""
    archivable = []
    for f in sorted(Path(root).glob("*.py")):
        if f.name not in KEEP_IN_ROOT:
            archivable.append(f)
    return archivable

def main():
    parser = argparse.ArgumentParser(description="Archive one-off scripts")
    parser.add_argument("--archive", action="store_true", help="Actually move files")
    args = parser.parse_args()

    archivable = find_archivable()

    if not archivable:
        print("No scripts to archive. Repo is clean!")
        return

    # Split into known one-offs vs unknown
    known = []
    unknown = []
    for f in archivable:
        if any(f.name.startswith(p) for p in KNOWN_PREFIXES):
            known.append(f)
        else:
            unknown.append(f)

    if known:
        print(f"{'='*60}")
        print(f"ONE-OFF SCRIPTS TO ARCHIVE ({len(known)})")
        print(f"{'='*60}")
        for f in known:
            size = f.stat().st_size
            print(f"  {f.name:45s} ({size:,} bytes)")

    if unknown:
        print(f"\n{'='*60}")
        print(f"UNKNOWN SCRIPTS — review these ({len(unknown)})")
        print(f"{'='*60}")
        for f in unknown:
            size = f.stat().st_size
            print(f"  {f.name:45s} ({size:,} bytes)")

    print(f"\n{'='*60}")
    print(f"KEEPING IN ROOT ({len(KEEP_IN_ROOT)} scripts)")
    print(f"{'='*60}")
    for name in sorted(KEEP_IN_ROOT):
        status = "✓" if Path(name).exists() else "✗ missing"
        print(f"  {name:45s} {status}")

    print(f"\n{'='*60}")
    print(f"KEEPING IN scripts/ ({len(KEEP_IN_SCRIPTS)} core pipeline)")
    print(f"{'='*60}")
    for name in sorted(KEEP_IN_SCRIPTS):
        status = "✓" if Path(f"scripts/{name}").exists() else "✗ missing"
        print(f"  scripts/{name:40s} {status}")

    if args.archive:
        to_archive = list(known)

        if unknown:
            resp = input(f"\nAlso archive the {len(unknown)} unknown script(s)? (y/n): ")
            if resp.strip().lower() == 'y':
                to_archive += unknown

        confirm = input(f"\nArchive {len(to_archive)} files to {ARCHIVE_DIR}/? Type 'yes': ")
        if confirm.strip().lower() == 'yes':
            ARCHIVE_DIR.mkdir(exist_ok=True)
            for f in to_archive:
                shutil.move(str(f), str(ARCHIVE_DIR / f.name))
                print(f"  Moved: {f.name}")
            print(f"\nDone. Archived {len(to_archive)} scripts to {ARCHIVE_DIR}/")
        else:
            print("Aborted. No files moved.")
    else:
        total = len(known) + len(unknown)
        print(f"\nDry run — {total} file(s) found. Use --archive to move them.")

if __name__ == "__main__":
    main()
