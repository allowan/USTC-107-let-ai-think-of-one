import tempfile
import unittest
from pathlib import Path

from tools.file_tool import WorkspaceFileError, WorkspaceFiles


class WorkspaceFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.files = WorkspaceFiles(self.root, max_read_bytes=16)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_write_read_and_append(self) -> None:
        self.files.write("notes/example.md", "hello")
        self.files.append("notes/example.md", " world")
        self.assertEqual(self.files.read("notes/example.md"), "hello world")

    def test_write_overwrites_existing_file(self) -> None:
        self.files.write("result.txt", "old")
        self.files.write("result.txt", "new")
        self.assertEqual(self.files.read("result.txt"), "new")

    def test_create_and_delete_directory(self) -> None:
        self.files.mkdir("one/two")
        self.assertTrue((self.root / "one" / "two").is_dir())
        self.files.delete("one/two")
        self.assertFalse((self.root / "one" / "two").exists())

    def test_delete_file(self) -> None:
        self.files.write("remove-me.txt", "temporary")
        self.files.delete("remove-me.txt")
        self.assertFalse((self.root / "remove-me.txt").exists())

    def test_copy_file_and_directory(self) -> None:
        self.files.write("source/file.txt", "copied")
        self.files.copy("source/file.txt", "copies/file.txt")
        self.files.copy("source", "directory-copy")
        self.assertEqual((self.root / "copies/file.txt").read_text(), "copied")
        self.assertEqual((self.root / "directory-copy/file.txt").read_text(), "copied")

    def test_move_file_and_directory(self) -> None:
        self.files.write("old/file.txt", "moved")
        self.files.move("old/file.txt", "new/file.txt")
        self.assertFalse((self.root / "old/file.txt").exists())
        self.files.move("old", "renamed")
        self.assertTrue((self.root / "renamed").is_dir())

    def test_copy_and_move_refuse_overwrite(self) -> None:
        self.files.write("one.txt", "one")
        self.files.write("two.txt", "two")
        with self.assertRaisesRegex(WorkspaceFileError, "already exists"):
            self.files.copy("one.txt", "two.txt")
        with self.assertRaisesRegex(WorkspaceFileError, "already exists"):
            self.files.move("one.txt", "two.txt")

    def test_read_large_file_in_chunks(self) -> None:
        (self.root / "large.txt").write_text("abcdefghij", encoding="utf-8")
        first = self.files.read_large_file("large.txt", offset=0, max_bytes=4)
        second = self.files.read_large_file("large.txt", offset=4, max_bytes=6)
        self.assertIn("next_offset=4", first)
        self.assertTrue(first.endswith("abcd"))
        self.assertIn("next_offset=EOF", second)
        self.assertTrue(second.endswith("efghij"))

    def test_refuses_to_delete_non_empty_directory(self) -> None:
        self.files.write("kept/file.txt", "important")
        with self.assertRaisesRegex(WorkspaceFileError, "must be empty"):
            self.files.delete("kept")
        self.assertTrue((self.root / "kept" / "file.txt").exists())

    def test_list_directory(self) -> None:
        self.files.write("src/main.py", "print('hello')")
        self.files.write("README.md", "hello")
        listing = self.files.list_dir(".", recursive=True)
        self.assertIn("src/", listing)
        self.assertIn("src/main.py", listing)
        self.assertIn("README.md", listing)

    def test_search_file_literal_and_regex(self) -> None:
        searcher = WorkspaceFiles(self.root, max_read_bytes=1_000)
        self.files.write("src/one.py", "alpha\nvalue = 42\n")
        self.files.write("src/two.txt", "value = 99\n")
        literal = searcher.search_file("value", file_pattern="*.py")
        self.assertIn("src/one.py:2:value = 42", literal)
        self.assertNotIn("two.txt", literal)
        regex = searcher.search_file(r"value = \d+", use_regex=True)
        self.assertIn("src/two.txt:1:value = 99", regex)

    def test_search_rejects_invalid_regex(self) -> None:
        with self.assertRaisesRegex(WorkspaceFileError, "Invalid regular expression"):
            self.files.search_file("[", use_regex=True)

    def test_rejects_path_outside_workspace(self) -> None:
        with self.assertRaisesRegex(WorkspaceFileError, "outside the workspace"):
            self.files.read("../secret.txt")

    def test_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(WorkspaceFileError, "outside the workspace"):
                self.files.write("escape/secret.txt", "nope")

    def test_rejects_large_read(self) -> None:
        (self.root / "large.txt").write_text("x" * 17, encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceFileError, "too large"):
            self.files.read("large.txt")

    def test_run_validates_content(self) -> None:
        with self.assertRaisesRegex(WorkspaceFileError, "must be omitted"):
            self.files.run("read", "anything", "unexpected")
        with self.assertRaisesRegex(WorkspaceFileError, "is required"):
            self.files.run("write", "anything")


if __name__ == "__main__":
    unittest.main()
