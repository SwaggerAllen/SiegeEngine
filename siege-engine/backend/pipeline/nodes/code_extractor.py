import re


def extract_code_files(content: str) -> list[dict]:
    """
    Parse code blocks from LLM-generated markdown content.

    Expects code blocks tagged with a filepath comment, e.g.:
        ```elixir
        # filepath: lib/my_app/auth.ex
        defmodule MyApp.Auth do
          ...
        end
        ```

    Also supports: // filepath:, -- filepath:, <!-- filepath: -->

    Returns: [{"file_path": "lib/my_app/auth.ex", "content": "...", "language": "elixir"}]
    """
    files: list[dict] = []

    # Match fenced code blocks with optional language
    pattern = r"```(\w*)\s*\n(.*?)```"
    for match in re.finditer(pattern, content, re.DOTALL):
        language = match.group(1) or ""
        block = match.group(2)

        # Look for filepath comment in first few lines
        filepath = _extract_filepath(block)
        if not filepath:
            continue

        # Remove the filepath comment line from content
        lines = block.split("\n")
        cleaned_lines = [line for line in lines if not _is_filepath_line(line)]
        file_content = "\n".join(cleaned_lines).strip()

        if file_content:
            files.append(
                {
                    "file_path": filepath,
                    "content": file_content,
                    "language": language,
                }
            )

    return files


def _extract_filepath(block: str) -> str | None:
    """Extract filepath from the first few lines of a code block."""
    lines = block.split("\n")[:5]
    for line in lines:
        # Match various comment styles: #, //, --, <!--
        fp_match = re.match(
            r"^\s*(?:#|//|--|<!--)\s*filepath:\s*(.+?)(?:\s*-->)?\s*$",
            line.strip(),
            re.IGNORECASE,
        )
        if fp_match:
            return fp_match.group(1).strip()
    return None


def _is_filepath_line(line: str) -> bool:
    """Check if a line is a filepath comment."""
    return bool(
        re.match(
            r"^\s*(?:#|//|--|<!--)\s*filepath:\s*.+",
            line.strip(),
            re.IGNORECASE,
        )
    )
