"""Owner-reviewed word-cued media expansion. Private test only; no voice generation."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import json,re,subprocess
from pathlib import Path
from kindled_iron import render,insets,private_media

# (word cue, source ID, meaning). All source IDs were visually researched.
SHOTS = {
0:[(0,'5651780','US hundred-dollar bills'),('or','6144016','Hesitating: thinking face')],
1:[(0,'7154208','The single dealership car: fictional sale'),('transmission','2075171','Transmission: gear shift detail')],
2:[(0,'8986479','Checking under the hood')],
3:[(0,'7535095','Phone banking / card payment')],
4:[(0,'7154208','Same dealership car; Runs great reaction')],
5:[(0,'2075171','Driving: gear shift detail'),('paid','7710826','US dollars received'),('repair','7546415','Repair invoice')],
6:[(0,'6952545','Brother and sister bonding')],
7:[(0,'6952545','Same imagined sister: alternate close crop and range')],
8:[(0,'2075171','Gear shift: transmission needs work')],
9:[(0,'7154208','SAME CAR / SAME PROBLEM: identical car side by side')],
10:[(0,'5466769','US dollars valued over another person'),('them','4988391','Reflecting on the consequence')],
11:[(0,'7263305','Newspaper: the repeated saying'),('Bible','5199724','Bible: checking the actual claim'),('feed','6305041','Family dinner'),('treatment','4352135','Medical consultation'),('get','7252265','Transit ticket home')],
12:[(0,'5199724','1 Timothy: Bible prefix, first range')],
13:[(0,'7475240','Generosity as contrast to loving money')],
14:[(0,'7154208','Same dealership car sale'),('want','7546415','Financial pressure: invoice'),('truth','11099870','Empty wallet: the temptation'),('excuses','7889097','Face: rationalizing')],
15:[(0,'14514790','Inspection: mechanics hands, no second exterior')],
16:[(0,'7546415','Invoice: I need the money')],
17:[(0,'35585184','Warning lights remain: Everybody does it reaction')],
18:[(0,'2075171','Transmission still needs work'),('hiding','8986488','Engine detail: hiding does not fix it')],
19:[(0,'7924459','Need money: past-due bill'),('spending','7710771','Spending savings: first jar range'),('just','10374892','Getting to work: laptop work, first range'),('Your','7924459','Your bills: later range and closer crop')],
20:[(0,'11099870','An empty wallet contrasts with the rich meme'),('almost','7710771','Almost nothing: later savings-jar range')],
21:[(0,'5199724','Proverbs: later Bible range')],
22:[(0,'5199724','Hebrews: another later Bible range')],
23:[(0,'29119700','Hope: sunrise'),('right','5199724','Trust in God: later open Bible detail'),('money','7924953','Need: an empty wallet')],
24:[(0,'10374892','WORK: new laptop range'),('Earn','7535095','EARN: later phone/card range'),('Save','7710771','SAVE: non-overlapping savings range'),('Provide','8421648','PROVIDE: groceries'),('wallet','11272053','Wallet opening'),('running',None,'Who runs your heart: hand-drawn heart')],
25:[(0,'4988391','Considering the honest choice'),('ten','5651780','US hundred-dollar bills: second and last use')],
26:[(0,'5466769','Closing choice: cash left / open Bible right')],
}
RANGES={(1,0):(1,None),(4,0):(4.5,None),(7,0):(5,[.15,.1,.75,.75]),(9,0):(1,None),(14,0):(7,None),
        (19,0):(1,None),(19,1):(1,None),(19,2):(0,None),(19,3):(5.5,[0,.05,.95,.55]),
        (20,1):(6,None),(12,0):(1,None),(21,0):(5,None),(22,0):(8,None),(23,1):(10.5,None),
        (24,0):(4.5,None),(24,1):(5.5,None),(24,2):(12,None)}

REACTIONS={4:('great','surprised',.7),17:('does','smart',.7),20:('rich','celebration',1.0)}

def expand(scene):
    """Keep all approved words/cards/gestures; replace the repetitive source mapping."""
    if len(scene['beats'])!=27:raise SystemExit('FAIL: expansion requires the exact 27-paragraph approved script')
    scene['editorial_expansion']=True
    scene['reaction_limits']={'max':3,'min_gap':3.0}
    for i,b in enumerate(scene['beats']):
        old=b['events'];card=next((deepcopy(e) for e in old if e.get('scripture')),None)
        keep=[deepcopy(e) for e in old if e.get('do') in ('express','point','shrug','present')]
        ev=[]
        for j,(cue,pin,meaning) in enumerate(SHOTS[i]):
            iid=f'shot_{i+1}_{j+1}'
            e=dict(at=cue,do='draw',id=iid,x=540,y=405,w=780,h=440,editorial=True,meaning=meaning,
                   instant=True,pop=False,required=True)
            if pin:
                e.update(type='inset',sources=['pexels','pixabay'],pin={'pexels':pin},query=meaning,clip_dur=3)
                if i in (12,21,22):e['clip_dur']=1.5
                if pin=='8630309':e['crop']=[.05,.02,.5,.75]
                if pin=='14514790':e['crop']=[.55,.40,.40,.40]
                if i==9:e['split_same']=True
                if i==26:e['composite_pin']='5199724';e['composite_start']=10.5
            else:e.update(type='heart',dur=.7,color='accent',instant=False)
            if (i,j) in RANGES:
                e['start'],crop=RANGES[i,j]
                if crop:e['crop']=crop
            if pin=='8986479':e['crop']=[.18,.15,.65,.65]
            if pin=='8986488':e['crop']=[.12,.18,.7,.6]
            ev.append(e)
        if card:
            card['card_at_beat_start']=False;card['editorial']=True;ev.append(card)
        for e in keep:
            if e.get('do')=='point' and not card:e['toward']=ev[0]['id']
            ev.append(e)
        if i in REACTIONS:
            cue,emotion,dur=REACTIONS[i]
            ev.append(dict(at=cue,reaction=emotion,dur=dur,card=dict(x=535 if i==20 else 650,y=1120,w=380 if i==20 else 200,h=240 if i==20 else 160,rotate=0,require_original_width=i==20)))
            b['serious']=False
        if i==1:
            ev += [dict(at='selling',do='draw',id='sale_sign',type='word',text='FOR SALE',x=540,y=570,size=56,color='accent',instant=True,pop=False),
                   dict(at='transmission',do='fade',ids=['sale_sign'],opacity=0,dur=.001)]
        if i==24:ev.append(dict(at='heart',do='point',who='guide',toward='shot_25_6',hold=.5))
        if i==26:
            ev += [dict(at=0,do='look_viewer',who='guide'),dict(at='trust',do='shrug',who='guide',hold=1.1)]
        b['events']=ev
    counts=Counter(e['pin']['pexels'] for b in scene['beats'] for e in b['events'] if e.get('editorial') and e.get('pin'))
    counts['5199724']+=1 # closing composite right side
    if sum(counts[k] for k in ('5466769','7710826'))>3:raise SystemExit('FAIL: cash-counting footage exceeds three uses')
    last=None
    for b in scene['beats']:
        for e in b['events']:
            if e.get('scripture'):last=None
            if not e.get('pin'):continue
            key=(e['pin']['pexels'],e.get('start',1),tuple(e.get('crop') or []),e.get('split_same'),e.get('composite_pin'))
            if key==last:raise SystemExit('FAIL: identical consecutive footage at '+e['id'])
            last=key
    return scene


def fetch(scene,work,log):
    """Provider fetches happen in Actions, using its secrets. Composites reuse decoded frames."""
    expanded=deepcopy(scene)
    for b in expanded['beats']:
        for e in list(b['events']):
            if e.get('composite_pin'):
                partner={**e,'id':e['id']+'_right','pin':{'pexels':e['composite_pin']},'query':'Closing open Bible','start':e.get('composite_start',10.5)}
                partner.pop('composite_pin');b['events'].append(partner)
    clips=insets.fetch(expanded,work,log)
    from PIL import Image,ImageOps
    from urllib.parse import urlparse
    for b in scene['beats']:
        for e in b['events']:
            if not(e.get('split_same') or e.get('composite_pin')):continue
            a=clips[e['id']]['frames'];right=clips[e['id']+'_right']['frames'] if e.get('composite_pin') else a
            out=work/'composites'/e['id'];out.mkdir(parents=True,exist_ok=True);frames=[]
            for k,src in enumerate(a):
                left=ImageOps.fit(Image.open(urlparse(src).path).convert('RGB'),(390,440))
                r=ImageOps.fit(Image.open(urlparse(right[k%len(right)]).path).convert('RGB'),(390,440))
                canvas=Image.new('RGB',(780,440));canvas.paste(left,(0,0));canvas.paste(r,(390,0))
                from PIL import ImageDraw
                ImageDraw.Draw(canvas).line((390,0,390,440),fill='#302b24',width=5)
                p=out/f'f_{k:04d}.jpg';canvas.save(p,quality=90);frames.append(p.as_uri())
            clips[e['id']]['frames']=frames
    return clips


def timed_visuals(data,scene,spans,words):
    """A strict visual segment per actual word cue, rather than per paragraph."""
    objs={o['id']:o for o in data['objects']};draws={e['id']:e for e in data['events'] if e['do']=='draw'}
    rows=[]
    for i,b in enumerate(scene['beats']):
        for spec in b['events']:
            if not spec.get('editorial'):continue
            o=objs[spec['id']];e=draws[spec['id']]
            if o['type']=='scripture':
                e['show_at']=o['_t0'];t=o['_t0'];kind='scripture'
            else:t=e['t'];kind='drawing' if o['type']=='heart' else 'inset'
            rows.append(dict(id=o['id'],kind=kind,start=t,line=i+1,cue=spec.get('at',0),meaning=spec.get('meaning','Scripture'),source=(spec.get('pin') or {}).get('pexels'),source_start=spec.get('start',1),crop=spec.get('crop')))
    rows.sort(key=lambda r:r['start'])
    coverage=[]
    for n,row in enumerate(rows):
        t=row['start'];end=rows[n+1]['start'] if n+1<len(rows) else data['duration']
        o=objs[row['id']]
        if row['kind']=='scripture':end=min(end,o['_t1'])
        else:o['display_dur']=max(.01,end-t)
        if end>t:coverage.append(dict(id=row['id'],kind=row['kind'],**{'from':t,'to':end}))
        if n:
            prev=rows[n-1];data['events'].append(dict(t=t,do='fade',ids=[prev['id']],opacity=0,dur=.001))
        row['end']=end
    data['mediaCoverage']=coverage
    # Four cumulative bullets replace ordinary captions only over this phrase.
    bw=words[24];start=render.resolve_at('work',bw,*spans[24],{});end=render.resolve_at('warning',bw,*spans[24],{})
    data['bulletOverlays']=[dict(start=start,end=render.resolve_at('The',bw,*spans[24],{}),zone=dict(left=200,top=410,right=880,bottom=605),words=[dict(text='✓ '+label,start=render.resolve_at(cue,bw,*spans[24],{})) for cue,label in [('work','WORK'),('Earn','EARN'),('Save','SAVE'),('Provide','PROVIDE')]])]
    data['guideSpots']=[160,310,460,610,760,920]
    data['editorialShots']=rows
    data['events'].sort(key=lambda e:e['t'])


def synchronize_shots(data):
    """Report actual visibility after scripture holds, not superseded clip plans."""
    visible={e['id'] for e in data['events'] if e['do']=='draw'}
    for row in data['editorialShots']:
        row['planned_start']=row['start'];row['planned_end']=row['end']
        intervals=[{'start':n['from'],'end':n['to']} for n in data['mediaCoverage'] if n['id']==row['id']]
        row['visible_intervals']=intervals if row['id'] in visible else []
        row['shown']=bool(row['visible_intervals'])
        if row['shown']:
            row['start']=min(n['start'] for n in intervals);row['end']=max(n['end'] for n in intervals)


def report(scene,data,voice,work):
    sources=json.loads((work/'sources.json').read_text());by={s['inset']:s for s in sources}
    reactions=json.loads((work/'reactions.json').read_text())
    lines=['# Love of Money — private test shot report','',
           'Exact approved script; supplied venloud v4 recording. No voice regeneration, no publishing.',
           'Normal captions retain size 92. Four cumulative uppercase bullets appear inside the inset, in their own audited region.',
           f"Final pause: {voice['ending_pause_edit']['original_seconds']:.3f} → 0.500 s; 20 ms crossfade within silence. Music mixed continuously after the cut.",
           '', '| Line / exact narration | Cue → visual and source |','|---|---|']
    for i,b in enumerate(scene['beats']):
        entries=[]
        for r in data['editorialShots']:
            if r['line']!=i+1:continue
            src=by.get(r['id']);url=src['page'] if src else 'existing hand-drawn runtime'
            if not r.get('shown',True):
                entries.append(f"**{r['cue']}**: previous scripture card remains for its required hold; fetched source {url} is superseded, not shown.")
                continue
            entries.append(f"{r['start']:.2f}s, **{r['cue']}**: {r['meaning']} — ID {r['source'] or r['id']}, range {r.get('source_start',1):.1f}s, crop {r.get('crop')} — {url}")
            if r['id']=='shot_27_1':entries.append('Right half: ID 5199724, source range 10.5s — https://www.pexels.com/video/5199724/')
        if i in REACTIONS:
            cue,emotion,_=REACTIONS[i];rec=next((r for r in reactions if r['emotion']==emotion),None)
            entries.append(f"**{cue}** reaction: {rec['origin']} — {rec.get('source','private reactions/')}" if rec else f'ERROR missing reaction {emotion}')
        lines.append('| '+str(i+1)+'. '+b['narration'].replace('|','/')+' | '+'<br>'.join(entries)+' |')
    lines+=['','All third-party reaction files and narration remain in the private voice repository. No public Actions artifacts.',
            'The FOR SALE lettering is editorial. One dealership exterior ID (7154208) is used throughout; other vehicle shots are cropped technical details.',
            'Stock people illustrate the fictional story; the footage is not evidence of actual dishonesty or vehicle defects.',
            'SAME CAR duplicates the approved car source in one composed frame. Lifestyle sources show no other cars.',
            'Phone/card is a payment illustration; no fake notification. EARN uses a distinct phone/card range.',
            'Bible prefixes use different IDs before the unchanged scripture card; no competing footage during typing.']
    (work/'shot-list.md').write_text('\n'.join(lines)+'\n')
    (work/'shot-list.json').write_text(json.dumps(dict(shots=data['editorialShots'],sources=sources,reactions=reactions),indent=2))


def review_times(data,work):
    rows=data['editorialShots']
    def at(line,cue=None,offset=.25):
        r=next(r for r in rows if r['line']==line and (cue is None or r['cue']==cue))
        return min(r['start']+offset,r['end']-.05)
    memes=json.loads((work/'reactions.json').read_text())
    return [.3,memes[0]['t']+.2,at(10,offset=.7),at(12,'feed'),
            next(r['start']+2 for r in rows if r['line']==13 and r['kind']=='scripture'),
            next(m['t']+.3 for m in memes if m['emotion']=='celebration'),
            at(25,'Provide')+.15,at(27,offset=.6)]


def stitch_sheet(paths,times,path):
    from PIL import Image,ImageDraw
    sheet=Image.new('RGB',(2160,2000),'#f4f1ea');d=ImageDraw.Draw(sheet)
    for i,(src,t) in enumerate(zip(paths,times)):
        im=Image.open(src).convert('RGB');im.thumbnail((540,960))
        x=i%4*540;y=i//4*1000;sheet.paste(im,(x,y));d.text((x+12,y+970),f'{t:.2f}s',fill='black')
    sheet.save(path,quality=92)


def preview_sheet(data,page,out,work):
    times=review_times(data,work);frames=work/'eight_frames'
    render.capture(page,None,None,data['duration'],None,stills=times,still_dir=frames)
    paths=[frames/f'frame_{t:05.2f}.png' for t in times]
    stitch_sheet(paths,times,out.parent/'eight-frames.jpg')
    return times


def review_sheet(data,video,work):
    times=review_times(data,work);paths=[]
    for i,t in enumerate(times):
        p=work/f'review_{i}.jpg';subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',str(video),'-frames:v','1','-vf','scale=540:960','-y',str(p)],check=True);paths.append(p)
    stitch_sheet(paths,times,video.parent/'eight-frames.jpg')
    return times
