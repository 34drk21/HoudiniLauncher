from __future__ import annotations

from pathlib import Path
import pytest

import inspect

import houd2launcher.core.trash as trash_module
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


def test_send_to_trash_uses_uuid_fallback_without_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(_path: str) -> None:
        raise OSError("network drive has no recycle bin")

    monkeypatch.setattr(trash_module, "native_send2trash", unavailable)
    first = tmp_path / "same_name"
    first.mkdir()
    result_one = send_to_trash(first)
    second = tmp_path / "same_name"
    second.mkdir()
    result_two = send_to_trash(second)

    assert result_one.method == "fallback"
    assert result_one.recovery_path and result_one.recovery_path.is_dir()
    assert result_two.recovery_path and result_two.recovery_path.is_dir()
    assert result_one.recovery_path != result_two.recovery_path
    source = inspect.getsource(trash_module)
    assert "subprocess" not in source
    assert "powershell" not in source.casefold()
