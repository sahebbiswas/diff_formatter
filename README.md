# Custom C Code Formatter (cstyle)

A lightweight, **diff-aware** C code style checker and formatter.

**Key Feature**: It only processes **modified lines** from a git diff (or Perforce-style unified diff). This prevents unnecessary reformatting of untouched code, keeping source control diffs clean.

## Features

- **Passive mode** (`--mode passive`): Scans modified lines and reports violations without changing anything.
- **Active mode** (`--mode active`): Automatically fixes safe issues (trailing whitespace, operator spacing, keyword spacing, pointer style) **only on the changed lines**.
- User-defined guidelines via `config.yaml`.
- Supports common C style rules: indentation (basic), line length, brace style (K&R), spacing, etc.
- Works with `git diff` or any unified diff file.
- Pure Python – no external dependencies beyond PyYAML (pre-installed in the env).

## Quick Start

```bash
# 1. Passive check on a diff
python cstyle.py --diff-file examples/sample.diff --mode passive

# 2. Auto-fix the modified lines
python cstyle.py --diff-file examples/sample.diff --mode active

# 3. Use current git changes
python cstyle.py --git-diff --mode passive

# 4. Perforce native support (p4 diff -du)
p4 diff -du > changes.diff
python cstyle.py --diff-file changes.diff --mode passive

# 5. Live commands with the new extensible provider system
python cstyle.py --git-diff --mode passive
python cstyle.py --p4-diff --mode passive
```

## Configuration (config.yaml)

Edit `config.yaml` to match your team's style:

```yaml
formatting:
  indent_style: spaces
  indent_size: 4
  max_line_length: 100
  brace_style: knr
  space_after_keywords: true
  space_around_operators: true
  no_trailing_whitespace: true
  pointer_style: right
```

## How It Works

1. Parses the unified diff to identify exactly which lines were modified.
2. For each modified line:
   - **Passive**: Runs all enabled checkers and collects violations.
   - **Active**: Applies safe, line-local fixes (preserving newlines and only touching changed lines).
3. In active mode, creates a `.bak` backup before modifying.

## Limitations & Future Work

- Indentation and brace-style fixes are currently **check-only** in active mode (complex context needed).
- No full C parser (regex-based rules; good enough for 80% of style issues).
- Line length only reports (doesn't auto-wrap).
- For production, consider integrating with `clang-format --lines=...` for full formatting power.

## Example Output (Passive)

```
Processing examples/sample.c (5 modified lines)...

📋 Found 10 formatting issues on modified lines:

📁 examples/sample.c
  Line    6 [trailing_whitespace ] Trailing whitespace found
  Line    6 [operator_spacing    ] Missing spaces around operator
  ...
```

## Extending

### Adding New Diff Providers (Git, Perforce, SVN, etc.)

The diff handling is now fully extensible via the `DiffProvider` abstract base class.

To add support for a new VCS (e.g., SVN, Mercurial, Azure DevOps):

1. Create a new class inheriting from `DiffProvider`
2. Implement:
   - `detect(diff_text)` — quick format detection
   - `parse(diff_text)` — return `{filename: Set[int]}`
   - (optional) `get_live_diff()` — run the native command
3. Add your class to the `DIFF_PROVIDERS` list

Example skeleton:

```python
class SvnDiffProvider(DiffProvider):
    name = "svn"

    @classmethod
    def detect(cls, diff_text: str) -> bool:
        return "Index: " in diff_text and "======" in diff_text

    def parse(self, diff_text: str) -> Dict[str, Set[int]]:
        # your parsing logic here
        ...

    def get_live_diff(self, **kwargs) -> str:
        return subprocess.check_output(["svn", "diff"]).decode()
```

Then just register it — **no changes needed** to `CStyleTool`, `main()`, or the formatter logic.

### Adding New Style Rules

Add new rules by implementing `_check_xxx` and `_fix_xxx` methods in `CStyleTool` and registering them in `_get_all_rules()`.

## Testing & Regression Protection

A full pytest test suite is included to protect the current featureset against regressions.

### Running the Tests

```bash
cd /home/workdir/artifacts/c_custom_formatter

# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests (verbose)
pytest tests/ -v

# With coverage
pytest tests/ --cov=cstyle --cov-report=term-missing
```

### Test Coverage

- **Diff Providers**: Git and Perforce detection, parsing accuracy, line number mapping, depot path handling, empty/malformed diffs.
- **Configuration**: Loading, nested keys, defaults, overrides.
- **Core Tool**: Passive violation reporting, active fixes (keyword spacing, operators, whitespace, pointers), backup creation logic.
- **CLI**: Argument parsing, error cases, integration smoke tests.
- **Regression Guards**: Specific tests for Perforce path stripping, hunk line accuracy, ensuring unchanged lines are never modified.

Tests use the existing `examples/` data and are designed to be fast and deterministic. Add new tests when extending providers or rules.

Property-based testing with Hypothesis can be enabled by uncommenting it in requirements-dev.txt for even stronger fuzzing of the parsers.

This tool demonstrates a practical, minimal-diff approach to code formatting in CI/CD or pre-commit hooks.
