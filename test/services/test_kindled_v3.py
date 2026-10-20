import json,hashlib
from pathlib import Path
import pytest
from kindled_iron import love_money_v3 as v,scripture,render
SCENE=Path(__file__).parents[2]/'kindled_iron/scenes/love-of-money-v3.json'
def test_owner_scene_and_verses():
 s=json.loads(SCENE.read_text());assert s['id']=='love-of-money-v3';assert s['exact_narration'];assert len(s['beats'])==16
 assert all(x['ok'] for x in scripture.check_scene(s,lambda x:None))
 files=[e['file'] for b in s['beats'] for e in b['events'] if e.get('file')]
 assert max(__import__('collections').Counter(files).values())<=2
 pops=[e for b in s['beats'] for e in b['events'] if e.get('reaction_popup')]
 assert len(pops)==3 and all(e['w']>=380 and e['display_dur']<=1.5 for e in pops)
def test_missing_named_file_fails(tmp_path,monkeypatch):
 (tmp_path/'movie_reference').mkdir();(tmp_path/'movie_reference/index.json').write_text('{"items":[]}')
 monkeypatch.setenv('KI_PRIVATE_MEDIA',str(tmp_path))
 s=dict(beats=[dict(id='test',narration='No missing file',events=[dict(file='missing.jpg',id='missing')])])
 with pytest.raises(SystemExit,match='missing.jpg'):v.resolve_media(s,tmp_path)
def test_hebrews_pages_and_word_timing():
 s=json.loads(SCENE.read_text());e=next(e for e in s['beats'][11]['events'] if e.get('scripture'));words=[dict(word=w,start=i*.2,end=i*.2+.18) for i,w in enumerate(render.words_of(s['beats'][11]['narration']))]
 o,event=render.scripture_card(e,words,0,0,'hebrews');assert o['size']==64;assert o['page_break']['word']==14
 assert o['lines'][o['page_break']['line']-1].endswith('have,');assert max(p['height'] for p in o['page_layouts'])<=500
 assert len(o['word_times'])==len(scripture.words(e['scripture']['text']))
