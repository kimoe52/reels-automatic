from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "motion_effects.py"
spec = importlib.util.spec_from_file_location("motion_effects", MODULE)
motion_effects = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(motion_effects)


def test_legacy_and_new_effects_are_supported_and_bounded() -> None:
    required = {"", "settle_fade", "rise_fade", "slide_left", "slide_right", "scale_pop", "reveal", "fade",
                "wipe_up", "wipe_down", "iris_reveal", "spring_settle", "bounce_settle", "path_arc", "gentle_tilt", "stepped_reveal"}
    assert required <= set(motion_effects.EFFECTS)
    assert all(0 < motion_effects.duration_ms(effect) <= 600 for effect in motion_effects.EFFECTS)
    assert motion_effects.duration_ms("unrecognised") <= 600


def test_choice_is_deterministic_and_role_safe() -> None:
    canvas = (1080, 1350)
    args = ("character", (100, 400, 380, 600), canvas, 2, 3)
    assert motion_effects.choose_effect(*args) == motion_effects.choose_effect(*args)
    assert motion_effects.choose_effect(*args) in {"rise_fade", "slide_left", "slide_right", "gentle_tilt"}
    assert motion_effects.choose_effect("title", (80, 100, 880, 150), canvas, 1, 0) in {"reveal", "wipe_up", "stepped_reveal"}
    assert motion_effects.choose_effect("panel", (30, 500, 1000, 200), canvas, 1, 0) in {"wipe_up", "wipe_down", "reveal"}
    assert motion_effects.choose_effect("prop", (700, 620, 120, 120), canvas, 1, 0) in {"bounce_settle", "path_arc", "iris_reveal"}


def test_choice_rejects_impossible_geometry() -> None:
    try:
        motion_effects.choose_effect("title", (0, 0, 0, 40), (1080, 1350))
    except ValueError:
        pass
    else:
        raise AssertionError("zero-sized source crop must be rejected")


class MotionEffectsTest(unittest.TestCase):
    def test_catalog(self):
        test_legacy_and_new_effects_are_supported_and_bounded()

    def test_roles(self):
        test_choice_is_deterministic_and_role_safe()

    def test_geometry(self):
        test_choice_rejects_impossible_geometry()

    def test_browser_catalog_matches_and_all_effects_end_exactly(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        script = """
const fs = require('fs'), vm = require('vm');
const window = {};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {window});
const effects = window.CardMotionEffects, results = [];
for (const effect of effects.EFFECTS) {
  const events = [], target = {};
  const timeline = {set:(t,v,at)=>{v.duration=0;const {duration,...clean}=v;events.push({kind:'set',v:clean,at});},
    fromTo:(t,f,v,at)=>events.push({kind:'tween',f,v,at})};
  effects.animate(timeline,target,{effect},0);
  results.push({effect,duration:effects.durationMs(effect),end:events.at(-1)});
}
process.stdout.write(JSON.stringify(results));
"""
        rows = json.loads(subprocess.check_output(
            [node,"-e",script,str(MODULE.with_suffix(".js"))],text=True))
        self.assertEqual({row["effect"] for row in rows},set(motion_effects.EFFECTS))
        for row in rows:
            self.assertEqual(row["duration"],motion_effects.duration_ms(row["effect"]))
            self.assertLessEqual(row["end"]["at"],.6)
            self.assertEqual(row["end"]["v"], {"opacity":1,"x":0,"y":0,
                "scale":1,"rotation":0,"clipPath":"inset(0 0% 0 0)"})
