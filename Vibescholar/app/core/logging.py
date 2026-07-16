import logging
import os

# Resolve log file relative to project root (handles any user)
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
log_file_path = os.path.join(_project_root, "vibescholar.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file_path, encoding="utf-8")
    ]
)

logger = logging.getLogger("vibescholar")
logger.setLevel(logging.INFO)
llm_logger = logging.getLogger("vibescholar.ai.llm")
llm_logger.setLevel(logging.INFO)


def configure_llm_diagnostic_logging(enabled: bool) -> None:
    """Enable only the dedicated LLM diagnostic logger at DEBUG level."""
    llm_logger.setLevel(logging.DEBUG if enabled else logging.INFO)
