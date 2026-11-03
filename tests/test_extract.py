import pytest
from app.extract import (
    extract_from_text,
    extract_from_file,
    MAX_INPUT_CHARS,
    InputTooLargeError,
    ExtractionError,
)

def test_extract_from_text():
    res = extract_from_text("This is test text.\nSecond line.")
    assert res["title"] == "This is test text."
    assert "Second line." in res["text"]

def test_extract_from_text_empty():
    with pytest.raises(ExtractionError):
        extract_from_text("   ")

def test_extract_from_text_too_large():
    huge_text = "A" * (MAX_INPUT_CHARS + 1)
    with pytest.raises(InputTooLargeError) as exc_info:
        extract_from_text(huge_text)
    assert "20,000" in str(exc_info.value)

def test_extract_from_file_txt():
    content = b"Sample article content from text file."
    res = extract_from_file("my_article.txt", content)
    assert res["title"] == "my_article"
    assert res["text"] == "Sample article content from text file."

def test_extract_from_file_md():
    content = b"# Heading\n\nMarkdown paragraph."
    res = extract_from_file("notes.md", content)
    assert res["title"] == "notes"
    assert "Markdown paragraph." in res["text"]

def test_extract_from_file_unsupported():
    with pytest.raises(ExtractionError):
        extract_from_file("data.exe", b"binarydata")
