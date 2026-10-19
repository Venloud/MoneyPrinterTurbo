"""Full Love of Money review, using the approved preview scene and original voice.

Only the quiet gaps between paragraphs are extended for walking, scripture holds
and reaction spacing. The spoken words and their order stay exactly as approved.
No publishing capability is used by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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


def main():
    ap=argparse.ArgumentParser();ap.add_argument('script',type=Path);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--work',type=Path,required=True);ap.add_argument('--prepare-only',action='store_true');a=ap.parse_args()
    a.work=a.work.resolve();a.work.mkdir(parents=True,exist_ok=True);a.out=a.out.resolve();a.out.parent.mkdir(parents=True,exist_ok=True)
    text=a.script.read_text();scene,_,_,_=money_preview.build(text)
    flat=[w for b in scene['beats'] for w in words_of(b['narration'])]
    spoken='\n\n'.join(' '.join(words_of(b['narration'])) for b in scene['beats'])
    profile=tts.load_profile('kindled_iron');raw=a.work/'narration_raw.wav'
    voice=tts.voice([(spoken,0.0)],raw,profile,'elevenlabs',render.log,strict=True)
    if voice['provider_used']!='elevenlabs' or voice.get('fallback'):
        raise SystemExit('FAIL: this review requires the original ElevenLabs voice')
    voice.setdefault('voice_id',profile['elevenlabs']['voice_id'])
    voice.setdefault('model',profile['elevenlabs']['model_id'])
    import soundfile as sf
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
    audio,spans,words=assemble_read(scene,audio,sr,aligned)
    retime_moves(scene,spans);duration=len(audio)/sr
    wav=a.work/'narration.wav';sf.write(wav,audio,sr)
    (a.work/'timings.json').write_text(json.dumps(dict(spans=spans,words=words,voice=voice),indent=2))
    (a.work/'scene.json').write_text(json.dumps(scene,indent=2))
    if a.prepare_only:
        render.log(f'Original narration and measured word timings ready: {duration:.2f}s')
        return
    data,memes=money_preview.resolve_media(scene,spans,words,duration,a.work)
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
    meta=dict(scene=scene['id'],duration=duration,words=len(flat),script_sha256=hashlib.sha256(text.encode()).hexdigest(),
              voice=voice,music=music_meta,reactions=memes,audit=audit,audio={k:mixed.get(k) for k in ('lufs','voice_lufs','true_peak')},
              full_render=True,published=False)
    a.out.with_suffix('.json').write_text(json.dumps(meta,indent=2))
    render.log(f'Private review ready: {a.out.name}, {duration:.2f}s, original voice, {len(memes)} reaction images')


if __name__=='__main__':main()
