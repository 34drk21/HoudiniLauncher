from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply a bundled theme and the launcher typography defaults."""
    if theme == "system":
        app.setStyleSheet("")
    else:
        style_path = (
            Path(__file__).resolve().parents[1]
            / "resources"
            / "styles"
            / f"{theme}.qss"
        )
        app.setStyleSheet(
            style_path.read_text(encoding="utf-8") if style_path.is_file() else ""
        )
    font = QFont("Segoe UI Variable", 10)
    if not font.exactMatch():
        font.setFamily("Segoe UI")
    font.setWeight(QFont.Weight.Medium)
    app.setFont(font)
