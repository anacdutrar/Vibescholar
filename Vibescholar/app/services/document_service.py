import io
import re
import uuid
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.models.document import Document, DocumentVersion, Sentence
from app.models.reference import EvidenceSuggestion
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.reference_repository import ReferenceRepository
from app.services.import_service import ImportService
from app.services.export_service import ExportService
from app.services.quality_analyzer import QualityAnalyzer
from app.utils.sentence_splitter import split_sentences
from app.utils.text_normalizer import normalize_text
from app.schemas.request import DocumentCreate, DocumentContentUpdate, DocumentUpdate
from app.exceptions.document import DocumentNotFoundException, ProjectNotFoundException, VersionNotFoundException
from app.core.logging import logger


def _normalize_version_content(content: str) -> str:
    return re.sub(r"\s+", " ", content or "").strip()

class DocumentService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db
        self.doc_repo = DocumentRepository()

    def _verify_document_ownership(self, doc_id: int, user_id: int) -> Document:
        doc = self.doc_repo.get_by_id(self.db, doc_id)
        if not doc:
            raise DocumentNotFoundException(doc_id)
        project = ProjectRepository.get_by_id(self.db, doc.project_id)
        if not project or project.user_id != user_id:
            raise HTTPException(status_code=403, detail="Acesso não autorizado a este documento.")
        return doc

    def _verify_project_ownership(self, project_id: int, user_id: int):
        project = ProjectRepository.get_by_id(self.db, project_id)
        if not project or project.user_id != user_id:
            raise ProjectNotFoundException(project_id)
        return project

    def build_version_snapshot(self, doc_id: int, content: str, created_by: str) -> DocumentVersion:
        # Determine version number
        prev_version = self.doc_repo.get_latest_version(self.db, doc_id)
        next_ver_num = (prev_version.version_number + 1) if prev_version else 1

        # Extract and split new sentences
        new_raw_sentences = split_sentences(content)

        # Fetch previous sentences for equivalence matching
        prev_sentences = []
        if prev_version:
            prev_sentences = self.doc_repo.get_sentences_by_version(self.db, prev_version.id)
        
        # Map previous sentences: normalized_text -> sentence_uuid
        prev_uuid_map = {}
        for ps in prev_sentences:
            norm = normalize_text(ps.text)
            prev_uuid_map[norm] = ps.sentence_uuid

        # Create the new version record
        new_version = self.doc_repo.create_version(self.db, doc_id, content, created_by, next_ver_num)

        # Process new sentences and assign sentence_uuid
        db_sentences = []
        new_sentence_uuids = set()

        for item in new_raw_sentences:
            norm_new = normalize_text(item["text"])
            
            # Equivalence match check
            if norm_new in prev_uuid_map:
                sent_uuid = prev_uuid_map[norm_new]
            else:
                sent_uuid = str(uuid.uuid4())

            s = Sentence(
                document_version_id=new_version.id,
                sentence_uuid=sent_uuid,
                paragraph_number=item["paragraph_number"],
                sentence_number=item["sentence_number"],
                position=item["position"],
                text=item["text"],
                status="UNVERIFIED"
            )
            db_sentences.append(s)
            new_sentence_uuids.add(sent_uuid)

        self.doc_repo.bulk_create_sentences(self.db, db_sentences)

        # Propagation of approved suggestions
        if prev_version:
            prev_suggestions = ReferenceRepository.get_suggestions_by_version(self.db, prev_version.id)
            approved_prev_sugs = [s for s in prev_suggestions if s.status == "APPROVED"]
            
            new_suggestions = []
            for ap_sug in approved_prev_sugs:
                if ap_sug.sentence_uuid in new_sentence_uuids:
                    cloned_sug = EvidenceSuggestion(
                        document_version_id=new_version.id,
                        sentence_uuid=ap_sug.sentence_uuid,
                        reference_id=ap_sug.reference_id,
                        status="APPROVED"
                    )
                    new_suggestions.append(cloned_sug)

            if new_suggestions:
                ReferenceRepository.bulk_create_suggestions(self.db, new_suggestions)

        # Run Quality Analysis
        QualityAnalyzer.analyze_version(self.db, new_version.id)

        # Update current version reference
        self.doc_repo.update_version_id(self.db, doc_id, new_version.id)

        return new_version

    def create_document(self, project_id: int, doc_in: DocumentCreate, user_id: int, username: str) -> Document:
        self._verify_project_ownership(project_id, user_id)
        doc = self.doc_repo.create(self.db, project_id, doc_in)
        self.build_version_snapshot(doc.id, doc.content or "", username)
        return self.doc_repo.get_by_id(self.db, doc.id)

    def list_documents(self, project_id: int, user_id: int) -> List[Document]:
        self._verify_project_ownership(project_id, user_id)
        return self.doc_repo.list_by_project(self.db, project_id)

    def get_document(self, doc_id: int, user_id: int) -> Document:
        return self._verify_document_ownership(doc_id, user_id)

    def delete_document(self, doc_id: int, user_id: int) -> Document:
        doc = self._verify_document_ownership(doc_id, user_id)
        return self.doc_repo.soft_delete(self.db, doc)

    def autosave_content(self, doc_id: int, content: str, user_id: int) -> Document:
        self._verify_document_ownership(doc_id, user_id)
        return self.doc_repo.update_content(self.db, doc_id, content)

    def save_version(self, doc_id: int, user_id: int, username: str):
        doc = self._verify_document_ownership(doc_id, user_id)
        latest_version = self.doc_repo.get_latest_version(self.db, doc_id)
        if latest_version and _normalize_version_content(doc.content or "") == _normalize_version_content(latest_version.content_snapshot):
            logger.info(
                "document.version.skipped document_id=%s current_version_id=%s reason=identical_content",
                doc_id,
                latest_version.id,
            )
            return {
                "created": False,
                "message": "Nenhuma alteração desde a última versão.",
                "document_id": doc_id,
                "current_version_id": latest_version.id,
            }
        version = self.build_version_snapshot(doc_id, doc.content or "", username)
        logger.info(
            "document.version.created document_id=%s version_id=%s version_number=%s",
            doc_id,
            version.id,
            version.version_number,
        )
        return version

    def list_versions(self, doc_id: int, user_id: int) -> List[DocumentVersion]:
        self._verify_document_ownership(doc_id, user_id)
        return self.doc_repo.list_versions(self.db, doc_id)

    def restore_version(self, doc_id: int, version_id: int, user_id: int) -> dict:
        self._verify_document_ownership(doc_id, user_id)
        target_ver = self.doc_repo.get_version_by_id(self.db, version_id)
        if not target_ver or target_ver.document_id != doc_id:
            raise VersionNotFoundException(version_id)

        versions_before = self.doc_repo.count_versions(self.db, doc_id)
        updated_document = self.doc_repo.update_content(
            self.db, doc_id, target_ver.content_snapshot
        )
        versions_after = self.doc_repo.count_versions(self.db, doc_id)
        logger.info(
            "document.version.loaded_as_draft document_id=%s source_version_id=%s "
            "source_version_number=%s versions_before=%s versions_after=%s",
            doc_id,
            target_ver.id,
            target_ver.version_number,
            versions_before,
            versions_after,
        )
        return {
            "document_id": doc_id,
            "restored_from_version_id": target_ver.id,
            "restored_from_version_number": target_ver.version_number,
            "content": updated_document.content,
        }

    def import_document(self, project_id: int, title: str, filename: str, file_bytes: bytes, user_id: int, username: str) -> Document:
        self._verify_project_ownership(project_id, user_id)
        
        # Parse format using ImportService
        markdown_content = ImportService.import_document(filename, file_bytes)

        # Create document
        doc_create_schema = DocumentCreate(title=title, content=markdown_content)
        doc = self.doc_repo.create(self.db, project_id, doc_create_schema)

        # Build first version snapshot
        self.build_version_snapshot(doc.id, markdown_content, username)

        return self.doc_repo.get_by_id(self.db, doc.id)

    def export_document(self, doc_id: int, export_format: str, user_id: int) -> tuple:
        doc = self._verify_document_ownership(doc_id, user_id)
        content_text = doc.content or ""
        
        # Retrieve approved references
        approved_refs = []
        if doc.current_version_id:
            suggestions = ReferenceRepository.get_suggestions_by_version(self.db, doc.current_version_id)
            approved_sugs = [s for s in suggestions if s.status == "APPROVED"]
            approved_refs = [sug.reference for sug in approved_sugs]

        export_format = export_format.lower()
        
        if export_format in ["markdown", "md"]:
            result = ExportService.export_markdown(doc.title, content_text, approved_refs)
            return result, "text/markdown", f"export_{doc_id}.md"
            
        elif export_format == "docx":
            docx_bytes = ExportService.export_docx(doc.title, content_text, approved_refs)
            return docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"export_{doc_id}.docx"
            
        elif export_format == "pdf":
            pdf_bytes = ExportService.export_pdf(doc.title, content_text, approved_refs)
            return pdf_bytes, "application/pdf", f"export_{doc_id}.pdf"
            
        elif export_format == "bibtex":
            result = ExportService.export_bibtex(approved_refs)
            return result, "text/plain", f"export_{doc_id}.bib"
            
        elif export_format == "apa":
            result = ExportService.export_apa(approved_refs)
            return result, "text/plain", f"export_{doc_id}_apa.txt"
            
        elif export_format == "abnt":
            result = ExportService.export_abnt(approved_refs)
            return result, "text/plain", f"export_{doc_id}_abnt.txt"
            
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de exportação '{export_format}' não suportado. Escolha entre: md, docx, pdf, bibtex, apa, abnt."
            )
