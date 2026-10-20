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


def build(script: str, *, editorial=False):
    note = 'Bracketed references appear on screen and are not spoken.'
    lines = [p.strip() for p in script.strip().split('\n\n') if p.strip()]
    if not lines or lines[-1] != note:
        raise SystemExit('FAIL: approved script must end with the reference display instruction')
    lines = lines[:-1]
    scene = dict(id='love-of-money-v2', title='The Love of Money', exact_narration=True,
                 strict_layout=True, strict_media=True, ground=1430, camera_y=960,
                 inset_snap=False, fill_min=0, voice_profile='kindled_iron', end_hold=1.2,
                 layout_zones={'captions':dict(left=120,top=670,right=960,bottom=825),
                               'reaction':dict(left=120,top=880,right=960,bottom=1430),
                               'clip':dict(left=128,top=160,right=960,bottom=660)},
                 captions_box=dict(x=540,y=690,w=820,size=92,min_scale=.68,single_line=True),
                 captions_chunk=dict(max_words=3,min_words=1,max_chars=16),
                 cast={'guide':dict(x=-150,panel=0,scale=1.785,facing=1,accent=True)}, beats=[])
    spans, words, t, lane = [], [], 0.0, 920
    last_visual = None
    # The same dealership car stays throughout. Cash appears exactly three times.
    pins=[CASH,CAR,GEAR,CASH,CAR,MECHANIC,CAR,MECHANIC,GEAR,CAR,CASH,BIBLE,
          None,GEAR,CAR,MECHANIC,GEAR,CAR,MECHANIC,CAR,MECHANIC,None,None,
          BIBLE,CAR,GEAR,BIBLE]
    reactions={4:('great','surprised',.7),15:('checked','confused',.9),17:('does','smart',.8)}
    for i,line in enumerate(lines):
        ws = words_of(line)
        duration = max(1.5, len(ws)*60/175)
        start,end=t,t+duration
        bw=[dict(word=w,start=t+j*duration/len(ws),end=t+(j+1)*duration/len(ws)) for j,w in enumerate(ws)]
        ev=[]
        if i == 0:
            ev += [dict(at=-start,do='place',who='guide',x=-150,facing=1),
                   dict(at=.05-start,do='walk',who='guide',to=920,speed=700)]
        elif i % 3 == 0:
            # Turn in place, walk forwards, then settle; captions never move.
            previous_end=spans[-1][1]
            lane=160 if lane==920 else 920
            direction=1 if lane==920 else -1
            ev += [dict(at=previous_end+.30-start,do='face',who='guide',facing=direction),
                   dict(at=previous_end+.55-start,do='walk',who='guide',to=lane,dur=.55)]
        ref=re.search(r'\[([^]]+)\]',line)
        if last_visual:
            ev.append(dict(at=0,do='fade',ids=[last_visual],opacity=0,dur=.15))
        if ref:
            quote=re.search('“(.*)”',line).group(1)
            visual=f'verse_{i}'
            # Renderer uses 64 with precomputed page sizes when the full
            # long quote cannot fit at 64. No second visual or inset here.
            ev.append(dict(scripture=dict(ref=ref.group(1),text=quote),id=visual,
                           x=540,y=405,w=780,size=64,fit_height=440,min_size=64,
                           card_at_beat_start=True,typewriter=True))
            key='money' if 'money' in quote else 'little' if 'little' in quote else 'leave'
            ev.append(dict(at=key,do='point',who='guide',toward=visual,hold=.5))
        else:
            pin=pins[i] if i<len(pins) else (CAR if i%2 else GEAR)
            visual=f'clip_{i}'
            clip=dict(at=0,do='draw',id=visual,type='inset',x=540,y=405,w=780,h=440,
                      sources=['pexels'],pin={'pexels':pin},required=True,query=f'pinned {pin}',
                      clip_dur=3,display_dur=duration,cover_beat=True,instant=True,pop=False)
            if pin==MECHANIC: clip['crop']=[.55,.40,.40,.40]
            ev.append(clip)
            if i%3==1 and i not in reactions: ev.append(dict(at=.25,do='point',who='guide',toward=visual,hold=.5))
        if i in reactions:
            key,emotion,hold=reactions[i]
            ev.append(dict(at=key,reaction=emotion,dur=hold,
                           card=dict(x=650 if lane==920 else 430,y=1120,w=200,h=160,rotate=0)))
        ev.append(dict(at=0,do='express',who='guide',expression='thinking' if i%2 else 'speaking'))
        scene['beats'].append(dict(id=f'line_{i+1}',panel=0,narration=line,camera_start=False,captions=not bool(ref),serious=i not in {0,1,2,3,4,7,8,9,13,14,15,16,17},events=ev))
        spans.append((start,end));words.append(bw);last_visual=visual
        # Pause-only lane changes cannot collide with a spoken caption. Cards
        # finish typing and hold for >=1 second before the next line starts.
        t=end+(1.4 if (i+1)%3==0 else 1.3 if ref else .35)
    if editorial:
        from kindled_iron.money_editorial import expand
        expand(scene)
    scripture.check_scene(scene,render.log)
    return scene,spans,words,t+1.2


def resolve_media(scene,spans,words,duration,work,require_all=True):
    # Always resolve approved pins using repository provider credentials in the
    # Actions runtime. No external local clip cache is smuggled into the run.
    from kindled_iron import money_editorial
    clips=money_editorial.fetch(scene,work,render.log) if scene.get("editorial_expansion") else insets.fetch(scene,work,render.log)
    data=render.build_data(scene,spans,words,duration,clips)
    if scene.get('editorial_expansion'):money_editorial.timed_visuals(data,scene,spans,words)
    data['inboxReactions'], memes=effects.apply_reaction_rules(data['events'],scene,spans,words,work,render.log,data,True)
    requested=[e for e in data['events'] if e['do']=='reaction']
    if scene.get('editorial_expansion') and (len(memes)!=3 or any(not m['origin'].startswith('private:reactions/') for m in memes)):
        raise SystemExit('FAIL: all three owner-selected reactions must resolve from private reactions/: '+str(memes))
    if require_all and (len(memes)!=3 or len(requested)!=3 or any(e.get('_drop') for e in requested)):
        missing=[e['emotion'] for e in requested if e.get('_drop') or not any(m['emotion']==e['emotion'] for m in memes)]
        raise SystemExit('FAIL: selected reaction images missing/dropped: '+', '.join(missing))
    data['events']=[e for e in data['events'] if not e.get('_drop')]
    for rec in memes:
        obj=next(o for o in data['objects'] if o['id']==rec['id'])
        event=next(e for e in data['events'] if e.get('id')==rec['id'] and e['do']=='draw')
        obj.update(required=True,reaction_card=True,display_dur=obj['clip_dur'])
        rec.update(width=obj['w'],height=obj['h'])
        event.update(instant=True,pop=False)
    data['events'].sort(key=lambda e:e['t'])
    (work/'reactions.json').write_text(json.dumps(memes,indent=2))
    data["paper"] = effects.paper_texture(work, render.PALETTE["board"])
    return data,memes


def main():
    ap=argparse.ArgumentParser();ap.add_argument('script',type=Path);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=True)
    text=a.script.read_text();scene,spans,words,duration=build(text)
    (a.out/'scene.json').write_text(json.dumps(scene,indent=2))
    data,memes=resolve_media(scene,spans,words,duration,a.out)
    # Opening mid-stride; both lanes; verse mid-type; pointing; long verse page.
    times=[.3, .75, spans[4][0]+1.0,
           spans[12][0]+2.15, spans[15][0]+1.35,
           spans[17][0]+.85, spans[22][0]+5.0, spans[22][1]+.5]
    times=sorted(round(t,3) for t in times)
    page=render.write_page(data,a.out)
    render.capture(page,None,None,duration,None,stills=times,still_dir=a.out/'eight_frames')
    report=dict(script_sha256=hashlib.sha256(text.encode()).hexdigest(),timing='estimated, no audio generated',
                frame_times=times,preview_only=True,full_render=False,reactions=memes,pins=[CASH,CAR,GEAR,MECHANIC,BIBLE])
    (a.out/'preview.json').write_text(json.dumps(report,indent=2))
    from PIL import Image,ImageDraw,ImageFont
    sheet=Image.new('RGB',(4*540,2*1000),'#f4f1ea')
    font=ImageFont.truetype(str(render.VENDOR/'fonts'/'Caveat.ttf'),26)
    for n,p in enumerate(sorted((a.out/'eight_frames').glob('*.png'), key=lambda f: float(f.stem.split('_')[-1]))):
        im=Image.open(p).convert('RGB');im.thumbnail((540,960));x=(n%4)*540;y=(n//4)*1000
        sheet.paste(im,(x,y));ImageDraw.Draw(sheet).text((x+12,y+968),f'{n+1}: {times[n]:.2f}s',font=font,fill='black')
    sheet.save(a.out/'eight-frames.jpg',quality=92)

if __name__=='__main__':main()
