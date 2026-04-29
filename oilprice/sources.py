from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json


def load_enabled_sources(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    enabled: list[dict[str, Any]] = []
    for province in payload.get("provinces", []):
        for source in province.get("sources", []):
            if not source.get("enabled", True):
                continue
            enabled.append(
                {
                    "province_code": province["province_code"],
                    "province_name": province["province_name"],
                    "slug": province["slug"],
                    "source": source,
                }
            )
    return enabled
