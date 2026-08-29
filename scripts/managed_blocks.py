#!/usr/bin/env python3
"""Strict helpers for allowlisted generated blocks in shared root files."""

from __future__ import annotations

from os.path import commonprefix


DB_HALO_SITEMAP_START = "  <!-- db-halo:start -->"
DB_HALO_SITEMAP_END = "  <!-- db-halo:end -->"
ALLOWLISTED_SITEMAP_BLOCKS = (
    ("dB Halo", DB_HALO_SITEMAP_START, DB_HALO_SITEMAP_END),
)


def exact_block_span(
    source: str,
    *,
    start_marker: str,
    end_marker: str,
    label: str,
) -> tuple[int, int] | None:
    """Return an exact whole-line marker span, rejecting ambiguous input."""

    start_token = start_marker.strip()
    end_token = end_marker.strip()
    start_count = source.count(start_token)
    end_count = source.count(end_token)
    marker_hint = commonprefix((start_token, end_token)).removeprefix(
        "<!--"
    ).strip()
    marker_like_count = source.casefold().count(marker_hint.casefold())
    if start_count == 0 and end_count == 0:
        if marker_like_count:
            raise ValueError(f"{label} contains an unrecognized marker")
        return None
    if start_count != 1 or end_count != 1:
        raise ValueError(
            f"{label} markers must each appear exactly once when present"
        )
    if marker_like_count != 2:
        raise ValueError(f"{label} contains an unrecognized marker")

    def line_bounds(token: str) -> tuple[int, int]:
        token_offset = source.index(token)
        line_start = source.rfind("\n", 0, token_offset) + 1
        line_end = source.find("\n", token_offset)
        if line_end == -1:
            line_end = len(source)
        return line_start, line_end

    start, start_line_end = line_bounds(start_token)
    end, block_end = line_bounds(end_token)
    if source[start:start_line_end] != start_marker:
        raise ValueError(f"{label} start marker must occupy its exact line")
    if source[end:block_end] != end_marker:
        raise ValueError(f"{label} end marker must occupy its exact line")
    if end <= start_line_end:
        raise ValueError(f"{label} markers are reversed or overlap")
    return start, block_end


def extract_allowlisted_sitemap_blocks(source: str) -> tuple[str, ...]:
    """Extract only explicitly allowlisted sitemap blocks, byte-for-byte."""

    blocks = []
    for label, start_marker, end_marker in ALLOWLISTED_SITEMAP_BLOCKS:
        span = exact_block_span(
            source,
            start_marker=start_marker,
            end_marker=end_marker,
            label=f"{label} sitemap block",
        )
        if span is not None:
            blocks.append(source[span[0] : span[1]])
    return tuple(blocks)
