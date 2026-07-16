import logging
from sqlalchemy.orm import Session
from app.core.database import Base, engine, SessionLocal
from app.core.security import hash_password
from app.models.user import User, Project
from app.models.project_settings import ProjectSettings
from app.models.document import Document, DocumentVersion, Sentence, GroundingReport, QualityIssue
from app.models.reference import ProjectReference, EvidenceSuggestion
from datetime import datetime

logger = logging.getLogger("vibescholar.db")

def init_db(db: Session = None):
    # Ensure tables are created
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        # Check if admin user already exists
        admin = db.query(User).filter(User.username == "admin").first()
        if admin:
            logger.info("Database already seeded. Skipping seeder.")
            return

        logger.info("Seeding database...")
        
        # 1. Create Admin User
        admin_user = User(
            username="admin",
            password_hash=hash_password("admin123"),
            email="admin@vibescholar.org"
        )
        db.add(admin_user)
        db.flush()  # Generates admin_user.id
        
        # 2. Create Sample Project
        sample_project = Project(
            user_id=admin_user.id,
            name="Projeto Exemplo - Visão Computacional",
            description="Projeto de pesquisa sobre detecção de objetos utilizando redes neurais profundas."
        )
        db.add(sample_project)
        db.flush()  # Generates sample_project.id
        
        # 3. Create Project Settings
        project_settings = ProjectSettings(
            project_id=sample_project.id,
            preferred_language="pt",
            minimum_qualis="B1",
            publication_year_min=2015,
            publication_year_max=2026,
            preferred_sources="Google Scholar, Crossref",
            only_open_access=False,
            prefer_doi=True,
            max_suggestions=5
        )
        db.add(project_settings)

        # 4. Create Sample Document
        doc_content = (
            "Redes neurais convolucionais apresentam excelentes resultados para detecção de objetos. "
            "YOLO é uma das abordagens mais populares na literatura acadêmica recente. "
            "Métodos de RAG podem auxiliar pesquisadores na fundamentação de suas afirmações científicas."
        )
        sample_doc = Document(
            project_id=sample_project.id,
            title="Introdução à Detecção de Objetos com Deep Learning",
            description="Primeiro rascunho de fundamentação teórica.",
            content=doc_content,
            grounding_score=0.0
        )
        db.add(sample_doc)
        db.flush()  # Generates sample_doc.id

        # 5. Create First Version Snapshot
        first_version = DocumentVersion(
            document_id=sample_doc.id,
            version_number=1,
            content_snapshot=doc_content,
            created_by="system"
        )
        db.add(first_version)
        db.flush()  # Generates first_version.id

        # Point document to its active version
        sample_doc.current_version_id = first_version.id
        db.add(sample_doc)

        # 6. Add Sentences for Version 1
        sentences_data = [
            ("Redes neurais convolucionais apresentam excelentes resultados para detecção de objetos.", 1, 1, 10.0),
            ("YOLO é uma das abordagens mais populares na literatura acadêmica recente.", 1, 2, 20.0),
            ("Métodos de RAG podem auxiliar pesquisadores na fundamentação de suas afirmações científicas.", 1, 3, 30.0)
        ]

        import hashlib
        for text, para_num, sent_num, pos in sentences_data:
            # Deterministic uuid using md5 hash of lowercase trimmed text
            normalized_text = text.lower().strip().replace(".", "").replace("!", "").replace("?", "")
            sentence_uuid = hashlib.md5(normalized_text.encode("utf-8")).hexdigest()
            
            s = Sentence(
                document_version_id=first_version.id,
                sentence_uuid=sentence_uuid,
                paragraph_number=para_num,
                sentence_number=sent_num,
                position=pos,
                text=text,
                status="UNVERIFIED"
            )
            db.add(s)

        # 7. Create Grounding Report
        report = GroundingReport(
            document_id=sample_doc.id,
            supported_count=0,
            unsupported_count=3,
            partial_count=0,
            outdated_count=0,
            contradictions_count=0
        )
        db.add(report)

        # 8. Create standard lack of evidence Quality Issues for each unverified sentence
        for text, para_num, sent_num, pos in sentences_data:
            normalized_text = text.lower().strip().replace(".", "").replace("!", "").replace("?", "")
            sentence_uuid = hashlib.md5(normalized_text.encode("utf-8")).hexdigest()
            
            issue = QualityIssue(
                document_id=sample_doc.id,
                document_version_id=first_version.id,
                sentence_uuid=sentence_uuid,
                issue_type="LACK_OF_EVIDENCE",
                description=f"A frase '{text}' não possui referências científicas associadas nesta versão.",
                severity=2.0
            )
            db.add(issue)

        db.commit()
        logger.info("Database seed successfully completed!")
        
    except Exception as e:
        db.rollback()
        logger.exception("Error during database seed!")
        raise
    finally:
        if close_session:
            db.close()

if __name__ == "__main__":
    init_db()
