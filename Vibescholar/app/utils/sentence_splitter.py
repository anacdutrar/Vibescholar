import re
from typing import List, Dict, Any


_VERB_HINTS = re.compile(
    r"\b(é|são|foi|foram|ser|estar|está|estão|tem|têm|há|deve|podem|pode|"
    r"is|are|was|were|has|have|shows|indicates|suggests|demonstrates)\b",
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


def _should_skip_markdown_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return True
    if "|" in text and text.count("|") >= 2:
        return True
    if re.fullmatch(r"[\s\-|:]+", text):
        return True
    symbols = sum(1 for char in text if not char.isalnum() and not char.isspace())
    if symbols / max(len(text), 1) > 0.45:
        return True
    cleaned = _clean_markdown_line(text)
    if len(cleaned) <= 8:
        return True
    if not re.search(r"[.!?]$", cleaned) and not _VERB_HINTS.search(cleaned):
        return True
    return False


def split_sentences(markdown_content: str) -> List[Dict[str, Any]]:
    """
    Splits markdown content into paragraphs and sentences.
    Returns a list of dictionaries with text, paragraph_number, sentence_number, and position.
    """
    sentences = []
    if not markdown_content:
        return sentences

    normalized_content = markdown_content.replace("\r\n", "\n").replace("\r", "\n")
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
                if "|" in line and line.count("|") >= 2:
                    continue
                if re.fullmatch(r"[\s\-|:]+", line.strip()):
                    continue
                cleaned_line = _clean_markdown_line(line)
                if cleaned_line.endswith(":") and not re.search(r"[.!?]$", cleaned_line):
                    continue
                if len(cleaned_line) <= 8:
                    continue
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
