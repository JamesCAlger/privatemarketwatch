"""Tracked files whose exact bytes are bound by a recorded sha256 must hash the same everywhere.

Git converts the line ends of text files (CRLF on Windows, LF on Linux) unless .gitattributes
marks them ``-text``. A hash recorded on one platform then fails on the other. These tests run
on every platform, so a hash-bound file committed without the attribute fails CI by name.
"""
import json
import shutil
import subprocess

import pytest

from pipeline import config, monetary_fx
from pipeline.programme.core import sha

FX_PACKAGE = config.PROJECT_ROOT / "data" / "reference" / "monetary_conversion"


def test_tracked_fx_package_passes_its_admission_and_source_hashes():
    """Admission manifest hash of quotes.json, then each quote's source-file hash."""
    loaded = monetary_fx.load_inputs(FX_PACKAGE)
    assert loaded["quotes"], "the tracked FX quotes were not admitted on this platform"
    sources = {q["source"]["path"] for q in loaded["quotes"]}
    for relative in sources:
        recorded = {q["source"]["sha256"] for q in loaded["quotes"] if q["source"]["path"] == relative}
        assert recorded == {sha(FX_PACKAGE / relative)}, relative


def test_files_named_in_the_fx_admission_manifest_are_never_line_end_converted():
    """Each admitted file, and each quote source, must carry the -text attribute in git."""
    if shutil.which("git") is None or not (config.PROJECT_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    manifest = json.loads((FX_PACKAGE / "admission_manifest.json").read_text(encoding="utf-8-sig"))
    quotes = json.loads((FX_PACKAGE / "quotes.json").read_text(encoding="utf-8-sig"))
    names = set(manifest["entries"]) | {q["source"]["path"] for q in quotes["quotes"]}
    names.add("admission_manifest.json")
    paths = sorted((FX_PACKAGE / n).relative_to(config.PROJECT_ROOT).as_posix() for n in names)
    result = subprocess.run(["git", "check-attr", "text", "--", *paths], cwd=config.PROJECT_ROOT,
                            capture_output=True, text=True, check=True, timeout=60)
    converted = [line for line in result.stdout.splitlines() if not line.endswith(": text: unset")]
    assert not converted, "add these to .gitattributes as -text: " + "; ".join(converted)


def _retired_records():
    """(retired file, recorded sha256) for every review record that names its file's original hash."""
    overrides = config.PROJECT_ROOT / "data" / "overrides"
    found = []
    for review in sorted(overrides.rglob("_retired_*.review.json")):
        recorded = json.loads(review.read_text(encoding="utf-8-sig")).get("original_sha256")
        retired = review.with_name(review.name[: -len(".review.json")] + ".json")
        if recorded and retired.is_file():
            found.append(pytest.param(retired, recorded, id=retired.relative_to(overrides).as_posix()))
    return found


@pytest.mark.parametrize("retired,recorded", _retired_records())
def test_every_retired_file_still_has_the_bytes_its_review_recorded(retired, recorded):
    """Some were recorded on CRLF bytes and some on LF; git must hand back whichever it was."""
    assert sha(retired) == recorded
