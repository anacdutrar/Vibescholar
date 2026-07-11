import re
from typing import List, Dict, Any

def split_sentences(markdown_content: str) -> List[Dict[str, Any]]:
    """
    Splits markdown content into paragraphs and sentences.
    Returns a list of dictionaries with text, paragraph_number, sentence_number, and position.
    """
    sentences = []
    if not markdown_content:
        return sentences

    # Split into paragraphs by newline
    paragraphs = markdown_content.split('\n')
    paragraph_number = 0
    current_char_offset = 0

    for para in paragraphs:
        para_stripped = para.strip()
        if not para_stripped:
            current_char_offset += len(para) + 1  # Add newline byte length
            continue

        paragraph_number += 1
        # Split sentences: punctuation (.!?), lookbehind, followed by spacing
        # Handles simple abbreviation exclusions by scanning common patterns
        raw_sentences = re.split(r'(?<!\bet)(?<!\bal)(?<!\beg)(?<!\bie)(?<=[.!?])\s+', para_stripped)
        
        sentence_number = 0
        para_offset = 0
        for sent in raw_sentences:
            sent_cleaned = sent.strip()
            if not sent_cleaned:
                continue

            # Skip header tags (e.g. # Header) or very short lines
            if sent_cleaned.startswith('#') or len(sent_cleaned) <= 8:
                continue

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

        current_char_offset += len(para) + 1

    return sentences
