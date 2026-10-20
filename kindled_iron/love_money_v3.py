"""Owner-recorded, handwritten V3 scene. Private review only; no TTS or publishing."""
from __future__ import annotations
import argparse,copy,hashlib,json,math,os,re,subprocess
from collections import Counter
from pathlib import Path
import numpy as np
from kindled_iron import render,scripture,whisper_transcribe as wt,private_media,insets,effects,sound,tts

def trim_silences(source,work):
 import soundfile as sf
 raw=work/'voice.wav'
 subprocess.run(['ffmpeg','-y','-v','error','-i',str(source),'-ac','1','-ar','44100','-c:a','pcm_f32le',str(raw)],check=True)
 audio,sr=sf.read(raw,dtype='float32');r=subprocess.run(['ffmpeg','-hide_banner','-i',str(raw),'-af','silencedetect=noise=-40dB:d=0.8','-f','null','-'],capture_output=True,text=True,check=True)
 start=None;cuts=[]
 for kind,t in re.findall(r'silence_(start|end): ([0-9.]+)',r.stderr):
  if kind=='start':start=float(t)
  elif start is not None:
   end=float(t)
   if end-start>.8 and start>0 and end<len(audio)/sr-.1:cuts.append((start,end))
   start=None
 edits=[]
 for a,b in reversed(cuts):
  n=round(.02*sr);left=round((a+.26)*sr);right=round((b-.26)*sr);ramp=np.linspace(0,1,n,dtype=np.float32)
  audio=np.concatenate([audio[:left-n],audio[left-n:left]*(1-ramp)+audio[right:right+n]*ramp,audio[right+n:]])
  edits.insert(0,dict(start=a,end=b,kept=.5,crossfade=.02,removed=(right-left+n)/sr))
 sf.write(raw,audio,sr,subtype='FLOAT')
 return raw,len(audio)/sr,dict(provider_used='owner_upload',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),regenerated=False,speed_changed=False,silence_edits=edits)

def cue(e,bw,span):return render.resolve_at(e.get('at'),bw,*span,{})

def prepare(scene,source,work,heard_path=None):
 wav,duration,voice=trim_silences(source,work)
 cache=work/'alignment.json'
 cached=json.loads(cache.read_text()) if cache.exists() else None
 if isinstance(cached,dict) and cached.get('source_sha256')==voice['source_sha256']:heard=cached['heard']
 elif isinstance(cached,list) and os.environ.get('KI_ALIGN_MODEL'):heard=cached # local geometry preflight only
 else:
  heard=wt.transcribe(wav,os.environ.get('KI_ALIGN_MODEL','small.en'));cache.write_text(json.dumps(dict(source_sha256=voice['source_sha256'],heard=heard)))
 texts=[b['narration'] for b in scene['beats']];flat=[w for t in texts for w in render.words_of(t)]
 aligned=wt.align(flat,heard,(0,duration));spans=[];words=[];k=0
 for i,t in enumerate(texts):
  n=len(render.words_of(t));bw=aligned[k:k+n];k+=n;words.append(bw);spans.append((0 if i==0 else bw[0]['start'],bw[-1]['end']))
 return wav,duration,voice,spans,words

def resolve_media(scene,work):
 root=private_media.root()
 if not root:raise SystemExit('FAIL: private movie_reference directory unavailable')
 index=root/'movie_reference'/'index.json';idx=json.loads(index.read_text());byfile={x['file']:x for x in idx.get('items',[])}
 records=[];pins=[]
 for i,b in enumerate(scene['beats']):
  for e in b['events']:
   if e.get('file'):
    if e['id']=='cash_open':e.update(x=410,w=500)
    f=root/'movie_reference'/e['file']
    if not f.is_file():raise SystemExit('FAIL: required file failed to load: '+e['file'])
    still=f.suffix.lower() in private_media.IMG_EXT
    dur=1.2 if e.get('reaction_popup') else 3
    # Full composition is preserved; do not crop subtitles/faces out of owner's memes.
    dest=work/'insets'/e['id'];dest.mkdir(parents=True,exist_ok=True)
    inp=['-stream_loop','-1'] if not still or f.suffix.lower()=='.gif' else ['-loop','1']
    if e['file']=='burning_bush.mp4':inp+=['-ss','2.6']
    vf=f"fps=30,scale={e['w']}:{e['h']}:force_original_aspect_ratio=decrease,pad={e['w']}:{e['h']}:(ow-iw)/2:(oh-ih)/2:color=0xf4f1ea"
    subprocess.run(['ffmpeg','-y','-v','error',*inp,'-i',str(f),'-t',str(dur),'-an','-vf',vf,'-q:v','3',str(dest/'f_%04d.jpg')],check=True)
    frames=[p.as_uri() for p in sorted(dest.glob('f_*.jpg'))]
    if not frames:raise SystemExit('FAIL: required file failed to decode: '+e['file'])
    e.update(frames=frames,fps=30,clip_dur=len(frames)/30)
    byfile[e['file']]={**byfile.get(e['file'],{}),'file':e['file'],'cue':b['narration'] if e.get('at')==0 else e['at'],'use':'POP' if e.get('reaction_popup') else 'BOX','source':'owner upload'}
    records.append(dict(beat=b['id'],cue=e['at'],file=e['file'],use='POP' if e.get('reaction_popup') else 'BOX',source='owner upload',id=e['id']))
   if e.get('pin'):pins.append(e)
 fetched=insets.fetch(scene,work,render.log)
 for e in pins:
  if e['id'] not in fetched:raise SystemExit('FAIL: missing required clip '+e['pin']['pexels'])
  e.update(fetched[e['id']]);records.append(dict(cue=e['at'],id=e['id'],source='Pexels',file=e['pin']['pexels'],use='BOX'))
 idx['items']=list(byfile.values());index.write_text(json.dumps(idx,indent=2)+'\n')
 return records

def timeline(scene,spans,words,duration):
 # Build cards with established checked typewriter and fixed-page layout.
 data=render.build_data(scene,spans,words,duration)
 objs={o['id']:o for o in data['objects']};events=data['events'];visuals=[]
 for e in events:
  o=objs.get(e.get('id'),{})
  if e.get('do')=='freeze':e.update(sound='scratch',sound_dur=.25)
  elif e.get('do')=='draw' and o.get('type') not in ('inset','scripture') and not o.get('overlay'):e.update(main=True)

 for i,b in enumerate(scene['beats']):
  for e in b['events']:
   if e.get('visual') and not e.get('decorative') and not e.get('overlay'):
    t=cue(e,words[i],spans[i]) if not e.get('scripture') else objs[e['id']]['_t0']
    if e['id']=='kakuzu':t+=.45 # let the marker land on 'love' before the anime cut
    visuals.append((t,e['id'],i))
 visuals.sort();cards=[o for o in objs.values() if o['type']=='scripture']
 # The verse holds for one second. Later content waits visually while narration remains untouched.
 for o in cards:
  for j,(t,id,i) in enumerate(visuals):
   if t>o['_t0'] and t<o['quote_end']+1:visuals[j]=(o['quote_end']+1,id,i)
 visuals.sort();windows=[]
 for j,(t,id,i) in enumerate(visuals):
  end=visuals[j+1][0] if j+1<len(visuals) else duration
  if end-t<.025:continue
  o=objs[id];o['v3_visual']=True
  ev=next(e for e in events if e.get('do')=='draw' and e.get('id')==id)
  ev['t']=t
  if o['type']=='inset':o['display_dur']=end-t;o['required']=True
  else:events.append(dict(t=end,do='fade',ids=[id],opacity=0,dur=.001))
  if o['type']=='scripture':ev['show_at']=t
  windows.append(dict(id=id,**{'from':t,'to':end},kind='scripture' if o['type']=='scripture' else 'inset' if o['type']=='inset' else 'drawing'))
 # Composite drawings' pieces follow their main visual, never leak onto subsequent beats.
 for i,b in enumerate(scene['beats']):
  for e in b['events']:
   if not(e.get('overlay') or e.get('decorative')):continue
   t=cue(e,words[i],spans[i]);end=spans[i][1]
   if e['id']=='clown':
    end=cue(next(x for x in b['events'] if x.get('id')=='cash_run'),words[i],spans[i])
    objs['cash_open'].update(x=410,w=500)
   objs[e['id']]['v3_visual']=True
   events.append(dict(t=end,do='fade',ids=[e['id']],opacity=0,dur=.001))
 data['mediaCoverage']=windows
 # Hide every superseded visual deterministically, including drawings and cards.
 data['v3Windows']=windows
 data['captionSuppress']=[dict(start=w['from'],end=w['to']) for w in windows if w['kind']=='scripture']
 # Verse highlights retain the actual card until the requested response, then footage resumes.
 t_love=cue(dict(at='love'),words[4],spans[4]);data['verseHighlights']=[dict(id='timothy_card',start=t_love,end=t_love+.45,text='love of money')]
 # Continuous speaking expressions and gestures every other line.
 for i in range(0,len(spans),2):
  target=next((w['id'] for w in windows if w['from']<=spans[i][0]+.1<w['to']),None)
  if target:events.append(dict(t=spans[i][0]+.1,do='point',who='guide',toward=target,hold=.5,respond=False))
 pop_intervals=[]
 for i,b in enumerate(scene['beats']):
  for e in b['events']:
   if e.get('reaction_popup'):pop_intervals.append(cue(e,words[i],spans[i]))
 # A new drawing can begin while the previous POP finishes; delay the pointing arm,
 # rather than letting that arm sweep through the still-visible reaction card.
 for e in events:
  if e.get('who')=='guide' and e.get('do') in ('point','shrug','present','wave'):
   for t in pop_intervals:
    if e['t']<t+1.45 and e['t']+e.get('hold',.5)+.8>t-.25:e['t']=t+1.45
 protected=[(o['_t0']-.35,o['quote_end']+1.2) for o in cards]
 for e in events:
  if e.get('do') in ('point','shrug','freeze'):protected.append((e['t']-.3,e['t']+e.get('hold',e.get('dur',.6))+1.0))
 # POPs require a clear adjacent lane; keep guide still for their entire duration.
 pops=[]
 for i,b in enumerate(scene['beats']):
  for e in b['events']:
   if not e.get('reaction_popup'):continue
   t=cue(e,words[i],spans[i]);pops.append((t,e['id']));protected.append((t-.3,t+1.5))
 data['guideWalkSpeed']=220
 data['guideSpots']=[330,410,490,570,650,750];x=330;last=0;moves=[]
 for move_index,i in enumerate([1,3,5,7,9,11,13]):
  target=[410,330,330,490,750,650,570][move_index]
  if target==x:continue
  dur=max(.7,abs(target-x)/220);t=max(spans[i][0]+.1,last+.3)
  for _ in range(50):
   hit=next(((a,b) for a,b in sorted(protected) if t+.25+dur+.3>a and t<b),None)
   if not hit:break
   t=hit[1]+.1
  if t+dur+.55>spans[min(i+1,len(spans)-1)][1]:continue
  events.extend([dict(t=t,do='face',who='guide',facing=1 if target>x else -1),dict(t=t+.25,do='walk',who='guide',to=target,speed=220,dur=dur)])
  moves.append(dict(start=t+.25,end=t+.25+dur,to=target));last=t+.25+dur+.3;x=target
 for t,id in pops:
  x=330
  for m in moves:
   if m['end']<=t:x=m['to']
  objs[id]['x']=700 if x<540 else 350;objs[id]['reaction_popup']=True
 data['moves']=moves
 # Cumulative inset bullets pop on the exact spoken word, clear before the next sentence.
 bw=words[13];ws=[]
 for label in ['work','Earn','Save','Provide']:
  w=next(w for w in bw if wt.norm(w['word'])==label.lower());ws.append(dict(text='✓ '+label.upper(),start=w['start']))
 data['bulletOverlays']=[dict(start=ws[0]['start'],end=spans[14][0],words=ws,zone=dict(left=200,top=410,right=880,bottom=605))]
 data['captionSuppress'].append(dict(start=ws[0]['start'],end=spans[14][0]))
 data['captions'][0]['start']=0
 data['sketchActions']=[dict(id='house',start=cue(dict(at='break'),words[6],spans[6]))]
 data['handOpenAt']=cue(dict(at='loosen'),words[12],spans[12])
 data['sketchCues']={'benefits':[cue(dict(at=w),words[5],spans[5]) for w in ['rent','groceries','plane']]}
 data['paper']=effects.paper_texture(Path(os.environ['KI_V3_WORK']),render.PALETTE['board'])
 data['events']=sorted(events,key=lambda e:e['t'])
 return data

def sheet(page,work,times):
 from PIL import Image,ImageDraw
 render.capture(page,None,None,json.loads((work/'data.json').read_text())['duration'],None,times,work/'stills')
 out=Image.new('RGB',(2160,2000),'#222222');d=ImageDraw.Draw(out)
 for i,t in enumerate(sorted(times)):
  im=Image.open(work/'stills'/f'frame_{t:05.2f}.png');im.thumbnail((540,960));x=(i%4)*540;y=(i//4)*1000
  out.paste(im,(x,y));d.text((x+15,y+970),f'{t:.2f}s',fill='white')
 out.save(work/'eight-frames.jpg',quality=95)

def review_sounds(data,scene,spans,words):
 """V3 explicitly requests a few drawing sounds even when the legacy pencil switch is off."""
 cues=sound.plan(data['events'],data['objects'],scene,spans,words=words)
 cues=[c for c in cues if c['role']=='chime']
 picker=sound.Picker();wanted={'myth_book','house','open_hand'}
 for e in data['events']:
  role=None;file=None;dur=.45
  if e.get('do')=='freeze':role='scratch';file='../scratch.ogg';dur=.25
  elif e.get('do')=='draw' and e.get('id') in wanted:
   role='pencil_long';f,_=picker.pick(role);file=f.name if f else None
  if role and file:
   if not (sound.LIB/file).is_file():raise SystemExit('FAIL: required quiet effect '+file)
   cues.append(dict(t=e['t'],role=role,file=file,pitch=1.0,dur=dur,why='owner V3 drawing / freeze cue',weight='small',group=None))
 cues.sort(key=lambda c:c['t'])
 if len(cues)>sound.MAX_EFFECTS:raise SystemExit('FAIL: V3 effects cap exceeded')
 return cues

def main(scene_path,audio,work,phase='preview'):
 work=Path(work).resolve();work.mkdir(parents=True,exist_ok=True);os.environ['KI_V3_WORK']=str(work)
 scene=json.loads(Path(scene_path).read_text());verse=scripture.check_scene(scene,render.log)
 wav,length,voice,spans,words=prepare(scene,Path(audio),work);records=resolve_media(scene,work)
 data=timeline(scene,spans,words,length+scene['end_hold']);(work/'data.json').write_text(json.dumps(data))
 page=render.write_page(data,work)
 # Eight requested story beats, word-aligned rather than arbitrary timestamps.
 def at(i,w,delta=0):return cue(dict(at=w),words[i],spans[i])+delta
 times=[.05,at(2,'Nope',.3),at(4,'love',.25),at(6,'break',.4),spans[8][0]+.2,at(0,'lie',.3),at(13,'Provide',.12),at(15,'Mr',.25)]
 if phase=='preview':sheet(page,work,times)
 else:
  chan=tts.load_profile('kindled_iron');music=dict(level_db=-22,duck_db=3.5,dip_db=3.5,lift_db=2,file=str(private_media.root()/'music'/'theme_1.mp3'),start=0,label='theme_1',lift_at=None)
  cues=review_sounds(data,scene,spans,[w for b in words for w in b])
  (work/'sound-cues.json').write_text(json.dumps(cues,indent=2))
  mixed=sound.mix(wav,cues,scene,spans,[w for b in words for w in b],data['duration'],work/'mix.wav',work/'mix_novoice.wav',music,render.log)
  render.capture(page,work/'love-of-money-v3.mp4',work/'mix.wav',data['duration'],None)
  subprocess.run(['ffmpeg','-v','error','-i',str(work/'love-of-money-v3.mp4'),'-f','null','-'],check=True)
 audit=json.loads((work/'strict_layout.json').read_text());meta=dict(scene=scene['id'],duration=data['duration'],voice=voice,verse_check=verse,audit=audit,moves=data['moves'],cue_files=records,failed_files=[])
 meta['branch']=os.environ.get('GITHUB_REF_NAME','claude/love-money-v3');meta['code_sha']=os.environ.get('GITHUB_SHA',subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
 (work/'metadata.json').write_text(json.dumps(meta,indent=2));lines=['# Love of Money V3', '',f"Branch: {meta['branch']} · code {meta['code_sha']}",f"Duration: {data['duration']:.3f}s · every-frame audit: {audit['passed']} ({audit['frames_checked']} frames)",f"Voice SHA256: {voice['source_sha256']} · synthesized: false · speed changed: false",'Music: private music/theme_1.mp3','Failed files: none','']
 for beat in scene['beats']:
  lines.extend(['## '+beat['id'],beat['narration']])
  for e in beat['events']:
   if e.get('file') or e.get('pin') or e.get('visual'):
    label=e.get('file') or ('Pexels '+e['pin']['pexels'] if e.get('pin') else e.get('type','scripture'))
    lines.append(f"- {e.get('at','quote')} → {label} ({'POP' if e.get('reaction_popup') else 'BOX / drawn'})")
 (work/'shot-list.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps(dict(phase=phase,duration=data['duration'],audit=audit['passed'],frames=audit['frames_checked'])))
