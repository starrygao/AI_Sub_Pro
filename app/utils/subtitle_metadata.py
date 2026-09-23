"""Remove transport headers accidentally embedded in extracted subtitle cues."""
import re


_TIMESTAMP_MAP = re.compile(
    r"X-TIMESTAMP-MAP\s*=\s*(?:"
    r"LOCAL:\d{2}:\d{2}:\d{2}\.\d{3},\s*MPEGTS:\d+|"
    r"MPEGTS:\d+,\s*LOCAL:\d{2}:\d{2}:\d{2}\.\d{3})"
)


def strip_subtitle_metadata(text: str) -> str:
    # Match whole header lines only; dialogue mentioning WebVTT is content.
    return "\n".join(
        line for line in text.splitlines()
        if line.strip().lstrip("\ufeff") != "WEBVTT"
        and not _TIMESTAMP_MAP.fullmatch(line.strip())
    )
