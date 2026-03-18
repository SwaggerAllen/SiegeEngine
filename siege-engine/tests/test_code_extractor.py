"""Tests for backend.pipeline.nodes.code_extractor – extracting code files from markdown."""

from backend.pipeline.nodes.code_extractor import (
    _extract_filepath,
    _is_filepath_line,
    extract_code_files,
)


class TestExtractCodeFiles:
    def test_single_python_file(self):
        content = "```python\n# filepath: src/main.py\nprint('hello')\n```"
        files = extract_code_files(content)
        assert len(files) == 1
        assert files[0]["file_path"] == "src/main.py"
        assert files[0]["content"] == "print('hello')"
        assert files[0]["language"] == "python"

    def test_multiple_files(self):
        content = (
            "```python\n"
            "# filepath: a.py\n"
            "x = 1\n"
            "```\n\n"
            "```javascript\n"
            "// filepath: b.js\n"
            "const y = 2;\n"
            "```"
        )
        files = extract_code_files(content)
        assert len(files) == 2
        assert files[0]["file_path"] == "a.py"
        assert files[1]["file_path"] == "b.js"

    def test_sql_comment_style(self):
        content = "```sql\n-- filepath: migrations/001.sql\nCREATE TABLE users (id INT);\n```"
        files = extract_code_files(content)
        assert len(files) == 1
        assert files[0]["file_path"] == "migrations/001.sql"

    def test_html_comment_style(self):
        content = "```html\n<!-- filepath: index.html -->\n<h1>Hello</h1>\n```"
        files = extract_code_files(content)
        assert len(files) == 1
        assert files[0]["file_path"] == "index.html"

    def test_skips_blocks_without_filepath(self):
        content = (
            "```python\n"
            "print('no filepath here')\n"
            "```\n\n"
            "```python\n"
            "# filepath: real.py\n"
            "x = 1\n"
            "```"
        )
        files = extract_code_files(content)
        assert len(files) == 1
        assert files[0]["file_path"] == "real.py"

    def test_empty_content_after_filepath_skipped(self):
        content = "```python\n# filepath: empty.py\n```"
        files = extract_code_files(content)
        assert len(files) == 0

    def test_no_language_tag(self):
        content = "```\n# filepath: script.sh\necho hello\n```"
        files = extract_code_files(content)
        assert len(files) == 1
        assert files[0]["language"] == ""

    def test_filepath_removed_from_content(self):
        content = "```python\n# filepath: app.py\nimport os\nprint(os.getcwd())\n```"
        files = extract_code_files(content)
        assert "filepath:" not in files[0]["content"]
        assert "import os" in files[0]["content"]


class TestExtractFilepath:
    def test_hash_comment(self):
        assert _extract_filepath("# filepath: src/main.py\ncode") == "src/main.py"

    def test_slash_comment(self):
        assert _extract_filepath("// filepath: src/index.ts\ncode") == "src/index.ts"

    def test_html_comment(self):
        assert _extract_filepath("<!-- filepath: index.html -->\n<div>") == "index.html"

    def test_case_insensitive(self):
        assert _extract_filepath("# FILEPATH: upper.py\ncode") == "upper.py"

    def test_no_filepath(self):
        assert _extract_filepath("just some code\nmore code") is None

    def test_filepath_not_in_first_5_lines(self):
        lines = "\n".join([f"line {i}" for i in range(6)] + ["# filepath: late.py"])
        assert _extract_filepath(lines) is None


class TestIsFilepathLine:
    def test_hash_filepath(self):
        assert _is_filepath_line("# filepath: foo.py") is True

    def test_slash_filepath(self):
        assert _is_filepath_line("// filepath: bar.ts") is True

    def test_regular_comment(self):
        assert _is_filepath_line("# this is a regular comment") is False

    def test_empty_line(self):
        assert _is_filepath_line("") is False
