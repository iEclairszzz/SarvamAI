import io
import re
from pathlib import Path
from typing import Dict, Optional
import pypdf
import trafilatura

MAX_INPUT_CHARS = 20000

class InputTooLargeError(ValueError):
    """Raised when extracted input text exceeds character limit."""
    pass

class ExtractionError(ValueError):
    """Raised when text cannot be extracted from a source."""
    pass

def _check_char_limit(text: str) -> None:
    if len(text) > MAX_INPUT_CHARS:
        raise InputTooLargeError(
            f"Input exceeds the MVP limit of {MAX_INPUT_CHARS:,} characters "
            f"(received {len(text):,} characters). Please trim your text or upload a shorter document."
        )

def extract_from_text(text: str, title: Optional[str] = None) -> Dict[str, str]:
    """Extract and validate pasted plain/markdown text."""
    trimmed = text.strip() if text else ""
    if not trimmed:
        raise ExtractionError("No text provided.")
    _check_char_limit(trimmed)

    # Derive fallback title from first line if not provided
    if not title:
        first_line = trimmed.split("\n")[0][:60].strip()
        title = first_line if first_line else "Narrated Text"

    return {"title": title, "text": trimmed}

def extract_from_file(filename: str, content: bytes) -> Dict[str, str]:
    """Extract text from uploaded .txt, .md, or .pdf file."""
    if not content:
        raise ExtractionError("Uploaded file is empty.")

    suffix = Path(filename).suffix.lower()
    base_title = Path(filename).stem

    if suffix in [".txt", ".md"]:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except Exception as e:
                raise ExtractionError(f"Could not decode text file: {e}")
    elif suffix == ".pdf":
        try:
            reader = pypdf.PdfReader(io.BytesIO(content))
            pages_text = []
            for idx, page in enumerate(reader.pages):
                extracted = page.extract_text()
                if extracted:
                    pages_text.append(extracted)
            text = "\n\n".join(pages_text)
        except Exception as e:
            raise ExtractionError(f"Failed to read PDF document: {e}")
    else:
        raise ExtractionError(f"Unsupported file format: {suffix}. Supported formats: .txt, .md, .pdf")

    text = text.strip()
    if not text:
        raise ExtractionError(f"No readable text could be extracted from '{filename}'.")

    _check_char_limit(text)
    return {"title": base_title, "text": text}

def extract_from_url(url: str) -> Dict[str, str]:
    """Fetch URL and extract main article text and title using trafilatura."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ExtractionError("URL must begin with http:// or https://")

    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception as e:
        raise ExtractionError(f"Failed to fetch URL: {e}")

    if not downloaded:
        raise ExtractionError(f"Could not download content from URL: {url}")

    extracted_text = trafilatura.extract(
        downloaded,
        output_format="txt",
        include_comments=False,
        include_tables=False,
    )

    if not extracted_text or not extracted_text.strip():
        raise ExtractionError("Could not extract readable article text from the URL.")

    title = "Web Article"
    metadata = trafilatura.extract_metadata(downloaded)
    if metadata and metadata.title:
        title = metadata.title.strip()

    text = extracted_text.strip()
    _check_char_limit(text)

    return {"title": title, "text": text}
