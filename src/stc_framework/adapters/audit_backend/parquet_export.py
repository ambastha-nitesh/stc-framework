"""Daily parquet export job for JSONL audit files.

Requires ``[parquet]`` extra. If ``pyarrow`` is missing, this module raises
on import so callers can fall back gracefully.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_jsonl_to_parquet(source_dir: str | Path, output_dir: str | Path) -> Path:
    """Convert every ``audit-*.jsonl`` in ``source_dir`` to parquet.

    Returns the path of the written parquet file.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional
        raise ImportError(
            "pyarrow is not installed; `pip install stc-framework[parquet]`"
        ) from exc

    src = Path(source_dir)
    dst = Path(output_dir)
    dst.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for path in sorted(src.glob("audit-*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

    if not records:
        return dst

    table = pa.Table.from_pylist(records)
    out = dst / f"audit-{Path().stem}-{len(records)}.parquet"
    pq.write_table(table, out)
    return out
