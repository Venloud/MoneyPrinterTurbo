"""Full Love of Money review, using the approved preview scene and original voice.

Uploaded reads keep their natural cadence, with only the requested ending-silence
edit. Generated reads may extend quiet paragraph gaps for the original choreography.
The spoken words and their order stay exactly as approved.
No publishing capability is used by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np

from kindled_iron import money_preview, render, tts, whisper_transcribe
from kindled_iron.pacing import words_of


def assemble_read(scene, audio, sr, aligned):
    """Insert silent gaps into the real read and shift all word times with the audio."""
    counts=[len(words_of(b['narration'])) for b in scene['beats']]
    boundaries=np.cumsum([0]+counts).tolist()
    if boundaries[-1]!=len(aligned):
        raise ValueError('approved script and aligned word counts differ')
    cuts=[0]
    for k in boundaries[1:-1]:
        cuts.append(round((aligned[k-1]['end']+aligned[k]['start'])*sr/2))
    cuts.append(len(audio))
    if any(a>b for a,b in zip(cuts,cuts[1:])):
        raise ValueError('word alignment produced reversed paragraph cuts')
    chunks=[];cursor=0;words=[];spans=[];last_reaction=None
    for i,beat in enumerate(scene['beats']):
        bw=aligned[boundaries[i]:boundaries[i+1]]
        def shifted():
            offset=(cursor-cuts[i])/sr
            return [dict(word=w['word'],start=w['start']+offset,end=w['end']+offset) for w in bw]
        moved=shifted()
        reaction=next((e for e in beat['events'] if e.get('reaction')),None)
        reaction_t=None
        if reaction:
            reaction_t=render.resolve_at(reaction['at'],moved,moved[0]['start'],moved[-1]['end'],{})
            if last_reaction is not None and reaction_t-last_reaction<3.05:
                n=math.ceil((3.05-(reaction_t-last_reaction))*sr)
                chunks.append(np.zeros(n,dtype=audio.dtype));cursor+=n
                moved=shifted();reaction_t+=n/sr
            last_reaction=reaction_t
        words.append(moved);spans.append((0.0 if i==0 else moved[0]['start'],moved[-1]['end']))
        part=audio[cuts[i]:cuts[i+1]];chunks.append(part);cursor+=len(part)
        if i+1<len(counts):
            gap=1.4 if (i+1)%3==0 else 1.3 if not beat['captions'] else .35
            if reaction and scene['beats'][i+1].get('serious'):
                gap=max(gap,reaction_t+reaction['dur']+.35-moved[-1]['end'])
            natural=aligned[boundaries[i+1]]['start']-bw[-1]['end']
            n=max(0,math.ceil((gap-natural)*sr))
            chunks.append(np.zeros(n,dtype=audio.dtype));cursor+=n
    tail=max(0,math.ceil((spans[-1][1]+scene.get('end_hold',1.2))*sr)-cursor)
    chunks.append(np.zeros(tail,dtype=audio.dtype))
    return np.concatenate(chunks),spans,words


def retime_moves(scene, spans):
    """Reuse the authored walking poses, placed in the actual paragraph silences."""
    for i,beat in enumerate(scene['beats']):
        for e in beat['events']:
            if i==0 and e.get('do') in ('place','walk'):
                e['at']=(.05 if e['do']=='walk' else 0)-spans[0][0]
            elif i and e.get('do') in ('face','walk'):
                e['at']=spans[i-1][1]+(.30 if e['do']=='face' else .55)-spans[i][0]


def shorten_final_silence(audio,sr,start,end,target=.7,crossfade=0):
    """Crossfade only inside the specified silence; all other samples remain intact."""
    if end-start<=target:return audio,dict(removed_seconds=0)
    n=round(crossfade*sr)
    a=round((start+(target+crossfade)/2)*sr);b=round((end-(target+crossfade)/2)*sr)
    if n:
        ramp=np.linspace(0,1,n,dtype=np.float32)
        middle=audio[a-n:a]*(1-ramp)+audio[b:b+n]*ramp
        edited=np.concatenate([audio[:a-n],middle,audio[b+n:]])
    else:edited=np.concatenate([audio[:a],audio[b:]])
    return edited,dict(silence_start=start,silence_end=end,original_seconds=end-start,
        kept_seconds=target,cut_start=a/sr,cut_end=b/sr,crossfade_seconds=n/sr,
        removed_seconds=(b-a+n)/sr)


def uploaded_read(source,work,target=.7):
    import soundfile as sf
    raw=work/'uploaded_raw.wav'
    subprocess.run(['ffmpeg','-y','-v','error','-i',str(source),'-ac','1','-ar','44100','-c:a','pcm_f32le',str(raw)],check=True)
    audio,sr=sf.read(raw,dtype='float32')
    r=subprocess.run(['ffmpeg','-hide_banner','-i',str(raw),'-af','silencedetect=noise=-40dB:d=0.7','-f','null','-'],capture_output=True,text=True,check=True)
    starts=[];gaps=[]
    for kind,value in re.findall(r'silence_(start|end): ([0-9.]+)',r.stderr):
        if kind=='start':starts.append(float(value))
        elif starts:gaps.append((starts.pop(),float(value)))
    candidates=[(a,b) for a,b in gaps if a>len(audio)/sr-20 and b<len(audio)/sr-.3 and b-a>target]
    if not candidates:raise SystemExit('FAIL: could not identify the long final pause without changing speech')
    start,end=max(candidates,key=lambda x:x[1]-x[0])
    audio,edit=shorten_final_silence(audio,sr,start,end,target,crossfade=.02)
    sf.write(raw,audio,sr,subtype='FLOAT')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    voice=dict(provider_used='user_upload',source_filename=source.name,source_sha256=digest,
               regenerated=False,speed_changed=False,ending_pause_edit=edit,
               cache_key='uploaded-'+digest[:24]+'-ending-'+str(round(target*1000))+'-xf20')
    render.log(f'Using uploaded narration unchanged except final silence: {end-start:.3f}s -> {target:.3f}s')
    return raw,audio,sr,voice


def continuous_timings(scene,aligned):
    words=[];spans=[];k=0
    for i,b in enumerate(scene['beats']):
        n=len(words_of(b['narration']));bw=aligned[k:k+n];k+=n
        words.append(bw);spans.append((0 if i==0 else bw[0]['start'],bw[-1]['end']))
    if k!=len(aligned):raise ValueError('uploaded voice word count differs from approved script')
    return spans,words


def slow_moves(scene,spans,words,speed=140):
    """Distance-driven gait over six spots; stop for every gesture and scripture hold."""
    for i,b in enumerate(scene['beats']):
        b['events']=[e for e in b['events'] if e.get('do') not in ('walk','place') and
                     (e.get('do')!='face' or i==len(scene['beats'])-1)]
    protected=[];reactions=[]
    gestures={'point','reach','touch','present','shrug','wave','react'}
    for i,b in enumerate(scene['beats']):
        if not b['captions']:protected.append((spans[i][0]-.3,spans[i][1]+1.1))
        for e in b['events']:
            if e.get('reaction') or e.get('do') in gestures:
                t=render.resolve_at(e.get('at'),words[i],*spans[i],{})
                protected.append((t-.35,t+e.get('dur',e.get('hold',1.5))+.65))
                if e.get('reaction'):reactions.append((i,e,t))
    moves=[];current=160;end=0;spots=[310,460,610,760,920,760,610,460,310,160,310,460]
    scene['beats'][0]['events'].insert(0,dict(at=0,do='place',who='guide',x=160,facing=1))
    for k,i in enumerate([1,3,6,9,11,14,16,18,20,23,25]):
        if i>=len(spans)-1:continue
        target=spots[len(moves)%len(spots)];dur=abs(target-current)/speed
        t=max(spans[i][0]+.15,end+1.0)
        for _ in range(30):
            hit=next(((a,b) for a,b in sorted(protected) if t<b and t+.25+dur+.25>a),None)
            if not hit:break
            t=hit[1]+.1
        if t+.25+dur+.25>spans[min(i+2,len(spans)-2)][1]:continue
        scene['beats'][i]['events'] += [dict(at=t-spans[i][0],do='face',who='guide',facing=1 if target>current else -1),
            dict(at=t+.25-spans[i][0],do='walk',who='guide',to=target,speed=speed)]
        end=t+.25+dur+.25;moves.append((t,end,target));current=target
    for i,e,t in reactions:
        x=160
        for a,b,target in moves:
            if b<=t:x=target
        e['card']['x']=x+270 if x<=540 else x-270
    return moves


def fit_continuous_visuals(data):
    """Hold cards on the natural read without inserting silence or covering them with footage."""
    objs={o['id']:o for o in data['objects']}
    draws={e['id']:e for e in data['events'] if e['do']=='draw'}
    cards=sorted((o for o in objs.values() if o['type']=='scripture'),key=lambda o:o['_t0'])
    for a,b in zip(cards,cards[1:]):a['_t1']=min(a['_t1'],b['_t0'])
    coverage=[];last=None;suppressed=set()
    for need in sorted(data['mediaCoverage'],key=lambda n:n['from']):
        n=dict(need);own=objs[n['id']]
        if n['kind']=='scripture':
            event=draws[n['id']];show=event.get('show_at',n['from'])
            if last and last['_t1']>show:
                show=min(last['_t1'],own['_t0'])
                if show>n['from']:
                    coverage.append(dict(id=last['id'],kind='scripture',**{'from':n['from'],'to':min(show,n['to'])}))
                    n['from']=show
            event['show_at']=show;last=own
        elif last and last['_t1']>n['from']:
            start=last['_t1']
            if n['to']-start<.6:
                last['_t1']=max(last['_t1'],n['to']);start=n['to'];suppressed.add(n['id'])
            coverage.append(dict(id=last['id'],kind='scripture',**{'from':n['from'],'to':min(start,n['to'])}))
            if start<n['to']:
                draws[n['id']]['t']=start;own['display_dur']=n['to']-start;n['from']=start
            else:continue
        if n['to']>n['from']:coverage.append(n)
    data['events']=[e for e in data['events'] if not (e['do']=='draw' and e.get('id') in suppressed)]
    for e in data['events']:
        if e['do']=='fade':
            touched=[o['_t1'] for o in cards if o['id'] in (e.get('ids') or [e.get('id')])]
            if touched:e['t']=max(touched)
    data['events'].sort(key=lambda e:e['t'])
    data['mediaCoverage']=coverage
    data['captionSuppress']=[dict(start=o['_t0'],end=o['_t1']) for o in cards]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('script',type=Path);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--work',type=Path,required=True);ap.add_argument('--prepare-only',action='store_true');ap.add_argument('--audio',type=Path);a=ap.parse_args()
    a.work=a.work.resolve();a.work.mkdir(parents=True,exist_ok=True);a.out=a.out.resolve();a.out.parent.mkdir(parents=True,exist_ok=True)
    text=a.script.read_text();scene,_,_,_=money_preview.build(text)
    from kindled_iron import money_editorial
    if a.audio:money_editorial.expand(scene)
    flat=[w for b in scene['beats'] for w in words_of(b['narration'])]
    spoken='\n\n'.join(' '.join(words_of(b['narration'])) for b in scene['beats'])
    profile=tts.load_profile('kindled_iron')
    import soundfile as sf
    if a.audio:
        raw,audio,sr,voice=uploaded_read(a.audio,a.work)
    else:
        raw=a.work/'narration_raw.wav'
        voice=tts.voice([(spoken,0.0)],raw,profile,'elevenlabs',render.log,strict=True)
        if voice['provider_used']!='elevenlabs' or voice.get('fallback'):
            raise SystemExit('FAIL: this review requires the original ElevenLabs voice')
        voice.setdefault('voice_id',profile['elevenlabs']['voice_id'])
        voice.setdefault('model',profile['elevenlabs']['model_id'])
        audio,sr=sf.read(raw,dtype='float32')
    cache=tts._cache_dir()/(voice['cache_key']+'.words.json')
    saved=json.loads(cache.read_text()) if cache.exists() else {}
    if saved.get('script_words')==flat:
        heard=saved['heard'];render.log('reusing cached real-voice word timestamps')
    else:
        heard=whisper_transcribe.transcribe(raw,'small.en')
        cache.write_text(json.dumps(dict(script_words=flat,heard=heard)))
    if not heard:raise SystemExit('FAIL: no words detected in the original narration')
    aligned=whisper_transcribe.align(flat,heard,(0,len(audio)/sr))
    if a.audio:
        spans,words=continuous_timings(scene,aligned)
        moves=slow_moves(scene,spans,words)
        voice['walking_speed']=140;voice['walks']=moves
    else:
        audio,spans,words=assemble_read(scene,audio,sr,aligned)
        retime_moves(scene,spans)
    duration=max(len(audio)/sr,spans[-1][1]+scene.get('end_hold',1.2))
    wav=a.work/'narration.wav';sf.write(wav,audio,sr)
    (a.work/'timings.json').write_text(json.dumps(dict(spans=spans,words=words,voice=voice),indent=2))
    (a.work/'scene.json').write_text(json.dumps(scene,indent=2))
    if a.prepare_only:
        render.log(f'Original narration and measured word timings ready: {duration:.2f}s')
        return
    data,memes=money_preview.resolve_media(scene,spans,words,duration,a.work,require_all=not bool(a.audio))
    if a.audio:fit_continuous_visuals(data)
    if a.audio:money_editorial.report(scene,data,voice,a.work)
    if data['captions']:data['captions'][0]['start']=0.0  # visible opening, with real word highlight times
    from kindled_iron import sound
    flat_words=[w for bw in words for w in bw]
    cues=sound.plan(data['events'],data['objects'],scene,spans,words=flat_words)
    music,music_meta=render.music_choice('generated',profile,render.log)
    mixed=sound.mix(wav,cues,scene,spans,flat_words,duration,a.work/'mix.wav',a.work/'mix_novoice.wav',music,render.log)
    page=render.write_page(data,a.work)
    render.capture(page,a.out,a.work/'mix.wav',duration,None)
    audit=json.loads((a.work/'strict_layout.json').read_text())
    if not audit['passed']:raise SystemExit('FAIL: strict frame audit did not pass')
    sheet_times=money_editorial.review_sheet(data,a.out,a.work) if a.audio else []
    meta=dict(scene=scene['id'],duration=duration,words=len(flat),script_sha256=hashlib.sha256(text.encode()).hexdigest(),
              voice=voice,music=music_meta,reactions=memes,audit=audit,audio={k:mixed.get(k) for k in ('lufs','voice_lufs','true_peak')},
              full_render=True,published=False,review_frame_times=sheet_times,editorial_shots=data.get('editorialShots',[]))
    a.out.with_suffix('.json').write_text(json.dumps(meta,indent=2))
    render.log(f'Private review ready: {a.out.name}, {duration:.2f}s, source narration, {len(memes)} reaction images')


if __name__=='__main__':main()
