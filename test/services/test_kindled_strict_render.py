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
    const window={}; const D={strictLayout:true}; const attrs={};
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


def test_typewriter_starts_every_spoken_word_and_finishes_by_seventy_percent():
    from kindled_iron.render import scripture_card
    from kindled_iron.pacing import words_of
    quote='For the love of money is a root of all kinds of evil.'
    ws=[dict(word=w,start=2+i*.4,end=2+(i+1)*.4) for i,w in enumerate(words_of(quote))]
    o,_=scripture_card({'scripture':{'ref':'1 Timothy 6:10','text':quote}},ws,0,0,'test')
    runtime=Path('kindled_iron/runtime/runtime.js').read_text()
    a=runtime.index('  window.kiTypedCount=function');b=runtime.index('  function renderTypewriter',a)
    times=o['word_times'];mid=(times[0]['start']+times[-1]['end'])/2
    probes=[mid]+[w['start'] for w in times]+[w['start']+.7*(w['end']-w['start']) for w in times]
    js='const window={};'+runtime[a:b]+'console.log(JSON.stringify('+json.dumps(probes)+'.map(t=>window.kiTypedCount('+json.dumps(times)+',t))));'
    counts=json.loads(subprocess.check_output(['node','-e',js],text=True))
    assert abs(sum(w['end_char']<=counts[0] for w in times)-sum(w['end']<=mid for w in times))<=1
    for i,w in enumerate(times):
        assert w['start_char']<counts[1+i]<=w['end_char']
        assert counts[1+len(times)+i]==w['end_char']
    # Across the quote, every word already started must have begun typing;
    # words remain letter-by-letter until their 70% deadline.
    samples=[times[0]['start']+i*.013 for i in range(int((times[-1]['end']-times[0]['start'])/.013)+1)]
    js='const window={};'+runtime[a:b]+'console.log(JSON.stringify('+json.dumps(samples)+'.map(t=>window.kiTypedCount('+json.dumps(times)+',t))));'
    values=json.loads(subprocess.check_output(['node','-e',js],text=True))
    for t,count in zip(samples,values):
        for w in times:
            if t>=w['start']:
                assert count>w['start_char']
            if t>=w['start']+.7*(w['end']-w['start'])+1e-8:
                assert count>=w['end_char']


def test_verse_pages_fit_requested_clip_zone_without_shrinking_below_64():
    from kindled_iron.render import scripture_card
    from kindled_iron.pacing import words_of
    from kindled_iron.scripture import verse_text
    quote=verse_text('Hebrews 13:5')
    ws=[dict(word=w,start=i*.4,end=(i+1)*.4) for i,w in enumerate(words_of(quote))]
    o,_=scripture_card({'scripture':{'ref':'Hebrews 13:5','text':quote},'size':92,'min_size':64,'w':780,'fit_height':440},ws,0,0,'test')
    assert 64<=o['size']<=92
    n=o['page_lines'] or len(o['lines'])
    assert 92+n*o['size']*1.08+min(64,round(o['size']*.62))*1.5<=440
    boundary=o['page_break']
    assert ' '.join(o['lines'][:boundary['line']]) == 'Be free from the love of money, content with such things as you have,'
    assert ' '.join(o['lines'][boundary['line']:]).startswith('for he has said,')
    assert boundary['time']==ws[13]['end']
    assert o['line_pages']==[0]*4+[1]*4
    assert o['page_layouts'][0]['height']==max(220,92+4*64*1.08)
    assert o['page_layouts'][1]['height']>o['page_layouts'][0]['height']
    assert o['page_layouts'][0]['text_top']==-4*64*1.08/2


def test_verse_refuses_more_than_two_pages_instead_of_shrinking():
    from kindled_iron.render import scripture_card
    from kindled_iron.pacing import words_of
    quote=' '.join(['A long clause without a punctuation boundary']*20)+'.'
    ws=[dict(word=w,start=i*.4,end=(i+1)*.4) for i,w in enumerate(words_of(quote))]
    with pytest.raises(SystemExit,match='cannot fit in two punctuation-split pages'):
        scripture_card({'scripture':{'ref':'Hebrews 13:5','text':quote},'size':92,'min_size':64,'w':780,'fit_height':440},ws,0,0,'test')


def test_money_preview_starts_with_media_and_caption_and_verses_use_cards_only():
    from kindled_iron.money_preview import build
    scene,spans,words,duration=build('Walk away with ten thousand dollars right now, or tell the truth?\n\nFirst Timothy says, “For the love of money is a root of all kinds of evil.” [1 Timothy 6:10]\n\nBracketed references appear on screen and are not spoken.')
    assert spans[0][0]==0 and words[0][0]['start']==0
    assert scene['cast']['guide']['scale']==1.785
    assert scene['captions_box']['size']==92 and scene['captions_box']['w']==820
    assert scene['beats'][0]['captions']
    assert not scene['beats'][1]['captions']
    assert scene['beats'][1]['events'][1]['size']==64


def test_authored_memes_use_existing_rules_and_stock_varies(tmp_path):
    from kindled_iron.money_preview import build, CASH
    from kindled_iron import render,effects
    from kindled_iron.scripture import verse_text
    lines=['ordinary line']*27
    lines[4]='Runs great.';lines[15]='They should’ve checked.';lines[17]='Everybody does it.'
    for i,ref in [(12,'1 Timothy 6:10'),(21,'Proverbs 16:8'),(22,'Hebrews 13:5')]:
        quote=verse_text(ref).split('. ')[0]+'.' if i==12 else verse_text(ref)
        lines[i]=f'Paul says, “{quote}” [{ref}]'
    scene,spans,words,duration=build('\n\n'.join(lines+['Bracketed references appear on screen and are not spoken.']))
    pins=[e['pin']['pexels'] for beat in scene['beats'] for e in beat['events'] if e.get('type')=='inset']
    assert pins.count(CASH)==3 and all(a!=b for a,b in zip(pins,pins[1:]))
    assert not any(e.get('do')=='caption_lane' for b in scene['beats'] for e in b['events'])
    clips={e['id']:{'frames':['file:///test.jpg'],'fps':30} for b in scene['beats'] for e in b['events'] if e.get('type')=='inset'}
    data=render.build_data(scene,spans,words,duration,clips)
    def fake_card(emotion,t,dur,pos,work,n):
        return ({'id':f'react{n}','type':'inset'}, {'do':'draw','id':f'react{n}','t':t}, {'id':f'react{n}','origin':'test','emotion':emotion})
    with patch('kindled_iron.private_media.reaction_card',side_effect=fake_card) as provider:
        _,images=effects.apply_reaction_rules(data['events'],scene,spans,words,tmp_path,lambda _:None,data,True)
    reactions=[e for e in data['events'] if e['do']=='reaction']
    assert provider.call_count==len(images)==len(reactions)==3
    assert not any(e.get('_drop') for e in reactions)
    assert [e['emotion'] for e in reactions]==['surprised','confused','smart']
    assert all(0<e['dur']<1.5 for e in reactions)
    assert all(b['t']-a['t']>=3 for a,b in zip(reactions,reactions[1:]))
    for e in reactions:
        assert not any(e['t']<end and e['t']+e['dur']>start for (start,end),b in zip(spans,scene['beats']) if b.get('serious'))


def test_strict_original_voice_never_calls_another_provider(tmp_path):
    from kindled_iron import tts
    with patch.dict('os.environ',{'KI_TTS_CACHE':str(tmp_path)}), \
         patch.object(tts.elevenlabs_tts,'available',return_value=(False,'test failure',{})), \
         patch.object(tts.chatterbox_tts,'available') as other, \
         patch.object(tts.kokoro_tts,'available') as fallback:
        with pytest.raises(SystemExit,match='test failure'):
            tts.voice([('Exact approved text',0)],tmp_path/'out.wav',{},'elevenlabs',lambda _:None,strict=True)
    other.assert_not_called();fallback.assert_not_called()


def test_real_audio_retiming_preserves_speech_and_holds_card_before_walk():
    import numpy as np
    from kindled_iron.money_video import assemble_read,retime_moves
    scene={'end_hold':1.2,'beats':[
        dict(narration='one',captions=True,events=[]),
        dict(narration='two',captions=True,events=[]),
        dict(narration='three',captions=False,events=[]),
        dict(narration='four',captions=True,events=[dict(do='walk',at=-99),dict(do='face',at=-99)])]}
    sr=1000;audio=np.arange(1,4001,dtype=np.float32)
    aligned=[dict(word=w,start=i+.1,end=i+.8) for i,w in enumerate(['one','two','three','four'])]
    result,spans,words=assemble_read(scene,audio,sr,aligned)
    retime_moves(scene,spans)
    assert np.array_equal(result[result!=0],audio)
    assert spans[3][0]-spans[2][1]>=1.4-1/sr
    assert len(result)/sr>=spans[-1][1]+1.2
    walk=scene['beats'][3]['events'][0]
    assert spans[3][0]+walk['at']==pytest.approx(spans[2][1]+.55)
    for i,bw in enumerate(words):
        original=aligned[i]
        assert bw[0]['end']-bw[0]['start']==pytest.approx(original['end']-original['start'])


def test_only_requested_ending_silence_is_removed():
    import numpy as np
    from kindled_iron.money_video import shorten_final_silence
    audio=np.concatenate([np.arange(1,1001),np.zeros(1550),np.arange(1001,1501)]).astype(np.float32)
    trimmed,edit=shorten_final_silence(audio,1000,1,2.55,.4)
    assert np.array_equal(trimmed[:1200],audio[:1200])
    assert np.array_equal(trimmed[1200:],audio[2350:])
    assert edit['removed_seconds']==pytest.approx(1.15)
    assert edit['kept_seconds']==.4


def test_slow_guide_walks_during_speech_without_moving_verse_timings():
    from kindled_iron.money_video import slow_moves
    scene={'beats':[]};spans=[];words=[]
    for i in range(27):
        word={4:'great',15:'checked',17:'does'}.get(i,'word')
        events=[dict(reaction='surprised',at=word,dur=.7,card={})] if i in (4,15,17) else []
        scene['beats'].append(dict(captions=i not in (12,21,22),events=events))
        spans.append((i*4,i*4+3.5));words.append([dict(word=word,start=i*4+.8,end=i*4+1.1)])
    before=json.dumps([spans,words])
    moves=slow_moves(scene,spans,words)
    assert json.dumps([spans,words])==before and len(moves)>=5
    assert all(e['speed']==280 for b in scene['beats'] for e in b['events'] if e.get('do')=='walk')
    assert all(end-start>2.7 for start,end,lane in moves)
    assert all(not (a<spans[i][1]+1.1 and b>spans[i][0]-.3) for a,b,_ in moves for i in (12,21,22))


def test_continuous_read_holds_card_without_covering_it_with_new_clip():
    from kindled_iron.money_video import fit_continuous_visuals
    data=dict(objects=[dict(id='verse',type='scripture',_t0=1,_t1=4),dict(id='clip',type='inset',display_dur=.5)],
        events=[dict(do='draw',id='verse',t=1,show_at=.7),dict(do='fade',ids=['verse'],t=3.2),dict(do='draw',id='clip',t=3.2)],
        mediaCoverage=[{'id':'verse','kind':'scripture','from':.7,'to':3},{'id':'clip','kind':'inset','from':3.2,'to':3.7}])
    fit_continuous_visuals(data)
    assert not any(e['do']=='draw' and e['id']=='clip' for e in data['events'])
    assert data['mediaCoverage'][-1]=={'id':'verse','kind':'scripture','from':3.2,'to':3.7}
    assert data['captionSuppress']==[dict(start=1,end=4)]
