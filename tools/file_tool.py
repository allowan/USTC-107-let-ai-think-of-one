"""Workspace-scoped file reading and writing tools.

The public ``file_tool`` object can be passed directly to a LangChain agent.  The
underlying :class:`WorkspaceFiles` class is dependency-free and can also be used
from ordinary Python code or tests.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

try:
    from langchain.tools import tool
except ImportError:  # Keep the dependency-free core usable before project setup.
    def tool(function):  # type: ignore[no-redef]
        return function


Action = Literal["read", "write", "append"]
DEFAULT_MAX_READ_BYTES = 1_000_000


class WorkspaceFileError(ValueError):
    """Raised when a requested file operation is invalid or unsafe."""


class WorkspaceFiles:
    """Read and write text files underneath one workspace directory."""

    def __init__(self, workspace: str | os.PathLike[str], max_read_bytes: int = DEFAULT_MAX_READ_BYTES):
        self.workspace = Path(workspace).expanduser().resolve()
        if not self.workspace.is_dir():
            raise WorkspaceFileError(f"Workspace does not exist or is not a directory: {self.workspace}")
        if max_read_bytes <= 0:
            raise WorkspaceFileError("max_read_bytes must be greater than zero")
        self.max_read_bytes = max_read_bytes

    def _resolve(self, path: str) -> Path:
        if not path or not path.strip():
            raise WorkspaceFileError("path cannot be empty")

        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        candidate = candidate.resolve(strict=False)

        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise WorkspaceFileError(f"Path is outside the workspace: {path}") from exc
        if candidate == self.workspace:
            raise WorkspaceFileError("path must refer to a file, not the workspace directory")
        return candidate

    def read(self, path: str) -> str:
        """Read a UTF-8 text file from the workspace."""
        target = self._resolve(path)
        if not target.exists():
            raise WorkspaceFileError(f"File does not exist: {path}")
        if not target.is_file():
            raise WorkspaceFileError(f"Path is not a file: {path}")
        size = target.stat().st_size
        if size > self.max_read_bytes:
            raise WorkspaceFileError(
                f"File is too large to read ({size} bytes; limit is {self.max_read_bytes} bytes)"
            )
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceFileError(f"File is not valid UTF-8 text: {path}") from exc
        except OSError as exc:
            raise WorkspaceFileError(f"Could not read {path}: {exc}") from exc

    def write(self, path: str, content: str) -> str:
        """Atomically overwrite a UTF-8 text file, creating parent folders."""
        target = self._resolve(path)
        if target.exists() and not target.is_file():
            raise WorkspaceFileError(f"Path is not a file: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)

        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary_name = temporary.name
            os.replace(temporary_name, target)
        except OSError as exc:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
            raise WorkspaceFileError(f"Could not write {path}: {exc}") from exc
        return f"Wrote {len(content.encode('utf-8'))} bytes to {self._display_path(target)}"

    def append(self, path: str, content: str) -> str:
        """Append UTF-8 text to a file, creating it and its parent folders."""
        target = self._resolve(path)
        if target.exists() and not target.is_file():
            raise WorkspaceFileError(f"Path is not a file: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("a", encoding="utf-8") as file:
                file.write(content)
        except OSError as exc:
            raise WorkspaceFileError(f"Could not append to {path}: {exc}") from exc
        return f"Appended {len(content.encode('utf-8'))} bytes to {self._display_path(target)}"

    def run(self, action: Action, path: str, content: str | None = None) -> str:
        """Perform a file operation and return content or a concise status."""
        if action == "read":
            if content is not None:
                raise WorkspaceFileError("content must be omitted when action is 'read'")
            return self.read(path)
        if action in {"write", "append"}:
            if content is None:
                raise WorkspaceFileError(f"content is required when action is '{action}'")
            return self.write(path, content) if action == "write" else self.append(path, content)
        raise WorkspaceFileError(f"Unsupported action: {action}")

    def _display_path(self, path: Path) -> str:
        return path.relative_to(self.workspace).as_posix()


def _default_workspace() -> Path:
    configured = os.environ.get("WORKSPACE_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[1]


workspace_files = WorkspaceFiles(_default_workspace())


@tool
def file_tool(action: Action, path: str, content: str | None = None) -> str:
    """Read or write UTF-8 text files within the workspace.

    Use action ``read`` to return a file's contents. Use ``write`` to replace a
    file atomically, or ``append`` to add text. ``content`` is required for
    write/append and must be omitted for read. Paths may be workspace-relative
    or absolute paths inside the workspace; paths outside it are rejected.
    """
    try:
        return workspace_files.run(action, path, content)
    except WorkspaceFileError as exc:
        return f"File operation failed: {exc}"


__all__ = ["WorkspaceFileError", "WorkspaceFiles", "file_tool", "workspace_files"]
