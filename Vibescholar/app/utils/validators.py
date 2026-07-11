import re

def validate_doi(doi: str) -> bool:
    """
    Validates Digital Object Identifier (DOI) format.
    Example valid: 10.1109/CVPR.2016.90
    """
    if not doi:
        return False
    pattern = r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$"
    return bool(re.match(pattern, doi))

def validate_email(email: str) -> bool:
    """
    Validates simple email pattern.
    """
    if not email:
        return False
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return bool(re.match(pattern, email))
