from fastapi import HTTPException, status

class ReferenceNotFoundException(HTTPException):
    def __init__(self, ref_id: int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Referência bibliográfica com ID {ref_id} não encontrada."
        )

class SuggestionNotFoundException(HTTPException):
    def __init__(self, suggestion_id: int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sugestão de evidência com ID {suggestion_id} não encontrada."
        )
