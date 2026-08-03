from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter


def generate_icon(source: Path, path: Path) -> None:
    """Create the Windows icon from the checked-in Launcher brand image."""
    image = QImage(str(source))
    if image.isNull():
        raise RuntimeError(f"Cannot read Launcher icon source: {source}")
    side = min(image.width(), image.height())
    image = image.copy(
        (image.width() - side) // 2,
        (image.height() - side) // 2,
        side,
        side,
    ).scaled(
        256,
        256,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path), "ICO"):
        raise RuntimeError("Qt could not write the Windows ICO file")


def generate_task_placeholder(source: Path, path: Path) -> None:
    """Create a wide Task placeholder while preserving the logo proportions."""
    source_image = QImage(str(source))
    if source_image.isNull():
        raise RuntimeError(f"Cannot read Launcher icon source: {source}")
    side = min(source_image.width(), source_image.height())
    square = source_image.copy(
        (source_image.width() - side) // 2,
        (source_image.height() - side) // 2,
        side,
        side,
    )
    logo = square.copy(
        int(side * 0.13),
        int(side * 0.18),
        int(side * 0.76),
        int(side * 0.64),
    ).scaled(
        820,
        650,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QImage(1280, 720, QImage.Format.Format_RGB32)
    canvas.fill(square.pixelColor(side // 2, side // 10))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawImage(
        (canvas.width() - logo.width()) // 2,
        (canvas.height() - logo.height()) // 2,
        logo,
    )
    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(path), "JPG", 92):
        raise RuntimeError("Qt could not write the Task placeholder image")


def generate_version_file(path: Path, version: str) -> None:
    parts = [int(value) for value in version.split(".")]
    if len(parts) != 3:
        raise ValueError("Version must use major.minor.patch")
    numeric = (*parts, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# UTF-8\n"
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={numeric}, prodvers={numeric}, "
        "mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[StringFileInfo([StringTable('040904B0', [\n"
        "    StringStruct('CompanyName', 'HouD2'),\n"
        "    StringStruct('FileDescription', 'HouD2Launcher'),\n"
        f"    StringStruct('FileVersion', '{version}'),\n"
        "    StringStruct('InternalName', 'HouD2Launcher'),\n"
        "    StringStruct('OriginalFilename', 'HouD2Launcher.exe'),\n"
        "    StringStruct('ProductName', 'HouD2Launcher'),\n"
        f"    StringStruct('ProductVersion', '{version}')\n"
        "  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n",
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) != 6:
        raise SystemExit(
            "Usage: generate_windows_assets.py SOURCE_IMAGE ICON TASK_PLACEHOLDER "
            "VERSION_FILE VERSION"
        )
    app = QGuiApplication.instance() or QGuiApplication([])
    generate_icon(Path(sys.argv[1]), Path(sys.argv[2]))
    generate_task_placeholder(Path(sys.argv[1]), Path(sys.argv[3]))
    generate_version_file(Path(sys.argv[4]), sys.argv[5])
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
