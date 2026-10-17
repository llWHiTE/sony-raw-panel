"""Semantic comparison for Sony Imaging Edge development recipes.

The recipe format is an XML plist.  This module deliberately parses the small
plist subset itself rather than using ``plistlib`` because Sony writes decimal
real values with a comma in some locales.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET


_INTEGER = re.compile(r"[+-]?\d+\Z")
# Sony's locale-specific decimal separator is accepted, but mixing separators
# is rejected rather than guessed at.
_REAL = re.compile(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?\Z")
_SUPPORTED_SCALARS = {"string", "integer", "real", "true", "false", "data", "date"}


class RecipeParseError(ValueError):
    """Raised when a recipe is malformed or cannot be compared safely."""


def _text(element: ET.Element) -> str:
    """Return scalar text, rejecting non-plist scalar syntax."""
    if element.attrib:
        raise RecipeParseError(f"<{element.tag}> must not have attributes")
    if len(element):
        raise RecipeParseError(f"<{element.tag}> must not contain child elements")
    return element.text or ""


def _decimal(value: str) -> str:
    value = value.strip()
    if not _REAL.fullmatch(value):
        raise RecipeParseError(f"Invalid plist real value: {value!r}")
    if value.count(",") > 1 or value.count(".") > 1 or ("," in value and "." in value):
        raise RecipeParseError(f"Ambiguous plist real value: {value!r}")
    try:
        number = Decimal(value.replace(",", "."))
    except InvalidOperation as error:
        raise RecipeParseError(f"Invalid plist real value: {value!r}") from error
    if not number.is_finite():
        raise RecipeParseError(f"Non-finite plist real value: {value!r}")
    if not number:
        return "0"
    return format(number.normalize(), "f")


def _parse_value(element: ET.Element) -> Any:
    tag = element.tag
    if tag in {"dict", "array"} and element.attrib:
        raise RecipeParseError(f"<{tag}> must not have attributes")
    if tag == "dict":
        children = list(element)
        if len(children) % 2:
            raise RecipeParseError("plist dictionary has an unpaired key or value")
        values: dict[str, Any] = {}
        for index in range(0, len(children), 2):
            key, value = children[index], children[index + 1]
            if key.tag != "key":
                raise RecipeParseError("plist dictionary entries must begin with <key>")
            name = _text(key)
            if name in values:
                raise RecipeParseError(f"Duplicate plist dictionary key: {name!r}")
            values[name] = _parse_value(value)
        # A tagged tuple prevents dict and array/scalar values from colliding
        # during canonical serialization.
        return ("dict", tuple(sorted(values.items())))
    if tag == "array":
        return ("array", tuple(_parse_value(child) for child in element))
    if tag == "integer":
        value = _text(element).strip()
        if not _INTEGER.fullmatch(value):
            raise RecipeParseError(f"Invalid plist integer value: {value!r}")
        return ("integer", str(int(value, 10)))
    if tag == "real":
        return ("real", _decimal(_text(element)))
    if tag in ("true", "false"):
        if _text(element).strip():
            raise RecipeParseError(f"<{tag}> must be empty")
        return (tag, None)
    if tag in _SUPPORTED_SCALARS:
        # Data and date are deliberately treated as typed literal values.  The
        # XML representation's surrounding whitespace is insignificant there;
        # their internal data/date syntax remains substantive.
        value = _text(element)
        if tag in ("data", "date"):
            value = "".join(value.split())
        return (tag, value)
    raise RecipeParseError(f"Unsupported plist element: <{tag}>")


def _development_parameters(path: str | Path) -> Any:
    """Parse and return the typed, canonical DevelopmentParameters value."""
    try:
        source = Path(path).read_bytes()
        # ElementTree supports internal entities.  Recipes do not need a DTD,
        # so refuse one before parsing instead of accepting entity expansion.
        if b"<!DOCTYPE" in source.upper() or b"<!ENTITY" in source.upper():
            raise RecipeParseError("Recipe must not contain a DTD or entity declaration")
        root = ET.fromstring(source)
    except RecipeParseError:
        raise
    except (OSError, ET.ParseError) as error:
        raise RecipeParseError(f"Cannot parse recipe {path!s}") from error
    if root.tag != "plist":
        raise RecipeParseError("Recipe root must be <plist>")
    roots = list(root)
    if len(roots) != 1 or roots[0].tag != "dict":
        raise RecipeParseError("plist must contain exactly one top-level dictionary")
    document = _parse_value(roots[0])
    entries = dict(document[1])
    try:
        parameters = entries["DevelopmentParameters"]
    except KeyError as error:
        raise RecipeParseError("Recipe does not contain DevelopmentParameters") from error
    if parameters[0] != "dict":
        raise RecipeParseError("DevelopmentParameters must be a dictionary")
    return parameters


def recipe_fingerprint(path: str | Path) -> str:
    """Return a SHA-256 fingerprint of the semantic DevelopmentParameters tree.

    XML formatting, dictionary ordering, and equivalent decimal spelling do
    not affect this value.  Malformed input raises :class:`RecipeParseError`.
    """
    canonical = _development_parameters(path)
    encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def recipes_equal(pathA: str | Path, pathB: str | Path) -> bool:
    """Return whether two recipes have semantically identical parameters.

    Parsing errors intentionally propagate: treating unparseable recipes as
    equal could cause an edited recipe to be silently discarded.
    """
    return recipe_fingerprint(pathA) == recipe_fingerprint(pathB)
