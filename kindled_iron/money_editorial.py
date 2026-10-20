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
1:[(0,'9737916','Car lot establishing shot'),('selling','7154208','The same fictional sale car'),('transmission','35585184','Dashboard warning lights')],
2:[(0,'8986479','Checking under the hood')],
3:[(0,'7535095','Phone banking / card payment')],
4:[(0,'7154207','Sale handshake; Runs great reaction')],
5:[(0,'8630309','Driving away: moving wheel and road detail'),('paid','7710826','US dollars received'),('week','34231504','Tow truck: consequences'),('repair','6685058','Customer discussing repair invoice with mechanic')],
6:[(0,'6952545','Brother and sister bonding')],
7:[(0,'7154215','Young woman beside car: imagined sister')],
8:[(0,'2075171','Gear shift: transmission needs work')],
9:[(0,'7154208','SAME CAR / SAME PROBLEM: identical car side by side')],
10:[(0,'5466769','US dollars valued over another person'),('them','4988391','Reflecting on the consequence')],
11:[(0,'7263305','Newspaper: the repeated saying'),('Bible','5199724','Bible: checking the actual claim'),('feed','6305041','Family dinner'),('treatment','4352135','Medical consultation'),('home','7252265','Transit ticket home')],
12:[(0,'5199729','1 Timothy: Bible prefix before quote')],
13:[(0,'7475240','Generosity as contrast to loving money')],
14:[(0,'7154212','Car sale'),('want','7924459','Financial pressure: past-due bill'),('truth','11099870','Empty wallet: the temptation'),('excuses','7889097','Face: rationalizing')],
15:[(0,'8986485','Inspection: They should have checked reaction')],
16:[(0,'7546415','Invoice: I need the money')],
17:[(0,'8987078','Repair work: Everybody does it reaction')],
18:[(0,'14514790','The unfixed car'),('hiding','8986488','Engine fault remains')],
19:[(0,'8421648','Essential groceries'),('savings','7710771','US-dollar savings jar'),('work','33825911','Commuter getting to work'),('bills','7924459','Past-due bills')],
20:[(0,'7710826','Verified US dollars; rich reaction'),('almost','36036686','Almost nothing: coins in a hand')],
21:[(0,'13013179','Proverbs: different open Bible')],
22:[(0,'16577160','Hebrews: another Bible opening')],
23:[(0,'29119700','Hope: sunrise'),('right','6685054','Honest work and agreement'),('money','7924953','Need: an empty wallet')],
24:[(0,'10374892','WORK: laptop work'),('Earn','6282368','EARN: payroll illustration'),('Save','7710771','SAVE: US-dollar savings jar'),('Provide','8503011','PROVIDE: family at home'),('wallet','11272053','Wallet opening'),('heart',None,'Hand-drawn heart')],
25:[(0,'4988391','Considering the honest choice'),('ten','5651780','US hundred-dollar bills: second and last use')],
26:[(0,'5466769','Closing choice: cash left / sunrise right')],
}
REACTIONS={4:('great','surprised',.7),15:('checked','confused',.7),17:('does','smart',.7),20:('rich','celebration',1.0)}

def expand(scene):
    """Keep all approved words/cards/gestures; replace the repetitive source mapping."""
    if len(scene['beats'])!=27:raise SystemExit('FAIL: expansion requires the exact 27-paragraph approved script')
    scene['editorial_expansion']=True
    # Owner's current review explicitly asks for all four cue-specific images.
    scene['reaction_limits']={'max':4,'min_gap':1.5}
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
                if i==26:e['composite_pin']='29119700'
            else:e.update(type='heart',dur=.7,color='accent',instant=False)
            ev.append(e)
        if card:
            card['card_at_beat_start']=False;card['editorial']=True;ev.append(card)
        for e in keep:
            if e.get('do')=='point' and not card:e['toward']=ev[0]['id']
            ev.append(e)
        if i in REACTIONS:
            cue,emotion,dur=REACTIONS[i]
            ev.append(dict(at=cue,reaction=emotion,dur=dur,card=dict(x=650,y=1120,w=200,h=160,rotate=0)))
            b['serious']=False
        if i==1:
            ev += [dict(at='selling',do='draw',id='sale_sign',type='word',text='FOR SALE',x=540,y=570,size=56,color='accent',instant=True,pop=False),
                   dict(at='transmission',do='fade',ids=['sale_sign'],opacity=0,dur=.001)]
        if i==24:ev.append(dict(at='heart',do='point',who='guide',toward='shot_25_6',hold=.5))
        if i==26:
            ev += [dict(at=0,do='look_viewer',who='guide'),dict(at='trust',do='shrug',who='guide',hold=1.1)]
        b['events']=ev
    counts=Counter(e['pin']['pexels'] for b in scene['beats'] for e in b['events'] if e.get('editorial') and e.get('pin'))
    counts['29119700']+=1 # closing composite right side
    if max(counts.values())>2:raise SystemExit('FAIL: source used more than twice: '+str(dict(counts)))
    return scene


def fetch(scene,work,log):
    """Provider fetches happen in Actions, using its secrets. Composites reuse decoded frames."""
    expanded=deepcopy(scene)
    for b in expanded['beats']:
        for e in list(b['events']):
            if e.get('composite_pin'):
                partner={**e,'id':e['id']+'_right','pin':{'pexels':e['composite_pin']},'query':'Closing sunrise'}
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
            rows.append(dict(id=o['id'],kind=kind,start=t,line=i+1,cue=spec.get('at',0),meaning=spec.get('meaning','Scripture'),source=(spec.get('pin') or {}).get('pexels')))
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
    data['bulletCaptions']=[dict(start=start,end=end,words=[dict(text='✓ '+label,start=render.resolve_at(cue,bw,*spans[24],{})) for cue,label in [('work','Work'),('Earn','Earn'),('Save','Save'),('Provide','Provide')]])]
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
           'Normal captions retain size 92. The cumulative four-item bullet line uses size 60 in the same fixed band so all four fit without wrapping.',
           f"Final pause: {voice['ending_pause_edit']['original_seconds']:.3f} → 0.700 s; 20 ms crossfade within silence. Music mixed continuously after the cut.",
           '', '| Line / exact narration | Cue → visual and source |','|---|---|']
    for i,b in enumerate(scene['beats']):
        entries=[]
        for r in data['editorialShots']:
            if r['line']!=i+1:continue
            src=by.get(r['id']);url=src['page'] if src else 'existing hand-drawn runtime'
            if not r.get('shown',True):
                entries.append(f"**{r['cue']}**: previous scripture card remains for its required hold; fetched source {url} is superseded, not shown.")
                continue
            entries.append(f"{r['start']:.2f}s, **{r['cue']}**: {r['meaning']} — {url}")
            if r['id']=='shot_27_1':entries.append('Right half: https://www.pexels.com/video/29119700/')
        if i in REACTIONS:
            cue,emotion,_=REACTIONS[i];rec=next((r for r in reactions if r['emotion']==emotion),None)
            entries.append(f"**{cue}** reaction: {rec['origin']} — {rec.get('source','private reactions/')}" if rec else f'ERROR missing reaction {emotion}')
        lines.append('| '+str(i+1)+'. '+b['narration'].replace('|','/')+' | '+'<br>'.join(entries)+' |')
    lines+=['','All third-party reaction files and narration remain in the private voice repository. No public Actions artifacts.',
            'The FOR SALE lettering is an editorial sign on the sale shot. Driving is a wheel/road detail, not a second identifiable car exterior.',
            'Stock people illustrate the fictional story; the footage is not evidence of actual dishonesty or vehicle defects.',
            'The lot is an establishing shot, engine/dashboard are component details, and SAME CAR uses the exact same source twice in one composed frame.',
            'Phone/card is a payment illustration; it does not show an invented real bank notification. EARN uses a payroll animation.',
            'Bible prefixes use different IDs before the unchanged scripture card; no competing footage during typing.']
    (work/'shot-list.md').write_text('\n'.join(lines)+'\n')
    (work/'shot-list.json').write_text(json.dumps(dict(shots=data['editorialShots'],sources=sources,reactions=reactions),indent=2))


def review_sheet(data,video,work):
    from PIL import Image,ImageDraw
    rows=data['editorialShots'];times=[.3]
    def at(line,cue=None,offset=.25):
        r=next(r for r in rows if r['line']==line and (cue is None or r['cue']==cue));return min(r['start']+offset,r['end']-.05)
    times += [16.4,at(10,offset=.7),at(12,'feed'),next(r['start']+2 for r in rows if r['line']==13 and r['kind']=='scripture'),at(21,'almost')-.8,at(25,'Provide')+.15,at(27,offset=.6)]
    # Use actual meme timestamp, never an estimated narration clock.
    memes=json.loads((work/'reactions.json').read_text());times[1]=memes[0]['t']+.2
    times[5]=next(m['t']+.3 for m in memes if m['emotion']=='celebration')
    sheet=Image.new('RGB',(2160,2000),'#f4f1ea');d=ImageDraw.Draw(sheet)
    for i,t in enumerate(times):
        p=work/f'review_{i}.jpg';subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',str(video),'-frames:v','1','-vf','scale=540:960','-y',str(p)],check=True)
        x=i%4*540;y=i//4*1000;sheet.paste(Image.open(p),(x,y));d.text((x+12,y+970),f'{t:.2f}s',fill='black')
    p=video.parent/'eight-frames.jpg';sheet.save(p,quality=92)
    return times
