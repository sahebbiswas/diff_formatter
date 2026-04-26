#!/usr/bin/env python3
"""
Custom C Code Formatter & Checker
---------------------------------
Works ONLY on modified lines from a git diff or native Perforce `p4 diff -du`.

Has passive (report only) and active (fix in-place) modes.
Auto-detects diff format and handles Perforce depot paths.

Usage examples:
  python cstyle.py --diff-file examples/sample.diff --mode passive
  python cstyle.py --diff-file examples/sample.diff --mode active --config config.yaml
  python cstyle.py --git-diff --mode passive
  p4 diff -du > changes.diff && python cstyle.py --diff-file changes.diff --mode passive
"""

import argparse
import os
import re
import sys
import yaml
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple, Optional
from pathlib import Path
from abc import ABC, abstractmethod
import subprocess


class DiffProvider(ABC):
    """Base class for source control diff providers.
    Extend this class to add support for new VCS (SVN, Mercurial, etc.).
    """

    name: str = "base"

    @classmethod
    def detect(cls, diff_text: str) -> bool:
        """Return True if this provider recognizes the diff format."""
        return False

    @abstractmethod
    def parse(self, diff_text: str) -> Dict[str, Set[int]]:
        """Parse diff text into {filename: set of modified line numbers}."""
        pass

    def get_live_diff(self, **kwargs) -> str:
        """Get diff from live command (optional)."""
        raise NotImplementedError(f"{self.name} does not support live diff")


class GitDiffProvider(DiffProvider):
    name = "git"

    @classmethod
    def detect(cls, diff_text: str) -> bool:
        return "diff --git" in diff_text

    def parse(self, diff_text: str) -> Dict[str, Set[int]]:
        files: Dict[str, Set[int]] = {}
        current_file = None
        in_hunk = False
        new_line_num = 0

        for line in diff_text.splitlines(keepends=False):
            if line.startswith("diff --git"):
                match = re.search(r" b/(.+)$", line)
                if match:
                    current_file = match.group(1)
                    files[current_file] = set()
                continue

            if line.startswith("--- ") or line.startswith("+++ "):
                continue

            if line.startswith("@@"):
                match = re.search(r"\+(\d+)(?:,(\d+))?", line)
                if match and current_file:
                    new_line_num = int(match.group(1))
                    in_hunk = True
                continue

            if in_hunk and current_file:
                if line.startswith("+") and not line.startswith("+++"):
                    files[current_file].add(new_line_num)
                    new_line_num += 1
                elif line.startswith("-") and not line.startswith("---"):
                    pass
                elif line.startswith(" "):
                    new_line_num += 1
                elif line.startswith("\\"):
                    pass
                else:
                    in_hunk = False
        return files

    def get_live_diff(self, **kwargs) -> str:
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"], capture_output=True, text=True, check=True
            )
            return result.stdout
        except subprocess.CalledProcessError:
            return ""


class PerforceDiffProvider(DiffProvider):
    name = "perforce"

    @classmethod
    def detect(cls, diff_text: str) -> bool:
        lines = diff_text.splitlines()[:5]
        return any(line.startswith("==== ") for line in lines)

    def parse(self, diff_text: str) -> Dict[str, Set[int]]:
        files: Dict[str, Set[int]] = {}
        current_file = None
        in_hunk = False
        new_line_num = 0

        for line in diff_text.splitlines(keepends=False):
            if line.startswith("==== "):
                match = re.search(r"====\s+(.+?)(?:#\d+|\s+\()", line)
                if match:
                    raw_path = match.group(1).strip()
                    if raw_path.startswith("//depot/"):
                        raw_path = raw_path[8:]
                    current_file = raw_path
                    files[current_file] = set()
                continue

            if line.startswith("--- ") or line.startswith("+++ "):
                continue

            if line.startswith("@@"):
                match = re.search(r"\+(\d+)(?:,(\d+))?", line)
                if match and current_file:
                    new_line_num = int(match.group(1))
                    in_hunk = True
                continue

            if in_hunk and current_file:
                if line.startswith("+") and not line.startswith("+++"):
                    files[current_file].add(new_line_num)
                    new_line_num += 1
                elif line.startswith("-") and not line.startswith("---"):
                    pass
                elif line.startswith(" "):
                    new_line_num += 1
                elif line.startswith("\\"):
                    pass
                else:
                    in_hunk = False
        return files

    def get_live_diff(self, **kwargs) -> str:
        try:
            result = subprocess.run(
                ["p4", "diff", "-du"], capture_output=True, text=True, check=True
            )
            return result.stdout
        except subprocess.CalledProcessError:
            return ""


# Registry of available providers (order matters for auto-detection)
DIFF_PROVIDERS: List[type[DiffProvider]] = [GitDiffProvider, PerforceDiffProvider]


def get_provider(diff_text: Optional[str] = None, provider_name: Optional[str] = None) -> DiffProvider:
    """Factory: return appropriate provider instance."""
    if provider_name:
        for pcls in DIFF_PROVIDERS:
            if pcls.name == provider_name.lower():
                return pcls()
        raise ValueError(f"Unknown provider: {provider_name}")

    if diff_text:
        for pcls in DIFF_PROVIDERS:
            if pcls.detect(diff_text):
                return pcls()
    # Default to Git if nothing matches
    return GitDiffProvider()


@dataclass
class Violation:
    filename: str
    line_num: int
    rule: str
    message: str
    original: str = ""
    suggestion: str = ""


class StyleConfig:
    def __init__(self, config_path: Optional[str] = None):
        self.config = {
            "formatting": {
                "indent_style": "spaces",
                "indent_size": 4,
                "max_line_length": 100,
                "brace_style": "knr",
                "space_after_keywords": True,
                "space_around_operators": True,
                "space_before_brace": True,
                "no_trailing_whitespace": True,
                "no_tabs": True,
                "pointer_style": "right",
            },
            "passive_checks": [
                "trailing_whitespace", "line_length", "indentation",
                "brace_style", "operator_spacing", "keyword_spacing", "pointer_style"
            ]
        }
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r') as f:
                user_config = yaml.safe_load(f) or {}
                self.config.update(user_config)

    def get(self, key: str, default=None):
        keys = key.split('.')
        val = self.config
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, default)
            else:
                return default
        return val

class CStyleTool:
    def __init__(self, config: StyleConfig):
        self.config = config
        self.violations: List[Violation] = []

    # ---------------- Rule Implementations ----------------

    def _check_trailing_whitespace(self, line: str, lineno: int, filename: str, all_lines: List[str]) -> List[Violation]:
        if line.rstrip() != line and self.config.get("formatting.no_trailing_whitespace"):
            return [Violation(
                filename=filename, line_num=lineno, rule="trailing_whitespace",
                message="Trailing whitespace found",
                original=line,
                suggestion=line.rstrip()
            )]
        return []

    def _fix_trailing_whitespace(self, line: str, lineno: int, all_lines: List[str]) -> str:
        if line.rstrip() == line:
            return line
        # Preserve original line ending (important for writelines)
        if line.endswith('\r\n'):
            return line.rstrip() + '\r\n'
        elif line.endswith('\n'):
            return line.rstrip() + '\n'
        return line.rstrip()

    def _check_line_length(self, line: str, lineno: int, filename: str, all_lines: List[str]) -> List[Violation]:
        max_len = self.config.get("formatting.max_line_length", 100)
        if len(line.rstrip()) > max_len:
            return [Violation(
                filename=filename, line_num=lineno, rule="line_length",
                message=f"Line exceeds {max_len} characters ({len(line.rstrip())} chars)",
                original=line,
                suggestion=line[:max_len-3] + "..." if len(line) > max_len else line
            )]
        return []

    def _check_indentation(self, line: str, lineno: int, filename: str, all_lines: List[str]) -> List[Violation]:
        if not line.strip():
            return []
        indent_style = self.config.get("formatting.indent_style")
        indent_size = self.config.get("formatting.indent_size", 4)

        # Calculate expected indent level by counting braces before this line
        expected_level = self._calculate_indent_level(all_lines, lineno)
        expected_indent = " " * (expected_level * indent_size) if indent_style == "spaces" else "\t" * expected_level

        current_indent = re.match(r'^[\t ]*', line).group(0)
        if current_indent != expected_indent:
            return [Violation(
                filename=filename, line_num=lineno, rule="indentation",
                message=f"Indentation mismatch (expected {expected_level} levels)",
                original=line,
                suggestion=expected_indent + line.lstrip()
            )]
        return []

    def _fix_indentation(self, line: str, lineno: int, all_lines: List[str]) -> str:
        if not line.strip():
            return line
        indent_style = self.config.get("formatting.indent_style")
        indent_size = self.config.get("formatting.indent_size", 4)
        expected_level = self._calculate_indent_level(all_lines, lineno)
        expected_indent = " " * (expected_level * indent_size) if indent_style == "spaces" else "\t" * expected_level
        return expected_indent + line.lstrip()

    def _calculate_indent_level(self, all_lines: List[str], lineno: int) -> int:
        """Count open braces minus close braces up to (but not including) this line."""
        level = 0
        for i in range(lineno - 1):  # 0-based index
            l = all_lines[i]
            level += l.count('{') - l.count('}')
            # Handle do-while, etc. but simple version is good enough
        return max(0, level)

    def _check_brace_style(self, line: str, lineno: int, filename: str, all_lines: List[str]) -> List[Violation]:
        style = self.config.get("formatting.brace_style", "knr")
        stripped = line.strip()

        # Check for if/for/while/switch/function followed by { on next line (Allman violation for K&R)
        if style == "knr":
            # Look for control keywords not followed by { on same line
            if re.search(r'\b(if|for|while|switch|else)\s*\([^)]*\)\s*$', stripped) and lineno < len(all_lines):
                next_line = all_lines[lineno].strip() if lineno < len(all_lines) else ""
                if next_line.startswith('{'):
                    return [Violation(
                        filename=filename, line_num=lineno, rule="brace_style",
                        message="Brace should be on same line (K&R style)",
                        original=line,
                        suggestion=line.rstrip() + " {"
                    )]
        # Could add Allman checks too
        return []

    def _fix_brace_style(self, line: str, lineno: int, all_lines: List[str]) -> str:
        style = self.config.get("formatting.brace_style", "knr")
        if style != "knr":
            return line
        # Simple fix: if line ends with ) and next line is {, merge
        stripped = line.rstrip()
        if re.search(r'\b(if|for|while|switch|else)\s*\([^)]*\)\s*$', stripped):
            if lineno < len(all_lines) and all_lines[lineno].strip() == "{":
                # We can't easily merge here without affecting next line.
                # For demo, just warn (fix would require multi-line edit)
                return line
        return line

    def _check_operator_spacing(self, line: str, lineno: int, filename: str, all_lines: List[str]) -> List[Violation]:
        if not self.config.get("formatting.space_around_operators"):
            return []
        # Avoid matching inside strings or comments (simple heuristic)
        code_part = re.split(r'["\']', line)[0] if '"' in line or "'" in line else line
        code_part = re.split(r'//|/\*', code_part)[0]  # remove comments

        if re.search(r'\w[+\-*/=<>!]=?\w', code_part):
            fixed = re.sub(r'(\w)([+\-*/=<>!]=?)(\w)', r'\1 \2 \3', line)
            if fixed != line:
                return [Violation(
                    filename=filename, line_num=lineno, rule="operator_spacing",
                    message="Missing spaces around operator",
                    original=line,
                    suggestion=fixed
                )]
        return []

    def _fix_operator_spacing(self, line: str, lineno: int, all_lines: List[str]) -> str:
        if not self.config.get("formatting.space_around_operators"):
            return line
        # Apply only outside obvious strings
        if '"' in line or "'" in line:
            return line  # skip for safety in demo
        line = re.sub(r'(\w)([+\-*/=<>!]=?)(\w)', r'\1 \2 \3', line)
        return line

    def _check_keyword_spacing(self, line: str, lineno: int, filename: str, all_lines: List[str]) -> List[Violation]:
        if not self.config.get("formatting.space_after_keywords"):
            return []
        # if(, for(, while(, switch(
        if re.search(r'\b(if|for|while|switch|return)\s*\(', line) and not re.search(r'\b(if|for|while|switch|return)\s+\(', line):
            fixed = re.sub(r'\b(if|for|while|switch|return)\s*\(', r'\1 (', line)
            return [Violation(
                filename=filename, line_num=lineno, rule="keyword_spacing",
                message="Missing space after keyword",
                original=line,
                suggestion=fixed
            )]
        return []

    def _fix_keyword_spacing(self, line: str, lineno: int, all_lines: List[str]) -> str:
        if not self.config.get("formatting.space_after_keywords"):
            return line
        return re.sub(r'\b(if|for|while|switch|return)\s*\(', r'\1 (', line)

    def _check_pointer_style(self, line: str, lineno: int, filename: str, all_lines: List[str]) -> List[Violation]:
        style = self.config.get("formatting.pointer_style", "right")
        if style == "right":
            # Prefer int *p over int* p
            if re.search(r'\w\*\s*\w', line) and not re.search(r'\w\s+\*\s*\w', line):
                fixed = re.sub(r'(\w)\*\s*(\w)', r'\1 *\2', line)
                return [Violation(
                    filename=filename, line_num=lineno, rule="pointer_style",
                    message="Pointer style should be 'type *name' (right-aligned *)",
                    original=line,
                    suggestion=fixed
                )]
        return []

    def _fix_pointer_style(self, line: str, lineno: int, all_lines: List[str]) -> str:
        style = self.config.get("formatting.pointer_style", "right")
        if style == "right":
            return re.sub(r'(\w)\*\s*(\w)', r'\1 *\2', line)
        return line

    # ---------------- Core Processing ----------------

    def _get_all_rules(self):
        """Return list of (check_func, fix_func, name)"""
        return [
            (self._check_trailing_whitespace, self._fix_trailing_whitespace, "trailing_whitespace"),
            (self._check_line_length, None, "line_length"),  # check-only
            (self._check_indentation, self._fix_indentation, "indentation"),
            (self._check_brace_style, self._fix_brace_style, "brace_style"),
            (self._check_operator_spacing, self._fix_operator_spacing, "operator_spacing"),
            (self._check_keyword_spacing, self._fix_keyword_spacing, "keyword_spacing"),
            (self._check_pointer_style, self._fix_pointer_style, "pointer_style"),
        ]

    SAFE_ACTIVE_RULES = {"trailing_whitespace", "operator_spacing", "keyword_spacing", "pointer_style"}

    def process_file(self, filename: str, changed_lines: Set[int], mode: str = "passive"):
        """Process one file's changed lines."""
        if not os.path.exists(filename):
            print(f"Warning: File {filename} not found. Skipping.")
            return

        with open(filename, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()

        rules = self._get_all_rules()
        file_violations = []

        for lineno_1based in sorted(changed_lines):
            if lineno_1based > len(all_lines):
                continue
            line = all_lines[lineno_1based - 1]  # 0-based

            for check_func, fix_func, rule_name in rules:
                if rule_name not in self.config.get("passive_checks", []):
                    continue
                violations = check_func(line, lineno_1based, filename, all_lines)
                for v in violations:
                    file_violations.append(v)

        self.violations.extend(file_violations)

        if mode == "active":
            self._apply_fixes(filename, all_lines, changed_lines)

    def _apply_fixes(self, filename: str, all_lines: List[str], changed_lines: Set[int]):
        """Apply fixes to changed lines only and write back.
        Only uses SAFE_ACTIVE_RULES to avoid complex multi-line interactions.
        """
        rules = self._get_all_rules()
        modified = False

        for lineno_1based in sorted(changed_lines):
            if lineno_1based > len(all_lines):
                continue
            original_line = all_lines[lineno_1based - 1]
            fixed_line = original_line

            for check_func, fix_func, rule_name in rules:
                if fix_func is None:
                    continue
                if rule_name not in self.SAFE_ACTIVE_RULES:
                    continue
                if rule_name not in self.config.get("passive_checks", []):
                    continue
                fixed_line = fix_func(fixed_line, lineno_1based, all_lines)

            if fixed_line != original_line:
                all_lines[lineno_1based - 1] = fixed_line
                modified = True

        if modified:
            backup = filename + ".bak"
            if not os.path.exists(backup):
                os.rename(filename, backup)
            with open(filename, 'w', encoding='utf-8') as f:
                f.writelines(all_lines)
            print(f"  ✓ Fixed and saved {filename} (backup: {backup})")
        else:
            print(f"  No fixes needed for {filename}")

    def run(self, diff_files: Dict[str, Set[int]], mode: str = "passive"):
        print(f"\n{'='*60}")
        print(f"C Custom Formatter - Mode: {mode.upper()}")
        print(f"{'='*60}\n")

        for filename, changed_lines in diff_files.items():
            if not changed_lines:
                continue

            actual_file = filename
            if not os.path.exists(actual_file):
                # Perforce often gives depot paths or full paths — try basename
                basename = os.path.basename(filename)
                if os.path.exists(basename):
                    actual_file = basename
                    print(f"  (Mapped {filename} → {basename})")
                else:
                    print(f"Warning: File '{filename}' not found (tried basename too). Skipping.")
                    continue

            print(f"Processing {actual_file} ({len(changed_lines)} modified lines)...")
            self.process_file(actual_file, changed_lines, mode)

        # Report
        if mode == "passive":
            self._print_report()

    def _print_report(self):
        if not self.violations:
            print("\n✅ No formatting issues found on modified lines!")
            return

        print(f"\n📋 Found {len(self.violations)} formatting issues on modified lines:\n")
        current_file = None
        for v in sorted(self.violations, key=lambda x: (x.filename, x.line_num)):
            if v.filename != current_file:
                current_file = v.filename
                print(f"\n📁 {current_file}")
            print(f"  Line {v.line_num:4d} [{v.rule:20s}] {v.message}")
            if v.suggestion and v.suggestion != v.original:
                print(f"           Suggested: {v.suggestion.strip()}")
        print("\nRun with --mode active to auto-fix (where possible).")

def main():
    parser = argparse.ArgumentParser(
        description="Custom C formatter that only touches modified lines from a diff.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cstyle.py --diff-file examples/sample.diff --mode passive
  python cstyle.py --diff-file examples/sample.diff --mode active
  python cstyle.py --git-diff --mode passive
  p4 diff -du > changes.diff && python cstyle.py --diff-file changes.diff --mode passive
        """
    )
    parser.add_argument("--diff-file", help="Path to unified diff file (git or p4 diff -du format)")
    parser.add_argument("--git-diff", action="store_true", help="Automatically run 'git diff HEAD'")
    parser.add_argument("--p4-diff", action="store_true", help="Automatically run 'p4 diff -du'")
    parser.add_argument("--provider", choices=["git", "perforce"], help="Force a specific diff provider")
    parser.add_argument("--mode", choices=["passive", "active"], default="passive",
                        help="passive = report only, active = fix in-place")
    parser.add_argument("--config", default="config.yaml", help="Path to style config YAML")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    # Load config
    config = StyleConfig(args.config)

    # Get diff text
    diff_text = ""
    provider = None

    if args.diff_file:
        with open(args.diff_file, 'r') as f:
            diff_text = f.read()
        provider = get_provider(diff_text, args.provider)
    elif args.git_diff:
        provider = GitDiffProvider()
        diff_text = provider.get_live_diff()
    elif args.p4_diff:
        provider = PerforceDiffProvider()
        diff_text = provider.get_live_diff()
    else:
        print("Error: Provide --diff-file, --git-diff, or --p4-diff")
        parser.print_help()
        sys.exit(1)

    if not diff_text or not diff_text.strip():
        print("No diff content found.")
        sys.exit(0)

    # Use provider to parse
    if provider is None:
        provider = get_provider(diff_text, args.provider)

    changed = provider.parse(diff_text)

    if not changed:
        print("No modified lines detected in diff.")
        sys.exit(0)

    # Run tool
    tool = CStyleTool(config)
    tool.run(changed, args.mode)

if __name__ == "__main__":
    main()
