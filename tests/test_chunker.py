import pytest
from app.chunker import (
    clean_text,
    split_into_sentences,
    chunk_text_for_tts,
    chunk_text_for_translation,
    TTS_MAX_CHARS,
    TRANSLATE_MAX_CHARS,
)

def test_clean_text_markdown_and_urls():
    md = """
    # Big Heading

    Here is a paragraph with **bold text**, *italic*, and `inline code`.
    Visit https://example.com for more info.
    Also check [Sarvam Docs](https://docs.sarvam.ai).

    ```python
    def code():
        print("hidden code")
    ```

    > A famous quote.
    """
    cleaned = clean_text(md)
    assert "#" not in cleaned
    assert "```" not in cleaned
    assert "hidden code" not in cleaned
    assert "inline code" not in cleaned
    assert "https://" not in cleaned
    assert "Sarvam Docs" in cleaned
    assert "**" not in cleaned
    assert ">" not in cleaned
    assert "Here is a paragraph with bold text, italic, and" in cleaned

def test_split_into_sentences_english():
    text = "Hello world! How are you? I am doing great. Thanks for asking."
    sentences = split_into_sentences(text)
    assert len(sentences) == 4
    assert sentences[0] == "Hello world!"
    assert sentences[1] == "How are you?"
    assert sentences[2] == "I am doing great."
    assert sentences[3] == "Thanks for asking."

def test_split_into_sentences_hindi():
    text = "सर्वम एआई भारत की प्रमुख भाषा एआई कंपनी है। यह कई भारतीय भाषाओं का समर्थन करती है! क्या आपने इसे आजमाया? बिल्कुल॥"
    sentences = split_into_sentences(text)
    assert len(sentences) == 4
    assert sentences[0] == "सर्वम एआई भारत की प्रमुख भाषा एआई कंपनी है।"
    assert sentences[1] == "यह कई भारतीय भाषाओं का समर्थन करती है!"
    assert sentences[2] == "क्या आपने इसे आजमाया?"
    assert sentences[3] == "बिल्कुल॥"

def test_chunk_text_for_tts_limits():
    # Long text with 20 sentences
    long_sent = "यह एक बहुत महत्वपूर्ण वाक्य है जो बार-बार दोहराया जा रहा है।"
    text = " ".join([f"{long_sent} ({i})" for i in range(100)])
    chunks = chunk_text_for_tts(text, max_chars=500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 500

def test_oversized_sentence_fallback():
    # A single sentence with no punctuation but commas and spaces that exceeds limit
    long_sentence = ", ".join([f"clause_{i}" for i in range(50)]) + "."
    assert len(long_sentence) > 200
    chunks = chunk_text_for_tts(long_sentence, max_chars=100)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 100

def test_paragraph_boundaries():
    text = "Paragraph one sentence one. Paragraph one sentence two.\n\nParagraph two sentence one."
    chunks = chunk_text_for_tts(text, max_chars=1000)
    assert len(chunks) == 2
    assert chunks[0].is_paragraph_end is True
    assert chunks[1].is_paragraph_end is True

def test_chunk_text_for_translation():
    text = "Sentence one. Sentence two? Sentence three! Sentence four."
    chunks = chunk_text_for_translation(text, max_chars=35)
    for c in chunks:
        assert len(c) <= 35
