import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "chunks.jsonl"


@dataclass
class Chunk:
    chunk_id: str
    text: str  # the text that will be embedded
    metadata: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def load_records(path: Optional[Path] = None) -> Iterator[dict]:
    path = Path(path) if path else DATA_PATH
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON at line {line_no}: {e}") from e


# --------------------------------------------------------------------------
# Helper
# --------------------------------------------------------------------------


def build_metadata(record: dict) -> dict:

    meta = record.get("metadata", {}) or {}

    return {
        "type": (meta.get("type") or "").strip(),
        "page": meta.get("page", -1),
        "source": meta.get("source", ""),
    }


# --------------------------------------------------------------------------
# Main API
# --------------------------------------------------------------------------
def chunk_record(record: dict, index: int) -> Optional[Chunk]:
    text = (record.get("text") or "").strip()
    if not text:
        return None

    metadata = build_metadata(record)
    base_id = f"chunk_{index}"

    return Chunk(chunk_id=base_id, text=text, metadata=metadata)


def load_and_chunk(path: Optional[Path] = None) -> List[Chunk]:
    """Load the JSONL file and return a flat list of chunks."""
    chunks: List[Chunk] = []
    for index, record in enumerate(load_records(path)):
        chunk = chunk_record(record, index)
        if chunk:
            chunks.append(chunk)
    return chunks


if __name__ == "__main__":
    all_chunks = load_and_chunk()
    print(len(all_chunks))
    print(f"Total chunks: {len(all_chunks)}")
    if all_chunks:
        first = all_chunks[2]
        print("\n--- first chunk ---")
        print("id      :", first.chunk_id)
        print("text    :", first.text)
        print("metadata:", first.metadata)
