"""Error Parser — categorizes errors from stack traces and build output.

TASK-069 — Supports 6 error categories: build, test, runtime, config, security, dependency.
"""

import re
import logging
from .models import ParsedError

logger = logging.getLogger(__name__)

# Category patterns — ordered by specificity
CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("security", [
        r"SQL injection", r"XSS", r"JWT expired", r"401 Unauthorized",
        r"403 Forbidden", r"invalid signature",
    ]),
    ("build_error", [
        r"SyntaxError", r"ModuleNotFoundError", r"ImportError",
        r"TS\d{4}", r"Cannot find module", r"Type .* is not assignable",
        r"build failed", r"compilation failed",
    ]),
    ("test_failure", [
        r"AssertionError", r"assert .*==", r"expect\(.*\)\.toBe",
        r"\d+ failed", r"FAILED", r"Assertion failed",
    ]),
    ("runtime_error", [
        r"HTTP 500", r"ECONNREFUSED", r"TypeError", r"timeout",
        r"ConnectionError", r"crash", r"unhandled exception",
    ]),
    ("config", [
        r"Port.*conflict", r"connection refused", r"env var",
        r"missing.*environment", r"config.*not found",
    ]),
    ("dependency", [
        r"version conflict", r"missing dep", r"ERR_PNPM",
        r"could not resolve", r"incompatible.*version",
    ]),
]

# Framework detection
FRAMEWORK_PATTERNS: list[tuple[str, str]] = [
    (r"fastapi|uvicorn|starlette", "fastapi"),
    (r"react|\.tsx|\.jsx|vite", "react"),
    (r"pytest|conftest", "pytest"),
    (r"docker|Dockerfile", "docker"),
    (r"tsc|typescript|\.ts:", "tsc"),
]

# File path extraction
FILE_PATH_RE = re.compile(r'(?:File "|at |  File )(.+?\.(?:py|ts|tsx|js|jsx))",?\s*(?:line\s+)?(\d+)')
MESSAGE_RE = re.compile(r'(?:Error:|Exception:|error|Error)(?:\s*:)?\s*(.+?)(?:\n|$)', re.IGNORECASE)


def parse_error(error_text: str) -> ParsedError:
    """Parse an error string into a structured ParsedError.

    Args:
        error_text: Raw error output (stack trace, build log, test output, etc.)

    Returns:
        ParsedError with category, file_path, line_number, and message extracted.
    """
    # Detect category
    category = "runtime_error"  # default
    for cat, patterns in CATEGORY_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, error_text, re.IGNORECASE):
                category = cat
                break
        if category != "runtime_error":
            break

    # Detect framework
    framework = ""
    for pattern, fw in FRAMEWORK_PATTERNS:
        if re.search(pattern, error_text, re.IGNORECASE):
            framework = fw
            break

    # Extract file path and line
    file_match = FILE_PATH_RE.search(error_text)
    file_path = file_match.group(1) if file_match else ""
    line_number = int(file_match.group(2)) if file_match and file_match.group(2) else 0

    # Extract message
    msg_match = MESSAGE_RE.search(error_text)
    message = msg_match.group(1).strip() if msg_match else error_text.split("\n")[0][:200]

    # Extract error type
    error_type = ""
    if category == "build_error":
        ts_match = re.search(r'(TS\d{4})', error_text)
        py_match = re.search(r'(SyntaxError|ModuleNotFoundError|ImportError)', error_text)
        error_type = ts_match.group(1) if ts_match else (py_match.group(1) if py_match else "BuildError")
    elif category == "test_failure":
        error_type = "AssertionError" if "AssertionError" in error_text else "TestFailure"
    elif category == "runtime_error":
        type_match = re.search(r'(TypeError|ECONNREFUSED|ConnectionError|TimeoutError)', error_text)
        error_type = type_match.group(1) if type_match else "RuntimeError"
    else:
        error_type = category.replace("_", " ").title().replace(" ", "")

    # Extract stack summary (top 3 frames)
    stack_summary = []
    for m in FILE_PATH_RE.finditer(error_text):
        if len(stack_summary) >= 3:
            break
        stack_summary.append({
            "file": m.group(1),
            "line": int(m.group(2)) if m.group(2) else 0,
        })

    return ParsedError(
        error_type=error_type,
        category=category,
        file_path=file_path,
        line_number=line_number,
        message=message[:500],
        framework=framework,
        stack_summary=stack_summary,
    )
