"""Dump every document in a mailbox to out/text/<mailbox>/... as plain text.

Usage:
    python scripts/dump_text.py data/scenarios
    python scripts/dump_text.py data/exam

Each .eml becomes out/text/<mailbox>/batch_NN/NNNN.eml.txt
Each attachment becomes out/text/<mailbox>/batch_NN/NNNN.eml#<filename>.txt
One text file per document page, separated by '--- page N ---' markers.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from grader.extract import attachments, pages_of, pdf_is_image_only


def dump_mailbox(mailbox_dir: Path, out_root: Path) -> None:
    mailbox_dir = Path(mailbox_dir)
    rel_name = mailbox_dir.relative_to(ROOT)
    out_base = out_root / str(rel_name).replace("/", "_").replace("\\", "_")
    out_base.mkdir(parents=True, exist_ok=True)

    for eml_path in sorted(mailbox_dir.rglob("*.eml")):
        rel = eml_path.relative_to(mailbox_dir)
        data = eml_path.read_bytes()

        # dump the email itself
        _write_doc(data, "eml", out_base / (str(rel) + ".txt"), eml_path)

        # dump each attachment
        for name, att_data in attachments(data):
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            out_path = out_base / (str(rel) + "#" + name + ".txt")
            _write_doc(att_data, ext, out_path, eml_path / name)


def _write_doc(data: bytes, ext: str, out_path: Path, src) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        pages = pages_of(data, ext)
        is_scan = ext == "pdf" and pdf_is_image_only(data)
        lines = []
        for i, page in enumerate(pages, 1):
            lines.append(f"--- page {i} ---")
            if is_scan:
                lines.append("[image-only scan — no text layer]")
            else:
                lines.append(page)
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  wrote {out_path.relative_to(ROOT)}")
    except Exception as e:
        out_path.write_text(f"ERROR: {e}\n", encoding="utf-8")
        print(f"  ERROR {src}: {e}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/dump_text.py <mailbox_dir> [<mailbox_dir> ...]")
        sys.exit(1)
    out_root = ROOT / "out" / "text"
    out_root.mkdir(parents=True, exist_ok=True)
    for arg in sys.argv[1:]:
        mbox = Path(arg)
        if not mbox.is_absolute():
            mbox = ROOT / mbox
        print(f"dumping {mbox} ...")
        dump_mailbox(mbox, out_root)
    print("done.")
