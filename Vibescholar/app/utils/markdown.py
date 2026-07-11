import re
from markdown_it import MarkdownIt

# Initialize the markdown-it-py parser
md_parser = MarkdownIt("commonmark")

def markdown_to_html(markdown_text: str) -> str:
    """
    Converts Markdown content to safe HTML for editor rendering.
    """
    if not markdown_text:
        return ""
    return md_parser.render(markdown_text)

def html_to_markdown(html_text: str) -> str:
    """
    Converts editor HTML content back to Markdown.
    """
    if not html_text:
        return ""
    
    # Standardize spaces
    text = html_text.strip()

    # Headers
    text = re.sub(r'<h1>(.*?)</h1>', r'# \1\n\n', text)
    text = re.sub(r'<h2>(.*?)</h2>', r'## \1\n\n', text)
    text = re.sub(r'<h3>(.*?)</h3>', r'### \1\n\n', text)
    
    # Lists
    text = re.sub(r'<li>(.*?)</li>', r'- \1\n', text)
    text = re.sub(r'</?(ul|ol)>', r'\n', text)

    # Paragraphs and linebreaks
    text = re.sub(r'<p>(.*?)</p>', r'\1\n\n', text)
    text = re.sub(r'<br\s*/?>', r'\n', text)

    # Inline styling (strong, em)
    text = re.sub(r'<(strong|b)>(.*?)</\1>', r'**\2**', text)
    text = re.sub(r'<(em|i)>(.*?)</\1>', r'*\2*', text)

    # Strip remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Clean double spaces/newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
