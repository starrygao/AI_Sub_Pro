"""
Text cleaning, filtering, and language utilities.
"""
import re
from typing import List, Set

# Common Japanese interjections / moans / exclamations
JA_INTERJECTIONS: Set[str] = {
    "あっ", "ああ", "あぁ", "あー", "あーっ", "ああっ",
    "うーん", "んん", "んー", "んっ", "んんっ", "んあ", "んああ",
    "ええ", "えっ", "えー", "えーっ",
    "おっ", "おお", "おーい",
    "いやっ", "いやー", "いやぁ",
    "はぁ", "はあ", "はぁっ", "はあっ",
    "ふぅ", "ふう", "ふっ",
    "きゃ", "きゃっ", "きゃー",
    "あ", "え", "う", "お",
}

# Common English interjections
EN_INTERJECTIONS: Set[str] = {
    "oh", "ah", "uh", "um", "hmm", "mm", "ooh", "aah",
    "wow", "huh", "whoa",
}

# SDH / sound effect patterns
SDH_PATTERNS = [
    re.compile(r"\[.*?\]"),          # [music playing]
    re.compile(r"\(.*?\)"),          # (laughing)
    re.compile(r"<.*?>"),            # <i>tags</i>
    re.compile(r"♪.*?♪"),           # ♪ music ♪
    re.compile(r"♫.*?♫"),
    re.compile(r"^[\s\-\.]*[A-Z][A-Z0-9\s\.\-]+:"),  # SPEAKER NAME:
]

# Garbage-only strings
GARBAGE = {"-", ":", ".", "!", "?", "—", "…", "...", "♪", "♫", "~",
           "，", "。", "！", "？", "—", "……", "。。。"}


def clean_sdh(text: str) -> str:
    """Remove SDH tags, speaker labels, HTML tags."""
    if not isinstance(text, str) or not text:
        return ""
    for pat in SDH_PATTERNS:
        text = pat.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in GARBAGE:
        return ""
    return text


def is_interjection(text: str, language: str = "ja") -> bool:
    """Check if text is a short interjection/exclamation."""
    if not isinstance(text, str):
        return True
    clean = text.strip().rstrip("。！？!?.…~♪♫")
    if not clean:
        return True
    lang = language.lower() if isinstance(language, str) else ""
    is_ja = lang.startswith("ja")
    is_en = lang.startswith("en")
    pool = JA_INTERJECTIONS if is_ja else EN_INTERJECTIONS if is_en else set()
    lookup = clean if is_ja else clean.lower()
    # Direct match
    if lookup in pool:
        return True
    # Single Chinese characters ("我", "是") and English words ("I", "a") can
    # be meaningful subtitles. Only treat single-character Japanese kana as
    # filler when it did not already match the explicit pool above.
    if len(clean) <= 1:
        return is_ja and any("\u3040" <= c <= "\u30FF" for c in clean)
    if not (is_ja or is_en):
        return False
    # Repeated single char pattern: ああああ, おおお
    if len(clean) >= 3 and len(set(clean.lower())) <= 2 and len(clean) <= 8:
        return True
    # Japanese: katakana-only short strings are often sound effects
    if is_ja and len(clean) <= 4:
        if all("\u30A0" <= c <= "\u30FF" or c in "ーッ" for c in clean):
            return True
    return False


def detect_repetitive(texts: List[str], threshold: int = 3) -> Set[str]:
    """Find texts that appear >= threshold times (case-insensitive)."""
    from collections import Counter
    counts = Counter(t.strip().lower() for t in texts if isinstance(t, str) and t.strip())
    return {t for t, c in counts.items() if c >= threshold}


def clean_for_translation(text: str) -> str:
    """Clean text for sending to translation API."""
    text = clean_sdh(text)
    # Remove excessive punctuation
    text = re.sub(r"[\.]{3,}", "…", text)
    text = re.sub(r"[!]{2,}", "!", text)
    text = re.sub(r"[?]{2,}", "?", text)
    return text.strip()


def detect_language_hint(texts: List[str]) -> str:
    """Simple language detection from subtitle text samples."""
    ja_count = 0
    en_count = 0
    zh_count = 0
    sample = " ".join(t for t in texts[:50] if isinstance(t, str))

    for c in sample:
        if "\u3040" <= c <= "\u309F" or "\u30A0" <= c <= "\u30FF":
            ja_count += 1
        elif "\u4E00" <= c <= "\u9FFF":
            zh_count += 1
        elif "a" <= c.lower() <= "z":
            en_count += 1

    total = ja_count + en_count + zh_count
    if total == 0:
        return "auto"
    if ja_count / total > 0.3:
        return "ja"
    if zh_count / total > 0.3:
        return "zh"
    return "en"
