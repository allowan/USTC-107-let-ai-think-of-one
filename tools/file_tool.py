"""Workspace-scoped file reading and writing tools.

The public ``file_tool`` object can be passed directly to a LangChain agent.  The
underlying :class:`WorkspaceFiles` class is dependency-free and can also be used
from ordinary Python code or tests.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Literal

try:
    from langchain.tools import tool
except ImportError:  # Allow core file operations to work before dependencies are installed.
    def tool(function):  # type: ignore[no-redef]
        return function

Action = Literal["read", "write", "append", "mkdir", "delete"]
DEFAULT_MAX_READ_BYTES = 1_000_000
DEFAULT_LARGE_READ_BYTES = 100_000
MAX_LARGE_READ_BYTES = 500_000
DEFAULT_MAX_RESULTS = 100
IGNORED_DIRECTORIES = {".git", ".venv", "node_modules", "__pycache__"}


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

    def _resolve(self, path: str, allow_workspace: bool = False) -> Path:
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
        if candidate == self.workspace and not allow_workspace:
            raise WorkspaceFileError("path must refer to a file, not the workspace directory")
        return candidate

    def list_dir(self, path: str = ".", recursive: bool = False, max_entries: int = DEFAULT_MAX_RESULTS) -> str:
        """List files and directories beneath a workspace directory."""
        if max_entries <= 0:
            raise WorkspaceFileError("max_entries must be greater than zero")
        target = self._resolve(path, allow_workspace=True)
        if not target.exists():
            raise WorkspaceFileError(f"Directory does not exist: {path}")
        if not target.is_dir():
            raise WorkspaceFileError(f"Path is not a directory: {path}")

        entries: list[str] = []
        iterator = target.rglob("*") if recursive else target.iterdir()
        try:
            for entry in iterator:
                relative_parts = entry.relative_to(target).parts
                if any(part in IGNORED_DIRECTORIES for part in relative_parts):
                    continue
                suffix = "/" if entry.is_dir() else ""
                entries.append(f"{entry.relative_to(self.workspace).as_posix()}{suffix}")
                if len(entries) >= max_entries:
                    entries.append(f"... truncated after {max_entries} entries")
                    break
        except OSError as exc:
            raise WorkspaceFileError(f"Could not list directory {path}: {exc}") from exc
        return "\n".join(sorted(entries)) if entries else "(empty directory)"

    def search_file(
        self,
        query: str,
        path: str = ".",
        file_pattern: str = "*",
        use_regex: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> str:
        """Search matching lines in UTF-8 workspace files."""
        if not query:
            raise WorkspaceFileError("query cannot be empty")
        if max_results <= 0:
            raise WorkspaceFileError("max_results must be greater than zero")
        target = self._resolve(path, allow_workspace=True)
        if not target.exists():
            raise WorkspaceFileError(f"Path does not exist: {path}")

        try:
            matcher = re.compile(query) if use_regex else None
        except re.error as exc:
            raise WorkspaceFileError(f"Invalid regular expression: {exc}") from exc

        candidates = [target] if target.is_file() else target.rglob(file_pattern)
        matches: list[str] = []
        try:
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                relative_parts = candidate.relative_to(self.workspace).parts
                if any(part in IGNORED_DIRECTORIES for part in relative_parts):
                    continue
                if target.is_file() and not candidate.match(file_pattern):
                    continue
                if candidate.stat().st_size > self.max_read_bytes:
                    continue
                try:
                    with candidate.open(encoding="utf-8") as file:
                        for line_number, line in enumerate(file, start=1):
                            found = bool(matcher.search(line)) if matcher else query in line
                            if found:
                                relative = candidate.relative_to(self.workspace).as_posix()
                                matches.append(f"{relative}:{line_number}:{line.rstrip()}")
                                if len(matches) >= max_results:
                                    matches.append(f"... truncated after {max_results} matches")
                                    return "\n".join(matches)
                except UnicodeDecodeError:
                    continue
        except OSError as exc:
            raise WorkspaceFileError(f"Could not search {path}: {exc}") from exc
        return "\n".join(matches) if matches else "No matches found"

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

    def read_large_file(
        self,
        path: str,
        offset: int = 0,
        max_bytes: int = DEFAULT_LARGE_READ_BYTES,
    ) -> str:
        """Read one byte range from a large UTF-8 text file."""
        if offset < 0:
            raise WorkspaceFileError("offset cannot be negative")
        if max_bytes <= 0 or max_bytes > MAX_LARGE_READ_BYTES:
            raise WorkspaceFileError(
                f"max_bytes must be between 1 and {MAX_LARGE_READ_BYTES}"
            )
        target = self._resolve(path)
        if not target.exists():
            raise WorkspaceFileError(f"File does not exist: {path}")
        if not target.is_file():
            raise WorkspaceFileError(f"Path is not a file: {path}")
        total = target.stat().st_size
        if offset > total:
            raise WorkspaceFileError(f"offset {offset} is beyond file size {total}")
        try:
            with target.open("rb") as file:
                file.seek(offset)
                raw = file.read(max_bytes)
        except OSError as exc:
            raise WorkspaceFileError(f"Could not read {path}: {exc}") from exc
        if b"\x00" in raw:
            raise WorkspaceFileError(f"File appears to be binary: {path}")
        end = offset + len(raw)
        next_offset = str(end) if end < total else "EOF"
        text = raw.decode("utf-8", errors="replace")
        header = f"[bytes {offset}:{end} of {total}; next_offset={next_offset}]"
        return f"{header}\n{text}"

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

    def mkdir(self, path: str) -> str:
        """Create a directory and any missing parent directories."""
        target = self._resolve(path)
        if target.exists() and not target.is_dir():
            raise WorkspaceFileError(f"Path exists and is not a directory: {path}")
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceFileError(f"Could not create directory {path}: {exc}") from exc
        return f"Created directory {self._display_path(target)}"

    def delete(self, path: str) -> str:
        """Delete a file or an empty directory without recursive removal."""
        target = self._resolve(path)
        if not target.exists():
            raise WorkspaceFileError(f"Path does not exist: {path}")
        try:
            if target.is_dir():
                target.rmdir()
                kind = "directory"
            else:
                target.unlink()
                kind = "file"
        except OSError as exc:
            raise WorkspaceFileError(
                f"Could not delete {path}; directories must be empty: {exc}"
            ) from exc
        return f"Deleted {kind} {self._display_path(target)}"

    def copy(self, source: str, destination: str) -> str:
        """Copy a file or directory without overwriting an existing path."""
        source_path = self._resolve(source)
        destination_path = self._resolve(destination)
        if not source_path.exists():
            raise WorkspaceFileError(f"Source does not exist: {source}")
        if destination_path.exists():
            raise WorkspaceFileError(f"Destination already exists: {destination}")
        if source_path == destination_path:
            raise WorkspaceFileError("Source and destination must be different")
        if source_path.is_dir():
            try:
                destination_path.relative_to(source_path)
            except ValueError:
                pass
            else:
                raise WorkspaceFileError("Cannot copy a directory into itself")
        try:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            if source_path.is_dir():
                shutil.copytree(source_path, destination_path)
                kind = "directory"
            else:
                shutil.copy2(source_path, destination_path)
                kind = "file"
        except OSError as exc:
            raise WorkspaceFileError(
                f"Could not copy {source} to {destination}: {exc}"
            ) from exc
        return f"Copied {kind} {self._display_path(source_path)} to {self._display_path(destination_path)}"

    def move(self, source: str, destination: str) -> str:
        """Move a file or directory without overwriting an existing path."""
        source_path = self._resolve(source)
        destination_path = self._resolve(destination)
        if not source_path.exists():
            raise WorkspaceFileError(f"Source does not exist: {source}")
        if destination_path.exists():
            raise WorkspaceFileError(f"Destination already exists: {destination}")
        if source_path == destination_path:
            raise WorkspaceFileError("Source and destination must be different")
        if source_path.is_dir():
            try:
                destination_path.relative_to(source_path)
            except ValueError:
                pass
            else:
                raise WorkspaceFileError("Cannot move a directory into itself")
        kind = "directory" if source_path.is_dir() else "file"
        try:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(destination_path))
        except OSError as exc:
            raise WorkspaceFileError(
                f"Could not move {source} to {destination}: {exc}"
            ) from exc
        return f"Moved {kind} {source} to {self._display_path(destination_path)}"

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
        if action in {"mkdir", "delete"}:
            if content is not None:
                raise WorkspaceFileError(f"content must be omitted when action is '{action}'")
            return self.mkdir(path) if action == "mkdir" else self.delete(path)
        raise WorkspaceFileError(f"Unsupported action: {action}")

    def _display_path(self, path: Path) -> str:
        return path.relative_to(self.workspace).as_posix()


def _default_workspace() -> Path:
    configured = os.environ.get("WORKSPACE_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[1]


workspace_files = WorkspaceFiles(_default_workspace())


def _failure(error: WorkspaceFileError) -> str:
    return f"File operation failed: {error}"


@tool
def read_file(path: str) -> str:
    """Read a UTF-8 text file located inside the workspace."""
    try:
        return workspace_files.read(path)
    except WorkspaceFileError as exc:
        return _failure(exc)


@tool
def read_large_file(
    path: str,
    offset: int = 0,
    max_bytes: int = DEFAULT_LARGE_READ_BYTES,
) -> str:
    """Read a large text file in chunks; use returned next_offset for the next chunk."""
    try:
        return workspace_files.read_large_file(path, offset, max_bytes)
    except WorkspaceFileError as exc:
        return _failure(exc)


@tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a UTF-8 text file inside the workspace."""
    try:
        return workspace_files.write(path, content)
    except WorkspaceFileError as exc:
        return _failure(exc)


@tool
def append_file(path: str, content: str) -> str:
    """Append UTF-8 text to a file inside the workspace."""
    try:
        return workspace_files.append(path, content)
    except WorkspaceFileError as exc:
        return _failure(exc)


@tool
def create_directory(path: str) -> str:
    """Create a directory and missing parent directories inside the workspace."""
    try:
        return workspace_files.mkdir(path)
    except WorkspaceFileError as exc:
        return _failure(exc)


@tool
def delete_path(path: str) -> str:
    """Delete a file or empty directory inside the workspace; never recursively."""
    try:
        return workspace_files.delete(path)
    except WorkspaceFileError as exc:
        return _failure(exc)


@tool
def copy_path(source: str, destination: str) -> str:
    """Copy a workspace file or directory; the destination must not exist."""
    try:
        return workspace_files.copy(source, destination)
    except WorkspaceFileError as exc:
        return _failure(exc)


@tool
def move_path(source: str, destination: str) -> str:
    """Move a workspace file or directory; the destination must not exist."""
    try:
        return workspace_files.move(source, destination)
    except WorkspaceFileError as exc:
        return _failure(exc)


@tool
def search_file(
    query: str,
    path: str = ".",
    file_pattern: str = "*",
    use_regex: bool = False,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> str:
    """Search workspace text files like grep and return file:line:content matches."""
    try:
        return workspace_files.search_file(query, path, file_pattern, use_regex, max_results)
    except WorkspaceFileError as exc:
        return _failure(exc)


@tool
def list_dir(path: str = ".", recursive: bool = False, max_entries: int = DEFAULT_MAX_RESULTS) -> str:
    """List a workspace directory; set recursive to see its nested structure."""
    try:
        return workspace_files.list_dir(path, recursive, max_entries)
    except WorkspaceFileError as exc:
        return _failure(exc)


@tool
def file_tool(action: Action, path: str, content: str | None = None) -> str:
    """Read or write UTF-8 text files within the workspace.

    Use action ``read`` to return a file's contents, ``write`` to replace a file
    atomically, ``append`` to add text, ``mkdir`` to create a directory, or
    ``delete`` to remove a file or empty directory. ``content`` is required only
    for write/append. Paths may be workspace-relative or absolute paths inside
    the workspace; paths outside it are rejected. Delete is never recursive.
    """
    try:
        return workspace_files.run(action, path, content)
    except WorkspaceFileError as exc:
        return _failure(exc)


FILE_TOOLS = [
    read_file,
    read_large_file,
    write_file,
    append_file,
    create_directory,
    delete_path,
    copy_path,
    move_path,
    search_file,
    list_dir,
]


__all__ = [
    "FILE_TOOLS",
    "WorkspaceFileError",
    "WorkspaceFiles",
    "append_file",
    "copy_path",
    "create_directory",
    "delete_path",
    "file_tool",
    "list_dir",
    "move_path",
    "read_file",
    "read_large_file",
    "search_file",
    "workspace_files",
    "write_file",
]
