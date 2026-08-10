"""Structural parser for shell command strings.

The permission classifier used to fnmatch patterns against the raw command
string and lex with ``shlex.shlex(punctuation_chars=...)``. That lexer does not
split on ``$(``, backticks or ``${``, so substitution text glued itself onto
ordinary tokens and only the first token decided the risk tier — which is how
``echo $(rm -rf ~/data)`` classified as a silent read.

This module turns a command string into structured segments instead:

    parse_command("FOO=bar rm -rf /tmp/x > out.log")
        → one segment with assignments=["FOO=bar"], argv=["rm", "-rf", "/tmp/x"]
          and a redirect that writes a real file

Every classification rule can then be written against structure — the head
command after stripping assignments and ``basename``, its flags, its redirect
targets, and the commands nested inside substitutions — rather than against
text that is trivial to disguise.

Parsing is deliberately conservative: anything it cannot make sense of is
reported as a failure so callers can fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ParsedCommand",
    "Redirect",
    "Segment",
    "parse_command",
]

# Operators that terminate a segment, longest first so "||" wins over "|".
_CONTROL_OPERATORS = ("||", "&&", ";;", ";", "|&", "|", "&", "\n")

# Redirection operators, longest first.
_REDIRECT_OPERATORS = ("&>>", "&>", "<<<", "<<", ">>", ">|", ">&", "<&", ">", "<")

# Redirect targets that do not amount to writing a real file.
_NULL_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


@dataclass(frozen=True)
class Redirect:
    """A single redirection, e.g. ``2>&1`` or ``>> out.log``."""

    operator: str
    target: str
    fd: str = ""

    @property
    def writes_file(self) -> bool:
        """True when this redirect creates, truncates or appends a real file."""
        if self.operator in {"<", "<<", "<<<", "<&"}:
            return False
        if self.operator in {">&", "&>"} and self.target.isdigit():
            return False  # plain descriptor duplication such as 2>&1
        if not self.target:
            return False
        return self.target not in _NULL_TARGETS


@dataclass(frozen=True)
class Segment:
    """One simple command: assignments, argv, redirects and nested substitutions."""

    argv: list[str] = field(default_factory=list)
    assignments: list[str] = field(default_factory=list)
    redirects: list[Redirect] = field(default_factory=list)
    substitutions: list[str] = field(default_factory=list)

    @property
    def head(self) -> str:
        """Lowercased basename of the command being run, ``""`` when there is none."""
        if not self.argv:
            return ""
        return Path(self.argv[0]).name.lower()

    @property
    def args(self) -> list[str]:
        return self.argv[1:]

    @property
    def writes_files(self) -> list[Redirect]:
        return [redirect for redirect in self.redirects if redirect.writes_file]

    def normalized(self) -> str:
        """``basename``-ed, assignment-free command text for pattern matching.

        This is what defeats ``FOO=bar rm -rf /tmp/x``, ``/bin/rm -rf /tmp/x``
        and ``"rm" -rf /tmp/x`` all dodging the ``rm -rf*`` block pattern.
        """
        if not self.argv:
            return ""
        return " ".join([self.head, *self.args])


@dataclass(frozen=True)
class ParsedCommand:
    segments: list[Segment] = field(default_factory=list)
    ok: bool = True
    error: str = ""

    @property
    def substitutions(self) -> list[str]:
        """Every command substitution found anywhere in the command."""
        found: list[str] = []
        for segment in self.segments:
            found.extend(segment.substitutions)
        return found


class _ParseError(Exception):
    pass


@dataclass
class _Token:
    text: str
    kind: str  # "word" | "control" | "redirect"
    substitutions: list[str] = field(default_factory=list)
    # Set for redirect tokens whose fd prefix was attached, e.g. the "2" of "2>&1".
    fd: str = ""


def _read_quoted(text: str, index: int, quote: str) -> tuple[str, list[str], int]:
    """Read a quoted run starting *after* the opening quote."""
    out: list[str] = []
    substitutions: list[str] = []
    while index < len(text):
        char = text[index]
        if char == quote:
            return "".join(out), substitutions, index + 1
        if quote == '"' and char == "\\" and index + 1 < len(text):
            out.append(text[index + 1])
            index += 2
            continue
        # Command substitution survives inside double quotes, which is exactly
        # how `echo "$(rm -rf ~/data)"` used to slip through.
        if quote == '"' and char == "$" and text.startswith("$(", index):
            inner, index = _read_balanced(text, index + 2, "(", ")")
            substitutions.append(inner)
            out.append(f"$({inner})")
            continue
        if quote == '"' and char == "`":
            inner, index = _read_until(text, index + 1, "`")
            substitutions.append(inner)
            out.append(f"`{inner}`")
            continue
        if quote == '"' and char == "$" and text.startswith("${", index):
            inner, index = _read_balanced(text, index + 2, "{", "}")
            substitutions.extend(_nested_substitutions(inner))
            out.append(f"${{{inner}}}")
            continue
        out.append(char)
        index += 1
    raise _ParseError(f"unterminated {quote} quote")


def _read_balanced(text: str, index: int, opener: str, closer: str) -> tuple[str, int]:
    """Read until the matching closer, honouring nesting. Returns (inner, next index)."""
    depth = 1
    out: list[str] = []
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            out.append(char)
            out.append(text[index + 1])
            index += 2
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return "".join(out), index + 1
        out.append(char)
        index += 1
    raise _ParseError(f"unterminated {opener}{closer} expansion")


def _read_until(text: str, index: int, terminator: str) -> tuple[str, int]:
    out: list[str] = []
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            out.append(text[index + 1])
            index += 2
            continue
        if char == terminator:
            return "".join(out), index + 1
        out.append(char)
        index += 1
    raise _ParseError(f"unterminated {terminator}")


def _nested_substitutions(text: str) -> list[str]:
    """Command substitutions hiding inside a ``${...}`` parameter expansion."""
    found: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith("$(", index):
            try:
                inner, index = _read_balanced(text, index + 2, "(", ")")
            except _ParseError:
                return found
            found.append(inner)
            continue
        if text[index] == "`":
            try:
                inner, index = _read_until(text, index + 1, "`")
            except _ParseError:
                return found
            found.append(inner)
            continue
        index += 1
    return found


def _tokenize(cmd: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    length = len(cmd)

    current: list[str] = []
    current_subs: list[str] = []
    has_word = False

    def flush() -> None:
        nonlocal current, current_subs, has_word
        if has_word:
            tokens.append(_Token("".join(current), "word", list(current_subs)))
        current = []
        current_subs = []
        has_word = False

    while index < length:
        char = cmd[index]

        if char in " \t\r":
            flush()
            index += 1
            continue

        if char == "\\" and index + 1 < length:
            current.append(cmd[index + 1])
            has_word = True
            index += 2
            continue

        if char in "'\"":
            body, subs, index = _read_quoted(cmd, index + 1, char)
            current.append(body)
            current_subs.extend(subs)
            has_word = True
            continue

        if char == "`":
            inner, index = _read_until(cmd, index + 1, "`")
            current.append(f"`{inner}`")
            current_subs.append(inner)
            has_word = True
            continue

        if cmd.startswith("$(", index):
            inner, index = _read_balanced(cmd, index + 2, "(", ")")
            current.append(f"$({inner})")
            current_subs.append(inner)
            has_word = True
            continue

        if cmd.startswith("${", index):
            inner, index = _read_balanced(cmd, index + 2, "{", "}")
            current.append(f"${{{inner}}}")
            current_subs.extend(_nested_substitutions(inner))
            has_word = True
            continue

        # Process substitution: <(cmd) and >(cmd) both execute cmd.
        if cmd.startswith("<(", index) or cmd.startswith(">(", index):
            prefix = cmd[index]
            inner, index = _read_balanced(cmd, index + 2, "(", ")")
            current.append(f"{prefix}({inner})")
            current_subs.append(inner)
            has_word = True
            continue

        if char == "#" and not has_word:
            break  # comment runs to end of line

        # A bare "(" or ")" is a subshell grouping; treat the contents inline.
        if char in "()":
            flush()
            index += 1
            continue

        matched_control = next((op for op in _CONTROL_OPERATORS if cmd.startswith(op, index)), None)
        matched_redirect = next((op for op in _REDIRECT_OPERATORS if cmd.startswith(op, index)), None)

        # "&>" is a redirect, not the "&" control operator, so redirects win when
        # they are the longer match.
        if matched_redirect and (not matched_control or len(matched_redirect) >= len(matched_control)):
            fd = ""
            if has_word and "".join(current).isdigit() and not current_subs:
                fd = "".join(current)
                current = []
                has_word = False
            flush()
            tokens.append(_Token(matched_redirect, "redirect", fd=fd))
            index += len(matched_redirect)
            continue

        if matched_control:
            flush()
            tokens.append(_Token(matched_control, "control"))
            index += len(matched_control)
            continue

        current.append(char)
        has_word = True
        index += 1

    flush()
    return tokens


def _build_segments(tokens: list[_Token]) -> list[Segment]:
    segments: list[Segment] = []

    argv: list[str] = []
    assignments: list[str] = []
    redirects: list[Redirect] = []
    substitutions: list[str] = []
    pending_redirect: _Token | None = None

    def close() -> None:
        nonlocal argv, assignments, redirects, substitutions, pending_redirect
        if pending_redirect is not None:
            # Redirect with no target, e.g. a trailing ">". Record it with an
            # empty target so it still counts as malformed rather than absent.
            redirects.append(Redirect(pending_redirect.text, "", pending_redirect.fd))
            pending_redirect = None
        if argv or assignments or redirects or substitutions:
            segments.append(
                Segment(
                    argv=argv,
                    assignments=assignments,
                    redirects=redirects,
                    substitutions=substitutions,
                )
            )
        argv = []
        assignments = []
        redirects = []
        substitutions = []

    for token in tokens:
        if pending_redirect is not None:
            if token.kind == "word":
                redirects.append(Redirect(pending_redirect.text, token.text, pending_redirect.fd))
                substitutions.extend(token.substitutions)
                pending_redirect = None
                continue
            redirects.append(Redirect(pending_redirect.text, "", pending_redirect.fd))
            pending_redirect = None

        if token.kind == "control":
            close()
            continue

        if token.kind == "redirect":
            pending_redirect = token
            continue

        substitutions.extend(token.substitutions)
        if not argv and _ASSIGNMENT.match(token.text):
            assignments.append(token.text)
            continue
        argv.append(token.text)

    close()
    return segments


def parse_command(cmd: str) -> ParsedCommand:
    """Parse ``cmd`` into segments.

    On any syntax the parser cannot resolve — an unterminated quote, an
    unbalanced ``$(`` — the result has ``ok=False`` so callers can fail closed
    rather than classify a command they did not actually understand.
    """
    try:
        tokens = _tokenize(cmd)
    except _ParseError as error:
        return ParsedCommand(segments=[], ok=False, error=str(error))

    return ParsedCommand(segments=_build_segments(tokens), ok=True)
