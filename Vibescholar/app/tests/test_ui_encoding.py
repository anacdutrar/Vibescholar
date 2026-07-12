from pathlib import Path


UI_ROOT = Path(__file__).resolve().parents[1] / "ui"
MOJIBAKE_PATTERNS = ("Ã", "Â", "�")


def test_ui_python_files_are_utf8_without_common_mojibake() -> None:
    findings: list[str] = []

    for path in sorted(UI_ROOT.rglob("*.py")):
        content = path.read_text(encoding="utf-8")
        for pattern in MOJIBAKE_PATTERNS:
            if pattern in content:
                findings.append(f"{path.relative_to(UI_ROOT)}: {pattern!r}")

    assert not findings, "Padrões comuns de mojibake encontrados: " + ", ".join(findings)
