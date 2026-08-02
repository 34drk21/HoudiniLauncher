from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget


class ElideLabel(QLabel):
    """Single-line label that elides long text and exposes it in a tooltip."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._update_elision()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_elision()

    def _update_elision(self) -> None:
        width = max(1, self.contentsRect().width())
        QLabel.setText(
            self,
            self.fontMetrics().elidedText(
                self._full_text, Qt.TextElideMode.ElideRight, width
            ),
        )


def field_with_help(control: QWidget, help_text: str) -> QWidget:
    """Wrap a form control with a short inline Japanese help label."""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 4)
    layout.setSpacing(3)
    layout.addWidget(control)
    help_label = QLabel(help_text)
    help_label.setObjectName("FieldHelp")
    help_label.setWordWrap(True)
    layout.addWidget(help_label)
    return widget


def add_helped_row(
    form: QFormLayout, label: str, control: QWidget, help_text: str
) -> None:
    """Add a consistently styled explained field to a form."""
    form.addRow(label, field_with_help(control, help_text))
