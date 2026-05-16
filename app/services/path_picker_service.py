from __future__ import annotations

from pathlib import Path
import platform
import subprocess


class PathPickerError(RuntimeError):
    pass


class PathPickerService:
    def pick_directory(self, *, title: str, initial_path: str | None = None) -> str:
        if platform.system() == "Darwin":
            try:
                return self._pick_directory_macos(title=title, initial_path=initial_path)
            except PathPickerError:
                pass

        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:  # noqa: BLE001
            raise PathPickerError("当前环境不支持系统目录弹窗，请改用手填路径或预设路径。") from exc

        root = None
        try:
            root = tk.Tk()
            root.withdraw()
            root.update()
            selected = filedialog.askdirectory(
                title=title,
                initialdir=str(Path(initial_path).expanduser()) if initial_path else None,
                mustexist=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise PathPickerError(f"打开系统目录弹窗失败，请改用手填路径或预设路径。原始错误: {exc}") from exc
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

        if not selected:
            raise PathPickerError("已取消目录选择")
        return str(Path(selected).expanduser().resolve())

    def _pick_directory_macos(self, *, title: str, initial_path: str | None = None) -> str:
        script = [
            "set chosenFolder to choose folder with prompt "
            + self._osascript_string(title)
            + (f" default location POSIX file {self._osascript_string(initial_path)}" if initial_path else ""),
            "POSIX path of chosenFolder",
        ]
        try:
            completed = subprocess.run(
                ["osascript", "-e", script[0], "-e", script[1]],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise PathPickerError(f"打开系统目录弹窗失败，请改用手填路径或预设路径。原始错误: {exc}") from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            if "User canceled" in stderr or "(-128)" in stderr:
                raise PathPickerError("已取消目录选择")
            raise PathPickerError(f"打开系统目录弹窗失败，请改用手填路径或预设路径。原始错误: {stderr or 'unknown error'}")

        selected = (completed.stdout or "").strip()
        if not selected:
            raise PathPickerError("已取消目录选择")
        return str(Path(selected).expanduser().resolve())

    @staticmethod
    def _osascript_string(value: str | None) -> str:
        escaped = (value or "").replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
