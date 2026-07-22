import fitz
import os
import camelot
import pandas as pd
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter


# ---------------------------------------------------------------------------
# doc_type derivation
# ---------------------------------------------------------------------------

_DOC_TYPE_KEYWORDS = {
    "hostel":   ["hostel", "residence", "dormitory"],
    "academic": ["academic", "regulation", "exam", "grade", "credit"],
    "conduct":  ["conduct", "disciplin", "code"],
    "staff":    ["cabin", "staff", "faculty"],
}


def _derive_doc_type(filename: str) -> str:
    """Best-effort doc_type from the filename.  Falls back to 'general'."""
    lower = filename.lower()
    for doc_type, keywords in _DOC_TYPE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return doc_type
    return "general"


# ---------------------------------------------------------------------------
# section_name extraction (best-effort, PyMuPDF font-size heuristic)
# ---------------------------------------------------------------------------

def _extract_page_sections(page) -> list[str]:
    """
    Scans a PyMuPDF page and returns a list of likely section headings —
    spans whose font size is >= 1.3× the median font size of the page.
    Returns [] if no headings are detected (never raises).
    """
    try:
        blocks = page.get_text("dict")["blocks"]
        sizes = []
        for block in blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sizes.append(span["size"])
        if not sizes:
            return []

        sizes_sorted = sorted(sizes)
        median = sizes_sorted[len(sizes_sorted) // 2]
        threshold = median * 1.3

        headings = []
        seen = set()
        for block in blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["size"] >= threshold:
                        text = span["text"].strip()
                        if text and text not in seen:
                            headings.append(text)
                            seen.add(text)
        return headings
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Core splitter (shared config so chunk sizes are consistent)
# ---------------------------------------------------------------------------

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=64,
    # Empty string ("") as final fallback so the splitter can always split
    separators=["\n\n", "\n", ".", " ", ""],
)


# ---------------------------------------------------------------------------
# Single-file processor (called by both batch and incremental paths)
# ---------------------------------------------------------------------------

def process_single_pdf(file_path: str) -> list[dict]:
    """
    Extracts structured chunks from a single PDF.

    Each chunk dict has the fields that match the Weaviate schema:
      - text_chunk   (TEXT)   — clean content, no [Page X] prefix
      - source_file  (TEXT)   — filename only (no path)
      - page_number  (INT)    — 1-indexed
      - doc_type     (TEXT)   — derived from filename
      - section_name (TEXT)   — best-effort heading, or None
    """
    file_path = str(file_path)
    filename  = Path(file_path).name
    doc_type  = _derive_doc_type(filename)
    chunks    = []

    print(f"\n--- Processing file: {filename} ---")

    try:
        # ----------------------------------------------------------------
        # Step 1: Extract tables (Camelot lattice) and record their bboxes
        # ----------------------------------------------------------------
        tables = camelot.read_pdf(file_path, pages="all", flavor="lattice")
        table_locations: dict[int, list] = {}

        print(f"  Found {tables.n} table(s). Extracting to Markdown...")
        for table in tables:
            page_no = int(table.page)
            table_locations.setdefault(page_no, []).append(table._bbox)

            df = table.df.replace(r"\n", " ", regex=True)
            if df.empty:
                continue
            df.columns = [str(c) for c in df.iloc[0]]
            df = df[1:].reset_index(drop=True)

            # Chunk large tables into ≤15-row segments to stay within
            # embedding model context limits (~512 tokens).
            chunk_size_rows = 15
            for i in range(0, len(df), chunk_size_rows):
                df_chunk = df.iloc[i : i + chunk_size_rows]
                md = df_chunk.to_markdown(index=False)
                chunks.append({
                    "text_chunk":   f"The following table appears on page {page_no}:\n\n{md}",
                    "source_file":  filename,
                    "page_number":  page_no,
                    "doc_type":     doc_type,
                    "section_name": None,  # tables rarely have a unique heading
                })

        # ----------------------------------------------------------------
        # Step 2: Extract non-table text, redacting table areas first
        # ----------------------------------------------------------------
        doc = fitz.open(file_path)
        for page_num, page in enumerate(doc, 1):
            # Blank out table regions so we don't double-ingest that text
            for bbox in table_locations.get(page_num, []):
                page.add_redact_annot(fitz.Rect(bbox), fill=(1, 1, 1))
            page.apply_redactions()

            text = page.get_text()
            if len(text.strip().split()) <= 15:
                continue  # skip near-empty pages

            # Best-effort section heading for the page
            headings = _extract_page_sections(page)
            section_name = headings[0] if headings else None

            for chunk_text in _SPLITTER.split_text(text):
                chunk_text = chunk_text.strip()
                if not chunk_text:
                    continue
                chunks.append({
                    "text_chunk":   chunk_text,
                    "source_file":  filename,
                    "page_number":  page_num,
                    "doc_type":     doc_type,
                    "section_name": section_name,
                })
        doc.close()

    except Exception as e:
        print(f"❌ Error processing {filename}: {e}")

    print(f"  → {len(chunks)} chunk(s) extracted.")
    return chunks


# ---------------------------------------------------------------------------
# Batch directory processor (used for full re-ingestion)
# ---------------------------------------------------------------------------

def process_pdfs_in_directory(directory_path: str) -> list[dict]:
    """
    Processes all PDFs in a directory and returns all chunk dicts.
    Use process_single_pdf() for incremental (file-by-file) processing.
    """
    all_chunks = []
    pdf_dir = Path(directory_path)

    if not pdf_dir.is_dir():
        print(f"❌ Directory '{directory_path}' not found.")
        return []

    for pdf_file in sorted(pdf_dir.glob("*.pdf")):
        all_chunks.extend(process_single_pdf(str(pdf_file)))

    print(f"\n✅ Total chunks extracted from all files: {len(all_chunks)}")
    return all_chunks
