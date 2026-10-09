"""State folder layout and atomic JSON writes.

Layout under <state_dir>/:
  documents/   one <safe-doc-id>.json per document record
  cache/       LLM response cache files
  feedback.jsonl  one JSON object per line
  reports/     saved report snapshots
  ledger.jsonl    one JSON object per LLM call
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, timezone
from pathlib import Path

from nova.mailbox import DocRecord


class StateDir:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    @property
    def documents_dir(self) -> Path:
        return self.root / "documents"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def feedback_file(self) -> Path:
        return self.root / "feedback.jsonl"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def ledger_file(self) -> Path:
        return self.root / "ledger.jsonl"

    @property
    def facts_dir(self) -> Path:
        return self.root / "facts"

    def ensure(self) -> None:
        for d in (self.root, self.documents_dir, self.cache_dir, self.reports_dir, self.facts_dir):
            d.mkdir(parents=True, exist_ok=True)

    def _doc_path(self, doc_id: str) -> Path:
        safe = doc_id.replace("/", "__").replace("#", "--")
        return self.documents_dir / f"{safe}.json"

    def write_json(self, path: Path, data: dict) -> None:
        """Atomic write via temp-file rename."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=1)
                f.write("\n")
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def save_doc(self, record: DocRecord) -> None:
        self.write_json(self._doc_path(record.doc_id), record.to_dict())

    def doc_exists(self, doc_id: str) -> bool:
        return self._doc_path(doc_id).is_file()

    def _facts_path(self, doc_id: str) -> Path:
        safe = doc_id.replace("/", "__").replace("#", "--")
        return self.facts_dir / f"{safe}.json"

    def facts_exist(self, doc_id: str) -> bool:
        return self._facts_path(doc_id).is_file()

    def save_facts(self, doc_id: str, type_: str, data: dict, received_at: str) -> None:
        self.facts_dir.mkdir(parents=True, exist_ok=True)
        self.write_json(self._facts_path(doc_id), {
            "type": type_, "doc": doc_id, "data": data, "received_at": received_at,
        })

    def load_all_facts(self, as_of: date | None = None) -> list[dict]:
        records: list[dict] = []
        if not self.facts_dir.exists():
            return records
        for f in sorted(self.facts_dir.glob("*.json")):
            try:
                entry = json.loads(f.read_text())
            except Exception:
                continue
            if as_of is not None and entry.get("received_at"):
                try:
                    from datetime import timezone
                    rec_date = date.fromisoformat(entry["received_at"][:10])
                    if rec_date > as_of:
                        continue
                except (ValueError, KeyError):
                    pass
            records.append(entry)
        return records

    def load_docs(self, as_of: date | None = None) -> list[DocRecord]:
        """Load all saved document records, optionally filtered to received <= as_of."""
        records: list[DocRecord] = []
        if not self.documents_dir.exists():
            return records
        for f in sorted(self.documents_dir.glob("*.json")):
            try:
                rec = DocRecord.from_dict(json.loads(f.read_text()))
            except Exception:
                continue
            if as_of is not None:
                rec_date = rec.received.astimezone(timezone.utc).date()
                if rec_date > as_of:
                    continue
            records.append(rec)
        return records

    def append_ledger(self, entry: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def append_feedback(self, item: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.feedback_file, "a") as f:
            f.write(json.dumps(item) + "\n")

    def read_json(self, path: Path) -> dict | None:
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return None
