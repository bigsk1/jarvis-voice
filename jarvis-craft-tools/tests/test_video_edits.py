"""Video source-range bounds, native project trust, and portable media retention."""
import json
import zipfile
from types import SimpleNamespace

import pytest
from craft_gateway.models import Operation, Submission
from craft_gateway.service import Service
from craft_gateway.videos import archive_project


@pytest.mark.parametrize('options', [
    {},
    {'clips': [{'source': 0, 'start': 3, 'end': 2}]},
    {'clips': [{'source': 1, 'start': 0, 'end': 2}]},
    {'clips': [{'end': 70}, {'end': 70}]},
    {'video_edits': [{'action': 'update_text', 'text': 'Missing target'}]},
    {'video_edits': [{'action': 'title', 'text': 'Wrong target', 'clip': 10}]},
    {'video_edits': [{'action': 'title', 'text': 'Bad color', 'color': 'red'}]},
    {'video_edits': [{'action': 'caption'}]},
])
def test_invalid_video_edits_are_rejected(options):
    with pytest.raises(ValueError):
        Operation(app='filmcraft', action='edit', inputs=['a'*32], **options)


def test_late_source_range_can_make_a_short_bounded_timeline():
    op = Operation(app='filmcraft', action='edit', inputs=['a'*32],
                   clips=[{'start': 300, 'end': 305}], video_edits=[{'action': 'title', 'text': 'Hello'}])
    restored = Operation.model_validate_json(op.model_dump_json(exclude_unset=True))
    assert restored.clips[0].start == 300 and restored.clips[0].end == 305


def test_external_native_project_is_rejected_but_successful_gateway_project_can_reopen(tmp_path):
    service = Service({'state_dir': str(tmp_path), 'apps_root': str(tmp_path)})
    project = service.store.create_project()
    folder = service.store.workspaces / project['id']
    path = folder / 'video.fcproj'
    path.write_text('{}')
    external = service.store.add_artifact(project['id'], path)
    operation = Operation(app='filmcraft', action='edit', inputs=[external['id']],
                          video_edits=[{'action': 'update_text', 'clip': 10, 'text': 'New words'}])
    submission = Submission(request_id='c'*32, project_id=project['id'], revision=0, operation=operation)
    with pytest.raises(ValueError, match='gateway-produced'):
        service.validate_inputs(submission)
    job=service.store.submit(Submission(request_id='d'*32,project_id=project['id'],revision=0,
              operation=Operation(app='photocraft',action='invert',inputs=['a'*32])),'fixture','fixture')
    service.store.finish(job['id'],'succeeded')
    native = service.store.add_artifact(project['id'], path, role='project',job_id=job['id'])
    operation.inputs = [native['id']]
    service.validate_inputs(submission)


def test_archive_retains_all_media_and_distinguishes_duplicate_names(tmp_path):
    project_root = tmp_path / 'project'
    work = project_root / 'job'
    work.mkdir(parents=True)
    files = []
    for directory in ('first', 'second'):
        folder = project_root / directory
        folder.mkdir()
        path = folder / 'source.mp4'
        path.write_bytes(directory.encode())
        files.append(path)
    project = work / 'video.fcproj'
    def write(paths):
        project.write_text(json.dumps({'project': {'items': {str(i): {'kind': {'Media': {'media': {'File': {'path': str(p)}}}}} for i, p in enumerate(paths)}}}))
    write(files)
    engine = SimpleNamespace(workspace=work)
    archive_project(engine, project)
    with zipfile.ZipFile(work / 'video-project.zip') as archive:
        assert archive.read('media/0_source.mp4') == b'first'
        assert archive.read('media/1_source.mp4') == b'second'
        assert 'Relink' in archive.read('README.txt').decode()
    outside = tmp_path / 'outside.mp4'
    outside.write_bytes(b'private')
    write([outside])
    with pytest.raises(ValueError, match='outside this gateway project'):
        archive_project(engine, project)


def test_overlapping_graphic_text_is_rejected_in_final_document():
    from craft_gateway.videos import metadata
    ticks=254016000000
    sequence={'settings':{'width':320,'height':180,'frame_rate':{'num':12,'den':1}},'duration':2*ticks,'audio':[],
              'video':[{'items':[{'clip':id,'duration':2*ticks,'start':0,'sourceIn':0,'sourceOut':2*ticks,
                       'name':'Title','effects':[{'effect':'graphic_text'}]} for id in (10,13)]}]}
    def call(name,args):
        return {'layers':[{'kind':'text','layer':0,'text':'Title','position':[9,9],
                  'quad':[[9,9],[311,9],[311,63],[9,63]],'overflow':False}]}
    with pytest.raises(ValueError,match='overlap'):
        metadata(call,sequence)


@pytest.mark.parametrize('value',[24,24.5,'24.5','Float(24.5)',{'value':24.5},{'value':'Float(24.5)'}])
def test_native_font_size_formats(value):
    from craft_gateway.videos import native_number
    assert 24<=native_number(value)<=24.5


@pytest.mark.parametrize('value',[None,True,{},'Vec2(1,2)','Float(nan)',float('inf'),-1])
def test_invalid_font_size_fails_before_mutating_revision(value):
    from craft_gateway.video_models import VideoText
    from craft_gateway.videos import add_text
    sequence={'settings':{'width':320,'height':180},'duration':2*254016000000,
              'video':[{'items':[{'clip':10,'start':0,'duration':2*254016000000,
                       'effects':[{'effect':'graphic_text','params':{'size':{'value':value}}}]}]}]}
    called=[]
    def call(name,args):
        called.append(args['id'])
        return {'layers':[{'kind':'text','layer':0,'effectIndex':0}]}
    with pytest.raises(ValueError,match='font size'):
        add_text(call,VideoText(action='update_text',clip=10,text='Changed'),sequence)
    assert called==['graphics.list']


@pytest.mark.parametrize('dimensions,expected', [((3840,2160),(1920,1080)),((2160,3840),(606,1080)),((320,180),(320,180))])
def test_implicit_video_sizing_fits_supported_frame_without_changing_aspect(dimensions,expected):
    from craft_gateway.videos import output_settings
    op=Operation(app='filmcraft',action='edit',inputs=['a'*32],clips=[{'end':1}])
    width,height,fps=output_settings(op,{'width':dimensions[0],'height':dimensions[1],'fps':30})
    assert (width,height)==expected and fps==30
    assert abs(width/height-dimensions[0]/dimensions[1])<.002


def test_fitting_scales_only_video_clips_and_centers_the_whole_source():
    from craft_gateway.videos import fit_source
    commands=[]
    def call(name,args):
        if name=='sequence_inspect':
            return {'video':[{'items':[{'clip':7}]}]}
        commands.append(args['params'])
        return {}
    fit_source(call,{'clips':[7,8]},{'width':3840,'height':2160},1920,1080)
    assert {item['clip'] for item in commands}=={7}
    assert {item['param']:item['value'] for item in commands}=={
        'scale':50,'position':[960,540],'anchor':[1920,1080]}


@pytest.mark.parametrize('timing',[{}, {'start':0,'duration':None}, {'start':.5},
                                 {'duration':1}, {'start':.5,'duration':1},
                                 {'start':.5+1e-12,'duration':1+1e-12}])
def test_placement_only_revision_accepts_defaults_or_saved_timing_and_retains_words(timing):
    from craft_gateway.video_models import VideoText
    from craft_gateway.videos import TICKS, add_text
    edit=VideoText(action='update_text',clip=10,placement='top',**timing)
    sequence={'settings':{'width':320,'height':180},'duration':2*TICKS,
              'video':[{'items':[{'clip':10,'start':TICKS/2,'duration':TICKS,
                       'effects':[{'effect':'graphic_text','params':{'size':24}}]}]}]}
    commands=[]
    def call(name,args):
        commands.append(args)
        return {'layers':[{'kind':'text','layer':0,'effectIndex':0,'text':'Keep these words',
                          'overflow':False,'quad':[[9,9],[311,9],[311,63],[9,63]]}]}
    add_text(call,edit,sequence)
    assert {c['id'] for c in commands}=={'graphics.list','graphics.set'}
    assert all(not ({'time','seconds','start','duration','text'} & c.get('params',{}).keys()) for c in commands)
    assert any(c.get('params',{}).get('props',{}).get('position')==[9,9] for c in commands)


@pytest.mark.parametrize('timing',[{'start':1}, {'duration':.5}, {'start':.500001},
                                 {'start':.5,'duration':2}])
def test_actual_timing_change_is_rejected_before_revision_mutation(timing):
    from craft_gateway.video_models import VideoText
    from craft_gateway.videos import TICKS, add_text
    edit=VideoText(action='update_text',clip=10,text='Must not change',placement='top',**timing)
    sequence={'settings':{'width':320,'height':180},'duration':2*TICKS,
              'video':[{'items':[{'clip':10,'start':TICKS/2,'duration':TICKS,
                       'effects':[{'effect':'graphic_text','params':{'size':24}}]}]}]}
    commands=[]
    def call(name,args):
        commands.append(args['id'])
        return {'layers':[{'kind':'text','layer':0,'effectIndex':0,'text':'Saved words'}]}
    with pytest.raises(ValueError,match='retain the existing clip timing'):
        add_text(call,edit,sequence)
    assert commands==['graphics.list']


@pytest.mark.parametrize('options',[{}, {'fps':24}, {'width':320,'height':180}])
def test_revision_preserves_motion_and_layout_without_actual_frame_change(options):
    from craft_gateway.videos import revise_settings
    op=Operation(app='filmcraft',action='edit',inputs=['a'*32],
                 video_edits=[{'action':'update_text','clip':10,'placement':'top'}],**options)
    commands=[]
    def call(name,args):
        if name=='sequence_inspect':
            return {'settings':{'width':320,'height':180,'frame_rate':{'num':12,'den':1}}}
        commands.append(args['id'])
    revise_settings(call,op,{})
    assert commands==(['sequence.settings'] if options else [])


def test_resize_revision_refits_only_media_and_reflows_existing_graphics():
    from craft_gateway.videos import TICKS, revise_settings
    op=Operation(app='filmcraft',action='edit',inputs=['a'*32],width=160,
                 video_edits=[{'action':'update_text','clip':10,'placement':'top'}])
    sequence={'settings':{'width':320,'height':180,'frame_rate':{'num':12,'den':1}},
              'video':[{'items':[{'clip':7,'item':1,'effects':[{'effect':'motion'}]},
                                {'clip':10,'start':TICKS/2,'duration':TICKS,
                                 'effects':[{'effect':'graphic_text','params':{'size':24}}]}]}]}
    commands=[]
    def call(name,args):
        if name=='sequence_inspect':
            return sequence
        commands.append(args)
        return {'layers':[{'kind':'text','layer':0,'effectIndex':0,'text':'Keep',
                          'position':[9,117],'box':[302,54],'overflow':False,
                          'quad':[[4.5,58.5],[155.5,58.5],[155.5,85.5],[4.5,85.5]]}]}
    revise_settings(call,op,{1:{'width':640,'height':360}})
    assert next(c['params'] for c in commands if c['id']=='sequence.settings')=={'width':160,'height':90}
    motion=[c['params'] for c in commands if c['id']=='effects.setParam']
    assert {p['clip'] for p in motion}=={7}
    assert {p['param']:p['value'] for p in motion}=={'scale':25,'position':[80,45],'anchor':[320,180]}
    props=[c['params']['props'] for c in commands if c['id']=='graphics.set']
    assert props==[{'position':[4.5,58.5],'box_width':151,'box_height':27},{'size':12}]
    assert all(c['id']!='graphics.setText' for c in commands)


def test_assemble_retains_legacy_canvas_defaults():
    from craft_gateway.videos import output_settings
    op=Operation(app='filmcraft',action='assemble',inputs=['a'*32])
    assert output_settings(op,{'width':3840,'height':2160,'fps':60})==(640,360,24)
