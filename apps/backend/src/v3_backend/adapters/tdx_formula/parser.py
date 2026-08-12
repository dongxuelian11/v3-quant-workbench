from __future__ import annotations

from dataclasses import dataclass

from v3_backend.provenance.canonical_hash import canonical_sha256


class TdxFormulaError(ValueError):
    def __init__(self, code: str, detail: str, position: int | None = None) -> None:
        self.code = code
        self.position = position
        suffix = "" if position is None else f" at {position}"
        super().__init__(f"{code}{suffix}: {detail}")


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    text: str
    position: int


@dataclass(frozen=True, slots=True)
class NumberExpression:
    text: str

    def to_wire(self) -> dict[str, object]:
        return {"expression_type": "NUMBER", "text": self.text}


@dataclass(frozen=True, slots=True)
class IdentifierExpression:
    name: str

    def to_wire(self) -> dict[str, object]:
        return {"expression_type": "IDENTIFIER", "name": self.name}


@dataclass(frozen=True, slots=True)
class UnaryExpression:
    operator: str
    operand: TdxExpression

    def to_wire(self) -> dict[str, object]:
        return {"expression_type": "UNARY", "operator": self.operator, "operand": self.operand.to_wire()}


@dataclass(frozen=True, slots=True)
class BinaryExpression:
    operator: str
    left: TdxExpression
    right: TdxExpression

    def to_wire(self) -> dict[str, object]:
        return {
            "expression_type": "BINARY",
            "operator": self.operator,
            "left": self.left.to_wire(),
            "right": self.right.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class CallExpression:
    function_name: str
    arguments: tuple[TdxExpression, ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "expression_type": "CALL",
            "function_name": self.function_name,
            "arguments": [value.to_wire() for value in self.arguments],
        }


TdxExpression = NumberExpression | IdentifierExpression | UnaryExpression | BinaryExpression | CallExpression


@dataclass(frozen=True, slots=True)
class FormulaStatement:
    statement_kind: str
    name: str | None
    expression: TdxExpression
    drawing_metadata: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "statement_kind": self.statement_kind,
            "name": self.name,
            "expression": self.expression.to_wire(),
            "drawing_metadata": list(self.drawing_metadata),
        }


@dataclass(frozen=True, slots=True)
class ParsedTdxProgram:
    statements: tuple[FormulaStatement, ...]
    ast_digest: str

    @classmethod
    def create(cls, statements: tuple[FormulaStatement, ...]) -> ParsedTdxProgram:
        if not statements:
            raise TdxFormulaError("TDX_PARSE_ERROR", "script must contain statements")
        return cls(statements, "tdx_ast_sha256_" + canonical_sha256([value.to_wire() for value in statements]))

    @property
    def declared_names(self) -> tuple[str, ...]:
        return tuple(value.name for value in self.statements if value.name is not None)


_TWO_CHAR = {":=": "ASSIGN", ">=": "GTE", "<=": "LTE", "!=": "NE", "<>": "NE"}
_ONE_CHAR = {
    ":": "OUTPUT",
    ";": "SEMI",
    ",": "COMMA",
    "(": "LPAREN",
    ")": "RPAREN",
    "+": "PLUS",
    "-": "MINUS",
    "*": "STAR",
    "/": "SLASH",
    ">": "GT",
    "<": "LT",
    "=": "EQ",
}


def _tokenize(source: str) -> tuple[Token, ...]:
    tokens: list[Token] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            index = len(source) if end < 0 else end + 1
            continue
        if char == "{":
            end = source.find("}", index + 1)
            if end < 0:
                raise TdxFormulaError("TDX_PARSE_ERROR", "unterminated block comment", index)
            index = end + 1
            continue
        pair = source[index : index + 2]
        if pair in _TWO_CHAR:
            tokens.append(Token(_TWO_CHAR[pair], pair, index))
            index += 2
            continue
        if char in _ONE_CHAR:
            tokens.append(Token(_ONE_CHAR[char], char, index))
            index += 1
            continue
        if char.isdigit() or (char == "." and index + 1 < len(source) and source[index + 1].isdigit()):
            start = index
            dots = 0
            while index < len(source) and (source[index].isdigit() or source[index] == "."):
                dots += source[index] == "."
                index += 1
            if dots > 1:
                raise TdxFormulaError("TDX_PARSE_ERROR", "malformed numeric literal", start)
            tokens.append(Token("NUMBER", source[start:index], start))
            continue
        if char.isalpha() or char == "_" or ord(char) > 127:
            start = index
            index += 1
            while index < len(source):
                observed = source[index]
                if not (observed.isalnum() or observed == "_" or ord(observed) > 127):
                    break
                index += 1
            text = source[start:index]
            upper = text.upper()
            tokens.append(Token(upper if upper in {"AND", "OR", "NOT"} else "IDENT", text, start))
            continue
        raise TdxFormulaError("TDX_PARSE_ERROR", f"unsupported character {char!r}", index)
    tokens.append(Token("EOF", "", len(source)))
    return tuple(tokens)


class TdxParser:
    parser_version = "v3-tdx-parser/1.0.0"

    def parse(self, source: str) -> ParsedTdxProgram:
        self._tokens = _tokenize(source)
        self._index = 0
        statements: list[FormulaStatement] = []
        names: set[str] = set()
        while self._peek().kind != "EOF":
            statement = self._statement()
            if statement.name is not None:
                normalized = statement.name.upper()
                if normalized in names:
                    raise TdxFormulaError("TDX_PARSE_ERROR", f"duplicate declaration {statement.name}")
                names.add(normalized)
            statements.append(statement)
        return ParsedTdxProgram.create(tuple(statements))

    def _peek(self, offset: int = 0) -> Token:
        return self._tokens[min(self._index + offset, len(self._tokens) - 1)]

    def _take(self, kind: str) -> Token:
        token = self._peek()
        if token.kind != kind:
            raise TdxFormulaError("TDX_PARSE_ERROR", f"expected {kind}, observed {token.kind}", token.position)
        self._index += 1
        return token

    def _statement(self) -> FormulaStatement:
        if self._peek().kind == "IDENT" and self._peek(1).kind in {"ASSIGN", "OUTPUT"}:
            name = self._take("IDENT").text
            marker = self._peek().kind
            self._index += 1
            expression = self._or()
            metadata: list[str] = []
            if marker == "OUTPUT":
                while self._peek().kind == "COMMA":
                    self._take("COMMA")
                    metadata.append(self._take("IDENT").text.upper())
            self._take("SEMI")
            return FormulaStatement("INTERMEDIATE" if marker == "ASSIGN" else "NAMED_OUTPUT", name, expression, tuple(metadata))
        expression = self._or()
        self._take("SEMI")
        return FormulaStatement("EXPRESSION", None, expression)

    def _or(self) -> TdxExpression:
        value = self._and()
        while self._peek().kind == "OR":
            self._index += 1
            value = BinaryExpression("OR", value, self._and())
        return value

    def _and(self) -> TdxExpression:
        value = self._comparison()
        while self._peek().kind == "AND":
            self._index += 1
            value = BinaryExpression("AND", value, self._comparison())
        return value

    def _comparison(self) -> TdxExpression:
        value = self._additive()
        if self._peek().kind in {"GT", "GTE", "LT", "LTE", "EQ", "NE"}:
            operator = self._peek().kind
            self._index += 1
            value = BinaryExpression(operator, value, self._additive())
        return value

    def _additive(self) -> TdxExpression:
        value = self._multiplicative()
        while self._peek().kind in {"PLUS", "MINUS"}:
            operator = self._peek().kind
            self._index += 1
            value = BinaryExpression("+" if operator == "PLUS" else "-", value, self._multiplicative())
        return value

    def _multiplicative(self) -> TdxExpression:
        value = self._unary()
        while self._peek().kind in {"STAR", "SLASH"}:
            operator = self._peek().kind
            self._index += 1
            value = BinaryExpression("*" if operator == "STAR" else "/", value, self._unary())
        return value

    def _unary(self) -> TdxExpression:
        if self._peek().kind in {"NOT", "MINUS"}:
            operator = self._peek().kind
            self._index += 1
            return UnaryExpression("NOT" if operator == "NOT" else "-", self._unary())
        return self._primary()

    def _primary(self) -> TdxExpression:
        token = self._peek()
        if token.kind == "NUMBER":
            self._index += 1
            return NumberExpression(token.text)
        if token.kind == "IDENT":
            self._index += 1
            if self._peek().kind != "LPAREN":
                return IdentifierExpression(token.text)
            self._take("LPAREN")
            arguments: list[TdxExpression] = []
            if self._peek().kind != "RPAREN":
                arguments.append(self._or())
                while self._peek().kind == "COMMA":
                    self._take("COMMA")
                    arguments.append(self._or())
            self._take("RPAREN")
            return CallExpression(token.text.upper(), tuple(arguments))
        if token.kind == "LPAREN":
            self._index += 1
            value = self._or()
            self._take("RPAREN")
            return value
        raise TdxFormulaError("TDX_PARSE_ERROR", f"unexpected token {token.kind}", token.position)
