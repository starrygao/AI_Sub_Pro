import subprocess
import sys


def test_synthetic_phrase_pack_generator_is_up_to_date():
    result = subprocess.run(
        [sys.executable, "tools/phrase_packs/generate_synthetic_packs.py", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_synthetic_phrase_packs_cover_researched_content_profiles():
    from tools.phrase_packs.generate_synthetic_packs import build_packs

    packs = {pack["id"]: pack for pack in build_packs()}

    assert "ai-sub-pro.en-zh.domain_interview_documentary" in packs
    assert "ai-sub-pro.en-zh.domain_technical_tutorial" in packs
    assert "ai-sub-pro.ja-zh.domain_anime" in packs
    assert "ai-sub-pro.en-zh.domain_legal_adult" in packs
    assert any("first-title" in row["tags"] for row in packs[
        "ai-sub-pro.en-zh.domain_interview_documentary"
    ]["phrases"])
    assert any("code" in row["tags"] for row in packs[
        "ai-sub-pro.en-zh.domain_technical_tutorial"
    ]["phrases"])
    assert any("anime" in row["tags"] for row in packs[
        "ai-sub-pro.ja-zh.domain_anime"
    ]["phrases"])
    assert any("adult" in row["tags"] for row in packs[
        "ai-sub-pro.en-zh.domain_legal_adult"
    ]["phrases"])
