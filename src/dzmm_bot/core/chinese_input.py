"""Traditional-Chinese input normalization for command routing."""

from collections.abc import Collection
import re
import unicodedata

from opencc import OpenCC


_T2S = OpenCC("t2s")
_COMMAND_CONTENT = re.compile(r"(?P<prefix>\s*)(?P<command>/\S+)(?P<suffix>.*)", re.DOTALL)


def traditional_to_simplified(value: str) -> str:
    return _T2S.convert(unicodedata.normalize("NFKC", value)).replace("揹", "背")


def canonicalize_command_name(value: str) -> str:
    return traditional_to_simplified(value)


def canonicalize_command_content(value: str) -> str:
    match = _COMMAND_CONTENT.fullmatch(value)
    if match is None:
        return value
    return (
        match["prefix"]
        + canonicalize_command_name(match["command"])
        + match["suffix"]
    )


def canonicalize_fixed_option(value: str, allowed: Collection[str]) -> str:
    canonical = traditional_to_simplified(value)
    return canonical if canonical in allowed else value
