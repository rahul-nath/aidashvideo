"""``LiteralText``: text that is always data (contracts §2).

Limited to Unicode categories L, M, N, P, S and Zs plus newline; bidi controls and every
other control/format character are refused at construction, so a caption or title can
never carry shell text, XML or direction overrides into a later adapter.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from aidashvideo.ledger.errors import ContractError, is_str

_ALLOWED_MAJOR = frozenset({"L", "M", "N", "P", "S"})
MAX_LITERAL_TEXT = 10_000


@dataclass(frozen=True, slots=True)
class LiteralText:
    text: str

    def __post_init__(self) -> None:
        if not is_str(self.text):
            raise ContractError("LiteralText must be a string")
        if len(self.text) > MAX_LITERAL_TEXT:
            raise ContractError(f"LiteralText longer than {MAX_LITERAL_TEXT} characters")
        for index, char in enumerate(self.text):
            if char == "\n":
                continue
            category = unicodedata.category(char)
            if category == "Zs" or category[0] in _ALLOWED_MAJOR:
                continue
            raise ContractError(
                f"LiteralText: character U+{ord(char):04X} ({category}) at {index} is not allowed"
            )

    @classmethod
    def make(cls, text: str) -> LiteralText:
        return cls(text)

    def to_json(self) -> str:
        return self.text

    @classmethod
    def from_json(cls, raw: object) -> LiteralText:
        if not isinstance(raw, str):
            raise ContractError("LiteralText: expected a string")
        return cls(raw)
