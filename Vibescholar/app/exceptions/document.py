from fastapi import HTTPException, status

class DocumentNotFoundException(HTTPException):
    def __init__(self, doc_id: int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Documento com ID {doc_id} não encontrado."
        )

class ProjectNotFoundException(HTTPException):
    def __init__(self, project_id: int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Projeto com ID {project_id} não encontrado ou foi removido."
        )

class VersionNotFoundException(HTTPException):
    def __init__(self, version_id: int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Versão com ID {version_id} não encontrada."
        )
