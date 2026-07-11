import json
import csv
import io
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pybtex.database import parse_string

from app.core.database import get_db
from app.models.reference import ProjectReference
from app.repositories.reference_repository import ReferenceRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.request import ReferenceCreate
from app.exceptions.reference import ReferenceNotFoundException
from app.exceptions.document import ProjectNotFoundException

class ReferenceService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    def _verify_project_ownership(self, project_id: Optional[int], user_id: int):
        if project_id is not None:
            project = ProjectRepository.get_by_id(self.db, project_id)
            if not project or project.user_id != user_id:
                raise ProjectNotFoundException(project_id)
            return project
        return None

    def _verify_reference_ownership(self, reference_id: int, user_id: int) -> ProjectReference:
        ref = ReferenceRepository.get_by_id(self.db, reference_id)
        if not ref:
            raise ReferenceNotFoundException(reference_id)
        if ref.project_id is not None:
            self._verify_project_ownership(ref.project_id, user_id)
        return ref

    def list_references(self, project_id: Optional[int], user_id: int) -> List[ProjectReference]:
        self._verify_project_ownership(project_id, user_id)
        return ReferenceRepository.list_by_project(self.db, project_id)

    def create_reference(self, project_id: int, ref_in: ReferenceCreate, user_id: int) -> ProjectReference:
        self._verify_project_ownership(project_id, user_id)
        return ReferenceRepository.create(self.db, ref_in, project_id)

    def update_reference(self, reference_id: int, ref_in: ReferenceCreate, user_id: int) -> ProjectReference:
        ref = self._verify_reference_ownership(reference_id, user_id)
        return ReferenceRepository.update(self.db, ref, ref_in)

    def delete_reference(self, reference_id: int, user_id: int) -> ProjectReference:
        ref = self._verify_reference_ownership(reference_id, user_id)
        return ReferenceRepository.soft_delete(self.db, ref)

    def import_references(self, project_id: int, filename: str, file_content: bytes, user_id: int) -> List[ProjectReference]:
        self._verify_project_ownership(project_id, user_id)
        
        filename = filename.lower()
        imported_refs = []
        
        try:
            if filename.endswith(".bib"):
                bib_text = file_content.decode("utf-8", errors="replace")
                bib_data = parse_string(bib_text, "bibtex")
                
                for key, entry in bib_data.entries.items():
                    title = entry.fields.get("title", "Sem Título")
                    authors_list = []
                    for author in entry.persons.get("author", []):
                        authors_list.append(str(author))
                    authors = " & ".join(authors_list) if authors_list else "Autor Desconhecido"
                    
                    journal = entry.fields.get("journal", entry.fields.get("booktitle", None))
                    year_str = entry.fields.get("year", None)
                    year = int(year_str) if (year_str and year_str.isdigit()) else None
                    doi = entry.fields.get("doi", None)
                    qualis_score = entry.fields.get("qualis", "C")
                    abstract = entry.fields.get("abstract", None)
                    availability = entry.fields.get("availability", "FECHADO").upper()

                    ref_schema = ReferenceCreate(
                        title=title,
                        authors=authors,
                        journal=journal,
                        year=year,
                        doi=doi,
                        qualis_score=qualis_score,
                        abstract=abstract,
                        availability=availability if availability in ["ABERTO", "FECHADO"] else "FECHADO"
                    )
                    db_ref = ReferenceRepository.create(self.db, ref_schema, project_id)
                    imported_refs.append(db_ref)

            elif filename.endswith(".csv"):
                csv_text = file_content.decode("utf-8", errors="replace")
                csv_file = io.StringIO(csv_text)
                reader = csv.DictReader(csv_file)
                for row in reader:
                    title = row.get("title", "Sem Título")
                    authors = row.get("authors", "Autor Desconhecido")
                    journal = row.get("journal", None)
                    year_str = row.get("year", None)
                    year = int(year_str) if (year_str and year_str.isdigit()) else None
                    doi = row.get("doi", None)
                    qualis_score = row.get("qualis", "C")
                    abstract = row.get("abstract", None)
                    availability = row.get("availability", "FECHADO").upper()

                    ref_schema = ReferenceCreate(
                        title=title,
                        authors=authors,
                        journal=journal,
                        year=year,
                        doi=doi,
                        qualis_score=qualis_score,
                        abstract=abstract,
                        availability=availability if availability in ["ABERTO", "FECHADO"] else "FECHADO"
                    )
                    db_ref = ReferenceRepository.create(self.db, ref_schema, project_id)
                    imported_refs.append(db_ref)

            elif filename.endswith(".json"):
                json_data = json.loads(file_content.decode("utf-8", errors="replace"))
                if not isinstance(json_data, list):
                    json_data = [json_data]
                    
                for item in json_data:
                    title = item.get("title", "Sem Título")
                    authors = item.get("authors", "Autor Desconhecido")
                    journal = item.get("journal", None)
                    year = item.get("year", None)
                    doi = item.get("doi", None)
                    qualis_score = item.get("qualis", "C")
                    abstract = item.get("abstract", None)
                    availability = item.get("availability", "FECHADO").upper()

                    ref_schema = ReferenceCreate(
                        title=title,
                        authors=authors,
                        journal=journal,
                        year=year,
                        doi=doi,
                        qualis_score=qualis_score,
                        abstract=abstract,
                        availability=availability if availability in ["ABERTO", "FECHADO"] else "FECHADO"
                    )
                    db_ref = ReferenceRepository.create(self.db, ref_schema, project_id)
                    imported_refs.append(db_ref)
            else:
                raise HTTPException(status_code=400, detail="Formato de arquivo não suportado. Envie .bib, .csv ou .json")

        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Erro ao processar arquivo de importação bibliográfica: {str(e)}"
            )

        return imported_refs
