import re
from typing import List, Dict, Any


_VERB_HINTS = re.compile(
    r"\b(é|são|foi|foram|ser|estar|está|estão|tem|têm|há|deve|podem|pode|"
    r"is|are|was|were|has|have|shows|indicates|suggests|demonstrates)\b",
    re.IGNORECASE,
)

_REFERENCE_HEADING = re.compile(
    r"^(?:references|referências|bibliography)\s*:?$", re.IGNORECASE
)
_EDITORIAL_PREFIX = re.compile(
    r"^(?:received\b|accepted\b|published\b|date\s+of\s+publication\b|"
    r"date\s+of\s+current\s+version\b|copyright\b|©|ieee\b|acm\b|"
    r"doi\s*:|index\s+terms?\b|keywords?\b)",
    re.IGNORECASE,
)
_BARE_DOI = re.compile(r"^10\.\d{4,9}/\S+\s*$", re.IGNORECASE)
_TABLE_OR_FIGURE = re.compile(
    r"^(?:table\s+(?:\d+|[ivxlcdm]+)|fig(?:ure)?\.?\s*\d+)\b",
    re.IGNORECASE,
)
_KNOWN_SECTION_HEADING = re.compile(
    r"^(?:abstract|resumo|introduction|introdução|methods?|methodology|metodologia|"
    r"results?|resultados|discussion|discussão|conclusion|conclusão|acknowledg(?:e)?ments?|"
    r"agradecimentos)\s*:?$",
    re.IGNORECASE,
)


def _clean_markdown_line(line: str) -> str:
    text = line.strip()
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"[*_~]+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


def _is_mostly_symbols(text: str) -> bool:
    if not text:
        return False
    symbols = sum(1 for char in text if not char.isalnum() and not char.isspace())
    structural = sum(1 for char in text if char in "-:_|")
    visible_length = max(sum(1 for char in text if not char.isspace()), 1)
    return symbols / visible_length > 0.55 or structural / visible_length > 0.60


def _is_short_heading(line: str, cleaned: str) -> bool:
    if re.match(r"^\s{0,3}#{1,6}(?:\s+|$)", line):
        return True
    if _KNOWN_SECTION_HEADING.fullmatch(cleaned):
        return True
    words = re.findall(r"[A-Za-zÀ-ÿ]+", cleaned)
    if not words or len(words) > 5 or len(cleaned) > 60:
        return False
    if re.search(r"[.!?]$", cleaned) or _VERB_HINTS.search(cleaned):
        return False
    is_uppercase = any(char.isalpha() for char in cleaned) and cleaned.upper() == cleaned
    is_title_case = len(words) >= 2 and all(word[0].isupper() for word in words)
    return is_uppercase or is_title_case


def _is_non_analyzable_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return False
    cleaned = _clean_markdown_line(text)
    if "|" in text:
        return True
    if re.fullmatch(r"[\s\-:_|]+", text):
        return True
    if _is_mostly_symbols(text):
        return True
    if _EDITORIAL_PREFIX.match(cleaned):
        return True
    if _BARE_DOI.fullmatch(cleaned):
        return True
    if _TABLE_OR_FIGURE.match(cleaned):
        return True
    return _is_short_heading(text, cleaned)


def filter_analyzable_content(content: str) -> str:
    """Build an analysis-only copy while preserving original offsets and line breaks."""
    if not content:
        return content

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    filtered_lines = []
    inside_references = False
    for line in normalized.split("\n"):
        cleaned = _clean_markdown_line(line)
        if _REFERENCE_HEADING.fullmatch(cleaned):
            inside_references = True
        should_ignore = inside_references or _is_non_analyzable_line(line)
        filtered_lines.append(" " * len(line) if should_ignore else line)
    return "\n".join(filtered_lines)


def _should_skip_markdown_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return True
    cleaned = _clean_markdown_line(text)
    return not cleaned or _is_non_analyzable_line(text)


def split_sentences(markdown_content: str) -> List[Dict[str, Any]]:
    """
    Splits markdown content into paragraphs and sentences.
    Returns a list of dictionaries with text, paragraph_number, sentence_number, and position.
    """
    sentences = []
    if not markdown_content:
        return sentences

    normalized_content = filter_analyzable_content(markdown_content)
    paragraph_blocks = re.split(r"\n{2,}", normalized_content)
    paragraph_number = 0
    current_char_offset = 0

    for para in paragraph_blocks:
        original_para = para
        raw_lines = [line for line in para.split("\n") if line.strip()]
        use_joined_block = len(raw_lines) > 1
        lines = []
        for line in raw_lines:
            if use_joined_block:
                if _should_skip_markdown_line(line):
                    continue
                cleaned_line = _clean_markdown_line(line)
                if cleaned_line:
                    lines.append(cleaned_line)
            elif not _should_skip_markdown_line(line):
                lines.append(_clean_markdown_line(line))
        para = re.sub(r"\s+", " ", " ".join(lines)).strip()
        if not para:
            current_char_offset += len(original_para) + 2
            continue

        paragraph_number += 1
        para_stripped = para
        # Split sentences: punctuation (.!?), lookbehind, followed by spacing
        # Handles simple abbreviation exclusions by scanning common patterns
        raw_sentences = re.split(r'(?<!\bet)(?<!\bal)(?<!\beg)(?<!\bie)(?<=[.!?])\s+', para_stripped)
        
        sentence_number = 0
        para_offset = 0
        for sent in raw_sentences:
            sent_cleaned = sent.strip()
            if not sent_cleaned:
                continue

            if _should_skip_markdown_line(sent_cleaned):
                continue
            sent_cleaned = _clean_markdown_line(sent_cleaned)

            sentence_number += 1
            # Compute visual offset position in the document
            start_in_para = para.find(sent, para_offset)
            if start_in_para != -1:
                para_offset = start_in_para + len(sent)
                pos = float(current_char_offset + start_in_para)
            else:
                pos = float(current_char_offset + para_offset)

            sentences.append({
                "text": sent_cleaned,
                "paragraph_number": paragraph_number,
                "sentence_number": sentence_number,
                "position": pos
            })

        current_char_offset += len(original_para) + 2

    return sentences
