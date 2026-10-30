"""Ready an AutoKit folder for SYNC 2: sound patch (both copies kept, hook added) and English.

Shared by tools/make_pack.py (first install) and `s2am job install AutoKit`.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

from .job import AUTOKIT_LANGS, AUTOKIT_MODULES, autokit_lang_file

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import patch_waveout  # noqa: E402

HOOK_SOURCE = Path("FullPack/SyncExtendedPack/Apps/Media/VideoPlayer_EN/WaveOutHooks.dll")


class PatchFailed(Exception):
    pass


def patch_folder(folder: Path, hook: Path) -> list[dict]:
    """Patch AutoKit's modules in ``folder``; returns what changed, with hashes."""
    changes = []
    for name in AUTOKIT_MODULES:
        module = folder / name
        original = module.read_bytes()
        try:
            patched = patch_waveout.patch(original, hook.read_bytes())
        except patch_waveout.PatchError as error:
            raise PatchFailed(f"{name}: {error}") from error
        # Both variants stay on the car so an s2am job can swap them for A/B tests.
        module.with_name(name + ".orig").write_bytes(original)
        module.with_name(name + ".patched").write_bytes(patched)
        module.write_bytes(patched)
        changes.append({"file": name, "original_sha256": hashlib.sha256(original).hexdigest(),
                        "patched_sha256": hashlib.sha256(patched).hexdigest()})
    shutil.copy2(hook, folder / patch_waveout.HOOK_DLL_NAME)
    changes.append({"file": patch_waveout.HOOK_DLL_NAME, "added_from": str(HOOK_SOURCE),
                    "sha256": hashlib.sha256(hook.read_bytes()).hexdigest()})
    # The stock `lang` file is 0x0804 (Chinese); start in English, keep the stock file as lang.orig.
    lang, english = folder / "lang", autokit_lang_file(AUTOKIT_LANGS["english"])
    if lang.is_file() and lang.read_bytes() != english:
        lang.with_name("lang.orig").write_bytes(lang.read_bytes())
    lang.write_bytes(english)
    changes.append({"file": "lang", "language": "english",
                    "sha256": hashlib.sha256(english).hexdigest()})
    return changes
