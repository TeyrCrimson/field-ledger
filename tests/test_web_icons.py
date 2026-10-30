"""Every hand-drawn icon is 16×16 and every letter in it has a colour: one letter off and
the board shows a lettered tile instead, so this catches it first. Needs `node`."""

import json
import shutil
import subprocess

import pytest

from field_ledger import hub

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def test_every_sprite_is_whole():
    check = ("import { SPRITES, problems } from './icons.js';"
             "console.log(JSON.stringify(Object.fromEntries("
             "Object.entries(SPRITES).map(([kind, s]) => [kind, problems(s)]))));")
    run = subprocess.run(["node", "--input-type=module", "-e", check], cwd=hub.WEB_DIR,
                         capture_output=True, text=True, check=True)
    found = json.loads(run.stdout)
    assert {"BAT", "CAM", "CAS", "build", "phone", "place", "VAN"} <= set(found)
    assert found == {kind: [] for kind in found}
