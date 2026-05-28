import os
import zipfile
from pathlib import Path


def extract_zip(zip_path: Path, dest_dir: Path):
    """Extract zip_path into dest_dir, skipping macOS metadata."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            # Skip macOS metadata artifacts
            if "__MACOSX" in member.filename or member.filename.endswith(".DS_Store"):
                continue
            zf.extract(member, dest_dir)


def recursive_extract(root: Path):
    """Walk root, extract every .zip found, then recurse into extracted dirs."""
    for zip_file in sorted(root.rglob("*.zip")):
        # Extract into a sibling folder named after the zip (without extension)
        target = zip_file.parent / zip_file.stem
        print(f"Extracting: {zip_file.relative_to(root.parent)} → {target.name}/")
        extract_zip(zip_file, target)
        # Recurse into the newly extracted folder
        recursive_extract(target)


if __name__ == "__main__":
    import sys

    zip_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("Voter_Turn_Out_By_Demographics.zip")
    if not zip_path.exists():
        print(f"File not found: {zip_path}")
        sys.exit(1)

    dest = zip_path.parent / zip_path.stem
    print(f"Extracting top-level: {zip_path.name} → {dest.name}/")
    extract_zip(zip_path, dest)
    recursive_extract(dest)
    print("Done.")
