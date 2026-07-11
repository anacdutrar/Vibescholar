import docx
import io
from fastapi import UploadFile, HTTPException

class ImportService:
    @staticmethod
    def import_docx(file_bytes: bytes) -> str:
        """
        Converts DOCX binary data into a clean Markdown string.
        """
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = []
            for p in doc.paragraphs:
                # Basic conversion to preserve formatting hints
                text = p.text.strip()
                if not text:
                    continue
                
                # Check for headings in paragraph styles
                style = p.style.name.lower()
                if "heading 1" in style:
                    paragraphs.append(f"# {text}")
                elif "heading 2" in style:
                    paragraphs.append(f"## {text}")
                elif "heading 3" in style:
                    paragraphs.append(f"### {text}")
                else:
                    paragraphs.append(text)
            
            return "\n\n".join(paragraphs)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro ao processar arquivo DOCX: {str(e)}")

    @staticmethod
    def import_markdown(file_bytes: bytes) -> str:
        """
        Parses Markdown binary data to string.
        """
        try:
            return file_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro ao decodificar Markdown: {str(e)}")

    @staticmethod
    def import_txt(file_bytes: bytes) -> str:
        """
        Parses raw TXT data to string.
        """
        try:
            return file_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro ao decodificar arquivo de texto: {str(e)}")

    @classmethod
    def import_document(cls, filename: str, content: bytes) -> str:
        ext = filename.split(".")[-1].lower()
        if ext == "docx":
            return cls.import_docx(content)
        elif ext in ["md", "markdown"]:
            return cls.import_markdown(content)
        elif ext in ["txt", "text"]:
            return cls.import_txt(content)
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Formato de arquivo .{ext} não suportado. Formatos aceitos: .docx, .md, .txt"
            )
