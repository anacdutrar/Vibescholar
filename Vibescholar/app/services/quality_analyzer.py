from sqlalchemy.orm import Session
from app.repositories.document_repository import DocumentRepository
from app.repositories.reference_repository import ReferenceRepository
from app.repositories.project_settings_repository import ProjectSettingsRepository
from app.models.document import GroundingReport, QualityIssue
from app.core.logging import logger

class QualityAnalyzer:
    @staticmethod
    def analyze_version(db: Session, version_id: int) -> float:
        """
        Analyzes a document version:
        1. Evaluates evidence suggestions to update sentence statuses (UNVERIFIED, SUPPORTED, OUTDATED).
        2. Calculates grounding counts and report score.
        3. Cleans and regenerates QualityIssues.
        4. Persists the GroundingReport and updates the Document grounding_score cache.
        """
        logger.info(f"Starting quality analysis for version_id={version_id}")

        # Fetch version and document context
        doc_repo = DocumentRepository()
        version = doc_repo.get_version_by_id(db, version_id)
        if not version:
            logger.error(f"Version {version_id} not found.")
            return 0.0

        doc = doc_repo.get_by_id(db, version.document_id)
        if not doc:
            logger.error(f"Document associated with version {version_id} not found.")
            return 0.0

        # Fetch project settings
        settings_repo = ProjectSettingsRepository()
        settings = settings_repo.get_by_project_id(db, doc.project_id)

        # Fetch sentences and suggestions for this version
        sentences = doc_repo.get_sentences_by_version(db, version_id)
        suggestions = ReferenceRepository.get_suggestions_by_version(db, version_id)

        # Index suggestions by sentence_uuid for quick lookups
        suggestions_by_uuid = {}
        for sug in suggestions:
            suggestions_by_uuid.setdefault(sug.sentence_uuid, []).append(sug)

        supported_count = 0
        unsupported_count = 0
        outdated_count = 0
        partial_count = 0
        contradictions_count = 0

        # Quality issue collector
        new_issues = []

        for sentence in sentences:
            sentence_sugs = suggestions_by_uuid.get(sentence.sentence_uuid, [])
            approved_sugs = [s for s in sentence_sugs if s.status == "APPROVED"]

            if not approved_sugs:
                # 1. No approved evidence suggestions
                sentence.status = "UNVERIFIED"
                unsupported_count += 1
                
                # Create lack of evidence issue
                issue = QualityIssue(
                    document_id=doc.id,
                    document_version_id=version_id,
                    sentence_uuid=sentence.sentence_uuid,
                    issue_type="LACK_OF_EVIDENCE",
                    description=f"A frase '{sentence.text[:60]}...' não possui nenhuma citação científica aprovada nesta versão.",
                    severity=2.0
                )
                new_issues.append(issue)
            else:
                # 2. Approved suggestions exist. Check for outdated references.
                has_valid_ref = False
                has_outdated_ref = False
                
                for sug in approved_sugs:
                    ref = sug.reference
                    # Check against settings publication_year_min
                    if settings and settings.publication_year_min is not None:
                        if ref.year and ref.year < settings.publication_year_min:
                            has_outdated_ref = True
                            continue
                    has_valid_ref = True

                if has_valid_ref:
                    sentence.status = "SUPPORTED"
                    supported_count += 1
                elif has_outdated_ref:
                    sentence.status = "OUTDATED"
                    outdated_count += 1
                    
                    # Create outdated issue
                    issue = QualityIssue(
                        document_id=doc.id,
                        document_version_id=version_id,
                        sentence_uuid=sentence.sentence_uuid,
                        issue_type="OUTDATED",
                        description=f"A frase '{sentence.text[:60]}...' é apoiada apenas por fontes anteriores ao ano limite ({settings.publication_year_min}).",
                        severity=1.0
                    )
                    new_issues.append(issue)
                else:
                    sentence.status = "UNVERIFIED"
                    unsupported_count += 1

        # Calculate score (supported sentences / total sentences)
        total_sentences = len(sentences)
        score = (supported_count / total_sentences) if total_sentences > 0 else 1.0

        # Save sentence status changes
        db.commit()

        # Clean old quality issues for this version
        doc_repo.delete_issues_by_version(db, version_id)
        
        # Save new quality issues
        if new_issues:
            doc_repo.bulk_create_issues(db, new_issues)

        # Create Grounding Report
        report = GroundingReport(
            document_id=doc.id,
            supported_count=supported_count,
            unsupported_count=unsupported_count,
            partial_count=partial_count,
            outdated_count=outdated_count,
            contradictions_count=contradictions_count
        )
        doc_repo.create_report(db, report)

        # Update cache on Document
        doc_repo.update_grounding_score(db, doc.id, score)

        logger.info(f"Analysis completed: score={score:.2f}, supported={supported_count}, unsupported={unsupported_count}, outdated={outdated_count}")
        return score
