"""Shared file utilities — formatting, type detection, and listing.

Extracted from routes/generate.py and routes/planning.py to eliminate duplication.
"""

import os
from pathlib import Path
from typing import Union


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable form (B → KB → MB → GB → TB)."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.0f} TB"


def guess_file_type(filename: str) -> str:
    """Guess the type of a generated file from its extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    type_map = {
        "html": "html",
        "md": "markdown",
        "json": "json",
        "pdf": "pdf",
        "csv": "csv",
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "css": "css",
        "svg": "svg",
        "png": "image",
        "jpg": "image",
        "jpeg": "image",
    }
    return type_map.get(ext, "unknown")


def list_files(dir_path: Union[str, Path], relative: bool = False) -> list[dict]:
    """List all files in a directory tree with size and type metadata.

    Args:
        dir_path: Root directory to walk.
        relative: If True, store path relative to dir_path in a 'path' key.

    Returns:
        List of dicts with filename, size, size_human, type, and optionally path.
    """
    files = []
    for root, _, filenames in os.walk(str(dir_path)):
        for fn in sorted(filenames):
            fp = os.path.join(root, fn)
            size = os.path.getsize(fp)
            entry = {
                "filename": fn,
                "size": size,
                "size_human": format_size(size),
                "type": guess_file_type(fn),
            }
            if relative:
                entry["path"] = os.path.relpath(fp, str(dir_path))
            files.append(entry)
    return files
