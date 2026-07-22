from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


CHINA_TZ = timezone(timedelta(hours=8))


def now_china_iso() -> str:
    return datetime.now(CHINA_TZ).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    write_json_batch_atomic({path: payload})


def write_json_batch_atomic(payloads: Mapping[Path, Any]) -> None:
    """Publish JSON files as one rollback-safe batch.

    Filesystems cannot atomically replace several paths at once. This function
    stages and fsyncs every new file before touching a target, keeps a durable
    backup of every existing target, and restores the whole batch if any
    replacement fails.
    """

    targets: list[Path] = []
    seen: set[Path] = set()
    for raw_path in payloads:
        path = Path(raw_path)
        resolved = path.resolve()
        if resolved in seen:
            raise ValueError(f"duplicate JSON publication target: {path}")
        seen.add(resolved)
        targets.append(path)

    if not targets:
        return

    staged: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    published: set[Path] = set()
    try:
        for path in targets:
            serialized = json.dumps(payloads[path], ensure_ascii=False, indent=2) + "\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            staged[path] = _write_temporary_text(path, serialized, suffix=".tmp")
            backups[path] = _backup_existing_file(path)

        for path in targets:
            os.replace(staged[path], path)
            staged.pop(path, None)
            published.add(path)

        for directory in {path.parent for path in targets}:
            _fsync_directory(directory)
    except BaseException as publish_error:
        rollback_errors: list[Exception] = []
        for path in reversed(targets):
            backup = backups.get(path)
            try:
                if path in published:
                    if backup is None:
                        path.unlink(missing_ok=True)
                    else:
                        os.replace(backup, path)
                        backups[path] = None
                elif backup is not None and not path.exists():
                    os.replace(backup, path)
                    backups[path] = None
            except Exception as rollback_error:
                rollback_errors.append(rollback_error)

        if rollback_errors and hasattr(publish_error, "add_note"):
            details = "; ".join(str(error) for error in rollback_errors)
            publish_error.add_note(f"JSON publication rollback errors: {details}")
        raise
    finally:
        for temporary_path in staged.values():
            temporary_path.unlink(missing_ok=True)
        for backup_path in backups.values():
            if backup_path is not None:
                backup_path.unlink(missing_ok=True)


def _write_temporary_text(path: Path, serialized: str, *, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=suffix,
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
        temporary_file.write(serialized)
        temporary_file.flush()
        os.fsync(temporary_file.fileno())
    return temporary_path


def _backup_existing_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    with tempfile.NamedTemporaryFile(
        mode="w+b",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".bak",
        delete=False,
    ) as backup_file:
        backup_path = Path(backup_file.name)
        with path.open("rb") as source:
            shutil.copyfileobj(source, backup_file)
        backup_file.flush()
        os.fsync(backup_file.fileno())
    return backup_path


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def repo_relative(path: Path, root: Path) -> str:
    return "/" + path.resolve().relative_to(root.resolve()).as_posix()


def emit_result(value: Any) -> None:
    if isinstance(value, Path):
        print(value)
        return
    if isinstance(value, str):
        print(value)
        return
    print(json.dumps(value, ensure_ascii=False, indent=2))
