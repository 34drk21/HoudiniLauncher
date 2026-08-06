from __future__ import annotations

from pathlib import Path
import pytest

from houd2launcher.core.trash import send_to_trash


def test_send_to_trash_moves_folder_to_recycle_bin(tmp_path: Path) -> None:
    folder = tmp_path / "trash_target"
    folder.mkdir()
    (folder / "data.txt").write_text("sample content")

    send_to_trash(folder)

    assert not folder.exists()


def test_send_to_trash_raises_file_not_found_on_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "non_existent"
    with pytest.raises(FileNotFoundError):
        send_to_trash(missing)
