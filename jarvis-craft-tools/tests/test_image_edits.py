"""Editing contracts and the partial-caption regression."""
import pytest
from craft_gateway.images import text_fits
from craft_gateway.models import Operation


def test_partial_paragraph_is_not_a_successful_caption():
    info = {'bounds': [20, 20, 400, 70], 'lines': [{'start': 0, 'end': 9}]}
    assert not text_fits(info, [10, 10, 600, 100], 'WHEN THE UPLOAD CANCELS')
    info['lines'].append({'start': 9, 'end': 23})
    assert text_fits(info, [10, 10, 600, 100], 'WHEN THE UPLOAD CANCELS')
    info['bounds'][0] = -1
    assert not text_fits(info, [10, 10, 600, 100], 'WHEN THE UPLOAD CANCELS')


@pytest.mark.parametrize('edits,inputs', [
    ([], ['a'*32]),
    ([{'action': 'text', 'text': '   '}], ['a'*32]),
    ([{'action': 'update_text', 'text': 'Hello'}], ['a'*32]),
    ([{'action': 'text', 'text': 'Hello', 'command': 'file.open'}], ['a'*32]),
    ([{'action': 'resize', 'width': 9000, 'height': 100}], ['a'*32]),
    ([{'action': 'text', 'text': 'Hello', 'color': 'red'}], ['a'*32]),
    ([{'action': 'overlay', 'source': 1, 'x': 0, 'y': 0, 'width': 10, 'height': 10}], ['a'*32]),
    ([{'action': 'text', 'text': 'Hello'}], ['a'*32, 'b'*32]),
])
def test_reject_invalid_edits_and_unused_sources(edits, inputs):
    with pytest.raises(ValueError):
        Operation(app='photocraft', action='edit', inputs=inputs, edits=edits)


def test_ordered_edits_roundtrip_for_durable_job_recovery():
    op = Operation(app='photocraft', action='edit', inputs=['a'*32, 'b'*32], edits=[
        {'action': 'resize', 'width': 800, 'height': 450},
        {'action': 'overlay', 'source': 1, 'x': 600, 'y': 300, 'width': 100, 'height': 100},
        {'action': 'text', 'text': 'A meme', 'placement': 'top'},
    ])
    restored = Operation.model_validate_json(op.model_dump_json(exclude_unset=True))
    assert [edit.action for edit in restored.edits] == ['resize', 'overlay', 'text']
    assert restored.edits[-1].text == 'A meme'


def test_title_uses_native_bounds_and_refuses_failed_inspection():
    from craft_gateway.titles import create_title
    calls=[]
    sizes=[]
    def call(name, args):
        calls.append((name,args))
        if name=='run_script':
            size=100 if not sizes else sizes[-1]
            return {'ok':True,'result':'{"left":-200,"top":-170,"width":400,"height":340}' if size==100 else '{"left":-150,"top":-100,"width":300,"height":200}'}
        if name=='execute_command' and args['id']=='layer.setText':
            sizes.append(args['params']['size'])
        if name=='get_property':
            return {'value':'Long title'}
        return {}
    metadata=create_title(call,Operation(app='effectcraft',action='title',text='Long title',font_size=100))
    assert metadata['layers'][0]['font_size']==85
    assert metadata['layers'][0]['fully_visible']
    assert not any(args.get('path')=='transform/position' for _,args in calls)
    def broken(name,args):
        return {'ok':False,'error':{'message':'unsupported'}} if name=='run_script' else {}
    with pytest.raises(RuntimeError,match='inspect title bounds'):
        create_title(broken,Operation(app='effectcraft',action='title'))


@pytest.mark.parametrize('name',['Caption','UFO top caption'])
def test_revision_accepts_echoed_name_without_renaming(name):
    op=Operation(app='photocraft',action='edit',inputs=['a'*32],edits=[
        {'action':'update_text','layer':3,'name':name,'text':'Revised'}])
    assert op.edits[0].layer==3


@pytest.mark.parametrize('action',['text','update_text'])
def test_glyph_bearing_above_paragraph_box_does_not_shrink_a_visible_caption(monkeypatch,action):
    from craft_gateway import images
    from craft_gateway.image_models import TextEdit
    text="Only if UFO's are real"
    doc={'width':2048,'height':2048,'resolution':72,
         'layers':[{'id':3,'name':'UFO top caption','kind':'Type'}] if action=='update_text' else []}
    info={'text':text,'bounds':[474,89,1572,197],'lines':[{'start':0,'end':len(text)}],
          'shape':{'Box':{'x':0,'y':0,'width':1862,'height':614}},'transform':[1,0,0,1,93,93],
          'runs':[{'style':{'size_pt':28}}],'pxPerPt':1}
    calls=[]
    def command(engine,project,name,params):
        calls.append((name,params))
        return info if name=='type.info' else {'layer':3}
    monkeypatch.setattr(images,'command',command)
    edit=TextEdit(action=action,text=text if action=='text' else None,font_size=110,
                  **({'layer':3,'name':'UFO top caption'} if action=='update_text' else {}))
    assert images.apply_text(None,None,edit,doc)==3
    assert [params['size'] for name,params in calls if name=='type.setStyle']==[110]
    if action=='update_text':
        assert all('name' not in params for _,params in calls)
