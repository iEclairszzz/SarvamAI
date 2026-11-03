import re
from dataclasses import dataclass
from typing import List, Tuple

TTS_MAX_CHARS = 2000
TRANSLATE_MAX_CHARS = 900

# Regex for sentence boundaries: . ? ! and Devanagari danda । (U+0964) and ॥ (U+0965)
# Followed by optional quote/bracket and whitespace or end of string
SENTENCE_SPLIT_REGEX = re.compile(r'([.?!।॥][\'"”’\)]?)(?:\s+|\Z)')

def clean_text(text: str) -> str:
    """
    Clean text for narration:
    - Strips code blocks and inline code
    - Strips markdown syntax (links, images, headers, emphasis, blockquotes)
    - Strips raw URLs
    - Normalizes excessive whitespace while preserving paragraph breaks
    """
    if not text:
        return ""

    # Remove code blocks ```...```
    text = re.sub(r"```[\s\S]*?```", "", text)

    # Remove inline code `...`
    text = re.sub(r"`[^`\n]*`", "", text)

    # Remove images ![alt](url)
    text = re.sub(r"!\[[^\]]*\]\([^\)]+\)", "", text)

    # Convert links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)

    # Remove markdown headers (# Title)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Remove blockquote markers (> Quote)
    text = re.sub(r"^\s*>\s*", "", text, flags=re.MULTILINE)

    # Remove list bullet markers (* item, - item)
    text = re.sub(r"^\s*[\*\-\+]\s+", "", text, flags=re.MULTILINE)

    # Remove emphasis (*text*, **text**, _text_, __text__, ~~text~~)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Split into paragraphs by 2 or more newlines
    raw_paras = [p.strip() for p in re.split(r"\n\s*\n+", text)]
    cleaned_paras = []
    for p in raw_paras:
        # Collapse single newlines within a paragraph into spaces
        single_line = re.sub(r"\s+", " ", p).strip()
        if single_line:
            cleaned_paras.append(single_line)

    return "\n\n".join(cleaned_paras)


def split_into_sentences(text: str) -> List[str]:
    """
    Split text into sentences using ., ?, !, and Devanagari danda (।, ॥).
    Preserves punctuation at the end of each sentence.
    """
    text = text.strip()
    if not text:
        return []

    tokens = []
    last_idx = 0
    for match in SENTENCE_SPLIT_REGEX.finditer(text):
        punct_end = match.end(1)
        sentence = text[last_idx:punct_end].strip()
        if sentence:
            tokens.append(sentence)
        last_idx = match.end()

    # Trailing part without ending punctuation
    trailing = text[last_idx:].strip()
    if trailing:
        tokens.append(trailing)

    return tokens


def _split_long_sentence(sentence: str, max_chars: int) -> List[str]:
    """
    Subdivide an oversized sentence by commas, then spaces, then character length.
    """
    if len(sentence) <= max_chars:
        return [sentence]

    # Try splitting at comma
    comma_parts = re.split(r'(,[\'"”’\)]?)\s+', sentence)
    if len(comma_parts) > 1:
        # Re-attach commas to previous tokens
        rebuilt = []
        i = 0
        while i < len(comma_parts):
            if i + 1 < len(comma_parts) and re.match(r'^,[\'"”’\)]?$', comma_parts[i + 1]):
                rebuilt.append((comma_parts[i] + comma_parts[i + 1]).strip())
                i += 2
            else:
                p = comma_parts[i].strip()
                if p:
                    rebuilt.append(p)
                i += 1

        chunks = []
        current = ""
        all_fit = True
        for part in rebuilt:
            if len(part) > max_chars:
                all_fit = False
                break
            if not current:
                current = part
            elif len(current) + 1 + len(part) <= max_chars:
                current = f"{current} {part}"
            else:
                chunks.append(current)
                current = part
        if current:
            chunks.append(current)
        if all_fit and chunks:
            return chunks

    # Fallback: split at words / spaces
    words = sentence.split(" ")
    chunks = []
    current = ""
    for w in words:
        if not w:
            continue
        if len(w) > max_chars:
            # Word itself exceeds limit: hard split
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(w), max_chars):
                chunks.append(w[i:i + max_chars])
        elif not current:
            current = w
        elif len(current) + 1 + len(w) <= max_chars:
            current = f"{current} {w}"
        else:
            chunks.append(current)
            current = w
    if current:
        chunks.append(current)

    return chunks


@dataclass
class TextChunk:
    text: str
    is_paragraph_end: bool = False


def chunk_text_for_tts(text: str, max_chars: int = TTS_MAX_CHARS) -> List[TextChunk]:
    """
    Pack text into chunks for TTS with paragraph boundary tracking.
    Each chunk is <= max_chars.
    is_paragraph_end is True on the final chunk of each paragraph.
    """
    cleaned = clean_text(text)
    if not cleaned:
        return []

    paragraphs = cleaned.split("\n\n")
    all_chunks: List[TextChunk] = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        raw_sentences = split_into_sentences(para)
        sentences: List[str] = []
        for s in raw_sentences:
            if len(s) > max_chars:
                sentences.extend(_split_long_sentence(s, max_chars))
            else:
                sentences.append(s)

        current_chunk = ""
        para_chunks: List[str] = []

        for s in sentences:
            if not current_chunk:
                current_chunk = s
            elif len(current_chunk) + 1 + len(s) <= max_chars:
                current_chunk = f"{current_chunk} {s}"
            else:
                para_chunks.append(current_chunk)
                current_chunk = s

        if current_chunk:
            para_chunks.append(current_chunk)

        # Mark only the last chunk of the paragraph as paragraph_end
        for i, c_text in enumerate(para_chunks):
            is_end = (i == len(para_chunks) - 1)
            all_chunks.append(TextChunk(text=c_text, is_paragraph_end=is_end))

    return all_chunks


def chunk_text_for_translation(text: str, max_chars: int = TRANSLATE_MAX_CHARS) -> List[str]:
    """
    Pack text into chunks <= max_chars for translation (e.g. Mayura:v1 max 1000).
    Never splits mid-sentence unless a single sentence exceeds max_chars.
    """
    cleaned = clean_text(text)
    if not cleaned:
        return []

    raw_sentences = split_into_sentences(cleaned)
    sentences: List[str] = []
    for s in raw_sentences:
        if len(s) > max_chars:
            sentences.extend(_split_long_sentence(s, max_chars))
        else:
            sentences.append(s)

    chunks: List[str] = []
    current_chunk = ""

    for s in sentences:
        if not current_chunk:
            current_chunk = s
        elif len(current_chunk) + 1 + len(s) <= max_chars:
            current_chunk = f"{current_chunk} {s}"
        else:
            chunks.append(current_chunk)
            current_chunk = s

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
