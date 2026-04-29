from __future__ import annotations

from pathlib import Path


def xls_to_text(path: Path) -> str:
    try:
        import xlrd
    except ImportError:
        return ""

    lines: list[str] = []
    try:
        workbook = xlrd.open_workbook(str(path))
    except Exception:
        return ""

    for sheet in workbook.sheets():
        for row_index in range(sheet.nrows):
            row_values: list[str] = []
            for column_index in range(sheet.ncols):
                value = sheet.cell_value(row_index, column_index)
                text = _cell_to_text(value)
                if text:
                    row_values.append(text)
            if row_values:
                lines.append(" ".join(row_values))
    return "\n".join(lines).strip()


def _cell_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        # Keep integer-looking numbers compact; preserve decimals for price values.
        if value.is_integer():
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".")
    text = str(value).strip()
    if not text:
        return ""
    return text
