"""Archive extraction safety helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any


def is_within(path: Path, root: Path) -> bool:
    root = root.resolve(strict=False)
    path = path.resolve(strict=False)
    return path == root or root in path.parents


def safe_extract_zip(zf: zipfile.ZipFile, output_dir: Path) -> None:
    root = output_dir.resolve(strict=False)
    for member in zf.infolist():
        target = root / member.filename
        if not is_within(target, root):
            raise ValueError(f"Refusing to extract unsafe archive member: {member.filename}")
    zf.extractall(root)


def safe_extract_tar(tf: Any, output_dir: Path) -> None:
    root = output_dir.resolve(strict=False)
    for member in tf.getmembers():
        target = root / member.name
        if not is_within(target, root):
            raise ValueError(f"Refusing to extract unsafe archive member: {member.name}")
        linkname = getattr(member, "linkname", "")
        if linkname:
            link_target = (target.parent / linkname).resolve(strict=False)
            if not is_within(link_target, root):
                raise ValueError(f"Refusing to extract unsafe archive link: {member.name}")
    # filter="data" is the Python 3.12+ default and refuses absolute paths,
    # traversal and special files during extraction. The pre-check above cannot
    # catch a symlink member followed by a write *through* that symlink, since
    # it validates before anything exists on disk.
    try:
        tf.extractall(root, filter="data")
    except TypeError:  # pragma: no cover - Python < 3.12
        tf.extractall(root)
