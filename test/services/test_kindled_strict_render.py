"""Regression checks for fail-closed media and rendered caption geometry."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from kindled_iron import insets


def event(n=0, **kw):
    return dict(do="draw", type="inset", id=f"cash{n}", sources=["pexels"],
                pin={"pexels": "5466769"}, **kw)


def test_missing_required_clip_names_id_and_pin(tmp_path):
    with patch.dict(insets.SEARCH, {"pexels": lambda *a: []}):
        with pytest.raises(SystemExit, match="cash0.*pexels:5466769"):
            insets.fetch({"strict_media": True, "beats": [{"events": [event()]}]}, tmp_path, lambda x: None)


def test_required_media_not_truncated_at_eight(tmp_path):
    events = [event(n, required=True) for n in range(9)]
    # First eight are supplied already; ninth must be attempted, not silently dropped.
    for e in events[:8]:
        e["frames"] = ["file:///already.jpg"]
    with patch.dict(insets.SEARCH, {"pexels": lambda *a: []}):
        with pytest.raises(SystemExit, match="cash8"):
            insets.fetch({"beats": [{"events": events}]}, tmp_path, lambda x: None)


def test_optional_legacy_media_still_optional(tmp_path):
    with patch.dict(insets.SEARCH, {"pexels": lambda *a: []}):
        assert insets.fetch({"beats": [{"events": [event()]}]}, tmp_path, lambda x: None) == {}


def test_required_media_rejects_unpinned_search(tmp_path):
    e = event(); e.pop("pin")
    with pytest.raises(SystemExit, match="pinned provider ID missing"):
        insets.fetch({"strict_media": True, "beats": [{"events": [e]}]}, tmp_path, lambda x: None)


@pytest.mark.parametrize("kind", ["inset", "scripture", "head", "safe", "band", "clear"])
def test_actual_runtime_collision_check(kind):
    runtime = Path("kindled_iron/runtime/runtime.js").read_text()
    start = runtime.index("  window.kiStrictCaptionCheck = function")
    end = runtime.index("  window.kiSeek = function", start)
    # Execute the exact runtime function with DOM-measured rectangle fixtures.
    setup = r"""
const window = {};
const D = {layoutZones:{captions:{left:120,top:1100,right:760,bottom:1440}}};
const capEl = {textContent:'MONEY',style:{visibility:'visible'}};
let rect={left:200,top:1200,right:500,bottom:1300};
let heads=[]; const objs={};
function capRect(){return rect;}
function shown(){return true;}
function getComputedStyle(){return {opacity:"1"};}
function headBoxes(){return heads;}
"""
    touch = "{left:508,top:1200,right:600,bottom:1300}"  # stroke touches inclusive edge
    if kind in ("inset", "scripture"):
        setup += f"objs.x={{def:{{type:{json.dumps(kind)}}},el:{{getAttribute:()=>null,getBoundingClientRect:()=>({touch})}}}};"
    elif kind == "head":
        setup += f"heads=[{touch}];"
    elif kind == "safe":
        setup += "rect.left=120;"  # glyph stroke extends beyond safe box
    elif kind == "band":
        setup += "rect.top=1000;"
    js = setup + runtime[start:end] + "console.log(JSON.stringify(window.kiStrictCaptionCheck()));"
    issues = json.loads(subprocess.check_output(["node", "-e", js], text=True))
    assert bool(issues) == (kind != "clear"), issues


def test_strict_layout_checks_every_frame_and_saves_half_second_samples(tmp_path):
    from kindled_iron.render import layout_check
    class Page:
        def __init__(self): self.times = []; self.images = []
        def evaluate(self, expr, arg=None):
            if expr.startswith("Boolean"): return True
            if expr.startswith("async"):
                self.times.append(arg); return []
            return []
        def screenshot(self, path, **kwargs): self.images.append(path)
        def reload(self): pass
        def wait_for_function(self, *a, **kw): pass
    page = Page()
    layout_check(page, 1.0, tmp_path)
    assert page.times == [f / 30 for f in range(30)]
    assert len(page.images) == 2
    result = json.loads((tmp_path / "strict_layout.json").read_text())
    assert result["passed"] and result["frames_checked"] == 30
    assert [s["time"] for s in result["review_samples"]] == [0, .5]


def test_instant_frame_still_initializes_movie_playback():
    runtime = Path("kindled_iron/runtime/runtime.js").read_text()
    start = runtime.index("  function addDraw(e)")
    end = runtime.index("  D.events.forEach(function (e)", start)
    setup = """
    const ob = {def:{type:'inset',display_dur:8,clip_dur:3},el:{},inner:{},strokes:[],fills:[]};
    const objs = {cash:ob}; const D={strictLayout:true};
    const tl={set(){},to(){},fromTo(){}};
    """
    js = setup + runtime[start:end] + "addDraw({id:'cash',t:2,instant:true}); console.log(JSON.stringify([ob.t0,ob.t1]));"
    assert json.loads(subprocess.check_output(["node","-e",js],text=True)) == [2,10]


def test_required_clip_visible_at_frame_zero_and_through_long_line():
    runtime = Path("kindled_iron/runtime/runtime.js").read_text()
    start = runtime.index("  function strictInsetVisibility(ob, t)")
    end = runtime.index("  function renderObjects(t)", start)
    setup = """
    const D={strictLayout:true}; const attrs={};
    const ob={def:{type:'inset',required:true},t0:0,t1:12,
      el:{style:{},setAttribute(k,v){attrs[k]=v;}},strokes:[],fills:[]};
    """
    js = setup + runtime[start:end] + """
    let states=[];
    for (const t of [0,3,6,11.99,12]) { strictInsetVisibility(ob,t); states.push([attrs.visibility,ob.el.style.opacity]); }
    console.log(JSON.stringify(states));
    """
    states=json.loads(subprocess.check_output(["node","-e",js],text=True))
    assert states == [["visible","1"]]*4 + [["hidden","0"]]
