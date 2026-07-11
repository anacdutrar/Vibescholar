import re

def normalize_text(text: str) -> str:
    """
    Normalizes text for sentence equivalence matching.
    Converts to lowercase, removes punctuation and standardizes whitespaces.
    """
    if not text:
        return ""
    # Lowercase & strip
    normalized = text.lower().strip()
    # Remove standard punctuation
    normalized = re.sub(r'[.,!?;:()\[\]"\'“”\-—_+*#/\\~`^&|<>=$%@]', '', normalized)
    # Standardize whitespace
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized
