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
