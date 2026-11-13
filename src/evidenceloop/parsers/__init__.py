"""Parsers that turn raw artifacts into bounded summaries."""

from .gtest import parse_gtest
from .tombstone import parse_tombstone

__all__ = ["parse_gtest", "parse_tombstone"]
