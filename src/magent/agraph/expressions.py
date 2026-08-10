"""Strict AGX parser and evaluator with no host-language evaluation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


class AgxEvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


_TOKEN = re.compile(
    r"\s*(?:(?P<number>\d+\.\d+|\d+)|(?P<string>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')|(?P<op>&&|\|\||==|!=|<=|>=|[-+*/%<>!()\[\],.])|(?P<name>[A-Za-z_][A-Za-z0-9_]*))"
)
_PRECEDENCE = {"or": 1, "||": 1, "and": 2, "&&": 2, "in": 3, "==": 4, "!=": 4, "<": 5, "<=": 5, ">": 5, ">=": 5, "+": 6, "-": 6, "*": 7, "/": 7, "%": 7}
_TEMPLATE = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)


def _tokens(text: str) -> list[_Token]:
    result: list[_Token] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match:
            raise AgxEvaluationError(f"unexpected character {text[pos]!r} at offset {pos}")
        pos = match.end()
        kind = next(name for name in ("number", "string", "op", "name") if match.group(name) is not None)
        result.append(_Token(kind, str(match.group(kind))))
    return result


class _Parser:
    def __init__(self, text: str, scope: dict[str, Any]):
        self.tokens = _tokens(text)
        self.scope = scope
        self.pos = 0
        # >0 while parsing a short-circuited branch: the tokens must be
        # consumed, but nothing in them may raise or be evaluated.
        self._suppress = 0

    def parse(self) -> Any:
        value = self.expression(0)
        if self.pos != len(self.tokens):
            raise AgxEvaluationError(f"trailing input at {self.tokens[self.pos].value!r}")
        return value

    def expression(self, minimum: int) -> Any:
        left = self.unary()
        while self.pos < len(self.tokens):
            token = self.tokens[self.pos]
            op = token.value
            if token.kind == "name" and op not in {"and", "or", "in"}:
                break
            precedence = _PRECEDENCE.get(op)
            if precedence is None or precedence < minimum:
                break
            self.pos += 1

            # Short-circuit: the idiomatic guard
            #   failed("build") && nodes.build.outputs.log == ""
            # raised when `build` had no outputs, because both sides were
            # always evaluated. The right side is still *parsed* (the token
            # stream must advance) but not evaluated.
            if op in {"and", "&&", "or", "||"} and self._suppress == 0:
                _require_bool(left)
                decided = (op in {"and", "&&"} and not left) or (op in {"or", "||"} and left)
                if decided:
                    self._suppress += 1
                    try:
                        self.expression(precedence + 1)
                    finally:
                        self._suppress -= 1
                    continue

            right = self.expression(precedence + 1)
            if self._suppress:
                left = None
                continue
            left = _binary(op, left, right)
        return left

    def unary(self) -> Any:
        if self._match("!", "not"):
            value = self.unary()
            if self._suppress:
                return None
            _require_bool(value)
            return not value
        if self._match("-"):
            value = self.unary()
            if self._suppress:
                return None
            _require_number(value)
            return -value
        return self.primary()

    def primary(self) -> Any:
        token = self._take()
        if token.kind == "number":
            return float(token.value) if "." in token.value else int(token.value)
        if token.kind == "string":
            try:
                return json.loads(token.value) if token.value.startswith('"') else bytes(token.value[1:-1], "utf-8").decode("unicode_escape")
            except Exception as exc:
                raise AgxEvaluationError(f"invalid string literal: {exc}") from exc
        if token.value == "(":
            value = self.expression(0)
            self._expect(")")
            return value
        if token.value == "[":
            values: list[Any] = []
            if not self._peek("]"):
                values.append(self.expression(0))
                while self._match(","):
                    values.append(self.expression(0))
            self._expect("]")
            return values
        if token.kind != "name":
            raise AgxEvaluationError(f"unexpected token {token.value!r}")
        if token.value in {"true", "false", "null"}:
            return {"true": True, "false": False, "null": None}[token.value]
        if self._match("("):
            if token.value == "default":
                return self._default_call()
            args: list[Any] = []
            if not self._peek(")"):
                args.append(self.expression(0))
                while self._match(","):
                    args.append(self.expression(0))
            self._expect(")")
            if self._suppress:
                try:
                    return _call(token.value, args, self.scope)
                except AgxEvaluationError:
                    return None
            return _call(token.value, args, self.scope)
        parts = [token.value]
        while self._match("."):
            part = self._take()
            if part.kind != "name":
                raise AgxEvaluationError("expected identifier after '.'")
            parts.append(part.value)
        if self._suppress:
            try:
                return resolve_reference(self.scope, parts)
            except AgxEvaluationError:
                return None
        return resolve_reference(self.scope, parts)

    def _default_call(self) -> Any:
        """Evaluate the fallback lazily so an absent optional reference is recoverable."""
        missing = object()
        start = self.pos
        try:
            value = self.expression(0)
        except AgxEvaluationError:
            value = missing
            # The failed parse left `pos` somewhere inside the first argument,
            # so `default(a == 1, "fb")` reported "expected ',', found '=='".
            # Rewind and skip the whole argument properly.
            self.pos = start
            self._skip_argument()
        self._expect(",")
        fallback = self.expression(0)
        self._expect(")")
        return fallback if value is missing or value is None else value

    def _skip_argument(self) -> None:
        """Advance past one argument, honouring nesting, stopping at a top-level ','."""
        depth = 0
        while self.pos < len(self.tokens):
            token = self.tokens[self.pos]
            if token.value in {"(", "["}:
                depth += 1
            elif token.value in {")", "]"}:
                if depth == 0:
                    return
                depth -= 1
            elif token.value == "," and depth == 0:
                return
            self.pos += 1

    def _take(self) -> _Token:
        if self.pos >= len(self.tokens):
            raise AgxEvaluationError("unexpected end of expression")
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def _peek(self, value: str) -> bool:
        return self.pos < len(self.tokens) and self.tokens[self.pos].value == value

    def _match(self, *values: str) -> bool:
        if self.pos < len(self.tokens) and self.tokens[self.pos].value in values:
            self.pos += 1
            return True
        return False

    def _expect(self, value: str) -> None:
        if not self._match(value):
            found = self.tokens[self.pos].value if self.pos < len(self.tokens) else "end"
            raise AgxEvaluationError(f"expected {value!r}, found {found!r}")


def evaluate_expression(text: str, scope: dict[str, Any]) -> Any:
    return _Parser(text.strip(), scope).parse()


def resolve_reference(scope: dict[str, Any], path: str | list[str]) -> Any:
    parts = path.split(".") if isinstance(path, str) else path
    value: Any = scope
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise AgxEvaluationError(f"unknown reference {'.'.join(parts)!r}")
    return value


def resolve_value(value: Any, scope: dict[str, Any]) -> Any:
    if isinstance(value, str):
        matches = list(_TEMPLATE.finditer(value))
        if not matches:
            return value
        if len(matches) == 1 and matches[0].span() == (0, len(value)):
            return evaluate_expression(matches[0].group(1), scope)
        return _TEMPLATE.sub(lambda item: str(evaluate_expression(item.group(1), scope)), value)
    if isinstance(value, list):
        return [resolve_value(item, scope) for item in value]
    if isinstance(value, dict):
        return {key: resolve_value(item, scope) for key, item in value.items()}
    return value


def _binary(op: str, left: Any, right: Any) -> Any:
    if op in {"and", "&&", "or", "||"}:
        _require_bool(left)
        _require_bool(right)
        return left and right if op in {"and", "&&"} else left or right
    if op in {"==", "!="}:
        numeric = (
            isinstance(left, (int, float))
            and isinstance(right, (int, float))
            and not isinstance(left, bool)
            and not isinstance(right, bool)
        )
        if not numeric and left is not None and right is not None and type(left) is not type(right):
            raise AgxEvaluationError("AGX equality requires operands of the same type")
        return left == right if op == "==" else left != right
    if op == "in":
        if not isinstance(right, (list, str, dict)):
            raise AgxEvaluationError("right operand of 'in' must be a list, string, or object")
        return left in right
    if op in {"<", "<=", ">", ">="}:
        numeric = (
            isinstance(left, (int, float))
            and isinstance(right, (int, float))
            and not isinstance(left, bool)
            and not isinstance(right, bool)
        )
        if not numeric and (
            type(left) is not type(right)
            or not isinstance(left, (int, float, str))
            or isinstance(left, bool)
        ):
            raise AgxEvaluationError("AGX comparison requires same-type numbers or strings")
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]
    if op == "+" and isinstance(left, str) and isinstance(right, str):
        return left + right
    _require_number(left)
    _require_number(right)
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise AgxEvaluationError("division by zero")
        return left / right
    if op == "%":
        if right == 0:
            raise AgxEvaluationError("division by zero")
        return left % right
    raise AgxEvaluationError(f"unsupported operator {op!r}")


def _call(name: str, args: list[Any], scope: dict[str, Any]) -> Any:
    statuses = scope.get("_statuses", {})
    functions: dict[str, Any] = {
        "len": lambda value: len(value),
        "count": lambda value: len(value),
        "contains": lambda value, needle: needle in value,
        "startswith": lambda value, prefix: value.startswith(prefix),
        "endswith": lambda value, suffix: value.endswith(suffix),
        "lower": lambda value: value.lower(),
        "upper": lambda value: value.upper(),
        "trim": lambda value: value.strip(),
        "matches": lambda value, pattern: re.search(pattern, value) is not None,
        "split": lambda value, separator: value.split(separator),
        "join": lambda values, separator: separator.join(values),
        "int": int,
        "float": float,
        "bool": bool,
        "str": str,
        "json": json.loads,
        "get": lambda value, key, default=None: value.get(key, default),
        "any": lambda value: any(_checked_bools(value)),
        "all": lambda value: all(_checked_bools(value)),
        "succeeded": lambda node: statuses.get(node) == "succeeded",
        "failed": lambda node: statuses.get(node) == "failed",
        "skipped": lambda node: statuses.get(node) == "skipped",
        "output": lambda node, output: resolve_reference(scope, ["nodes", node, "outputs", output]),
    }
    function = functions.get(name)
    if function is None:
        raise AgxEvaluationError(f"unknown function {name!r}")
    try:
        return function(*args)
    except AgxEvaluationError:
        raise
    except Exception as exc:
        raise AgxEvaluationError(f"{name} failed: {exc}") from exc


def _require_bool(value: Any) -> None:
    if not isinstance(value, bool):
        raise AgxEvaluationError("AGX boolean operator requires booleans")


def _require_number(value: Any) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AgxEvaluationError("AGX arithmetic requires numbers")


def _checked_bools(values: Any) -> list[bool]:
    if not isinstance(values, list) or not all(isinstance(item, bool) for item in values):
        raise AgxEvaluationError("any/all require a list of booleans")
    return values
