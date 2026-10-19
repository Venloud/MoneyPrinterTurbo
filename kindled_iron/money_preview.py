"""Eight layout stills only; never synthesizes audio, encodes video or publishes.

Uses estimated word times for editorial approval. Final narration must replace
these times and rerun the every-frame gate before encoding a production video.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
from kindled_iron import insets, render, scripture, effects
from kindled_iron.pacing import words_of

# Exact IDs from claudevandam/docs/LOVE_OF_MONEY_SCENE_SHORTLIST.md.
CASH = '5466769'  # visually reviewed US $20/$100 bills, not the rejected GBP clip
CAR = '7154208'   # one dealership car source, reused; no second car exterior
GEAR = '2075171'
MECHANIC = '14514790'
BIBLE = '5199724'


def build(script: str):
    note = 'Bracketed references appear on screen and are not spoken.'
    lines = [p.strip() for p in script.strip().split('\n\n') if p.strip()]
    if not lines or lines[-1] != note:
        raise SystemExit('FAIL: approved script must end with the reference display instruction')
    lines = lines[:-1]
    scene = dict(id='love-of-money-v2', title='The Love of Money', exact_narration=True,
                 strict_layout=True, strict_media=True, ground=1430, camera_y=960,
                 inset_snap=False, fill_min=0, voice_profile='kindled_iron', end_hold=1.2,
                 layout_zones={'captions':dict(left=140,top=1150,right=760,bottom=1430),
                               'clip':dict(left=128,top=160,right=960,bottom=660),
                               'verse':dict(left=128,top=650,right=768,bottom=1080),
                               'guide_head':dict(left=770,top=650,right=960,bottom=1140)},
                 captions_box=dict(x=450,y=1190,w=580,size=104,min_scale=.68),
                 captions_chunk=dict(max_words=3,min_words=1,max_chars=19),
                 cast={'guide':dict(x=885,panel=0,scale=1.785,facing=-1,accent=True)}, beats=[])
    spans, words, t = [], [], 0.
    for i,line in enumerate(lines):
        ws = words_of(line)
        duration = max(1.5, len(ws)*60/175)
        bw=[dict(word=w,start=t+j*duration/len(ws),end=t+(j+1)*duration/len(ws)) for j,w in enumerate(ws)]
        start,end=t,t+duration
        spans.append((start,end));words.append(bw)
        # US dollars whenever money/payment/earning is mentioned. Car exteriors
        # always use CAR; component closeups do not introduce a different car.
        money=bool(re.search(r'money|dollars|payment|paid|paid|bills|wallet|earn|save|pay|savings|wealth|rich|ten thousand',line,re.I))
        pin=CASH if money or i == 13 else (GEAR if 'transmission' in line.lower() else CAR)
        if i==18: pin=MECHANIC
        if '[Proverbs' in line: pin=BIBLE
        ev=[dict(at=0,do='draw',id=f'clip_{i}',type='inset',x=540,y=405,w=780,h=440,
                 sources=['pexels'],pin={'pexels':pin},required=True,query=f'pinned {pin}',
                 clip_dur=3,display_dur=duration,cover_beat=True,instant=True,pop=False)]
        if pin == MECHANIC:
            ev[0]['crop'] = [.55, .40, .40, .40] # engine-only: exclude the second vehicle's exterior
        ev.append(dict(at=0,do='express',who='guide',expression='thinking' if i%2 else 'speaking'))
        if i:
            ev.insert(0,dict(at=0,do='fade',ids=[f'clip_{i-1}'],opacity=0,dur=.01))
        ref=re.search(r'\[([^]]+)\]',line)
        if ref:
            quote=re.search('“(.*)”',line).group(1)
            ev.append(dict(scripture=dict(ref=ref.group(1),text=quote),id=f'verse_{i}',x=450,y=805,w=600,size=42))
        beat=dict(id=f'line_{i+1}',panel=0,narration=line,camera_start=False,events=ev)
        scene['beats'].append(beat);t=end+.05
    scripture.check_scene(scene,render.log)
    return scene,spans,words,t+1.2


def main():
    ap=argparse.ArgumentParser();ap.add_argument('script',type=Path);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=True)
    text=a.script.read_text();scene,spans,words,duration=build(text)
    (a.out/'scene.json').write_text(json.dumps(scene,indent=2))
    # Always resolve approved pins using repository provider credentials in the
    # Actions runtime. No external local clip cache is smuggled into the run.
    clips=insets.fetch(scene,a.out,render.log)
    data=render.build_data(scene,spans,words,duration,clips)
    data["paper"] = effects.paper_texture(a.out, render.PALETTE["board"])
    picks=[0,2,5,8,12,18,21,22]
    times=[round((spans[i][1]+.55) if i in (12,21,22) else spans[i][0]+min(1.2,(spans[i][1]-spans[i][0])/2),3) for i in picks]
    page=render.write_page(data,a.out)
    render.capture(page,None,None,duration,None,stills=times,still_dir=a.out/'eight_frames')
    report=dict(script_sha256=hashlib.sha256(text.encode()).hexdigest(),timing='estimated, no audio generated',
                frame_times=times,preview_only=True,full_render=False,pins=[CASH,CAR,GEAR,MECHANIC,BIBLE])
    (a.out/'preview.json').write_text(json.dumps(report,indent=2))
    from PIL import Image,ImageOps,ImageDraw
    sheet=Image.new('RGB',(4*270,2*500),'#f4f1ea')
    for n,p in enumerate(sorted((a.out/'eight_frames').glob('*.png'), key=lambda f: float(f.stem.split('_')[-1]))):
        im=Image.open(p).convert('RGB');im.thumbnail((270,480));x=(n%4)*270;y=(n//4)*500
        sheet.paste(im,(x,y));ImageDraw.Draw(sheet).text((x+8,y+482),f'{n+1}: {times[n]:.2f}s',fill='black')
    sheet.save(a.out/'eight-frames.jpg',quality=92)

if __name__=='__main__':main()
