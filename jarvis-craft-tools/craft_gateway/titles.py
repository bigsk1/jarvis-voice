"""Fitted EffectCraft titles using native full text bounds, not guessed anchors."""
import json
import math


def create_title(call, op):
    call('execute_command', {'id': 'comp.new', 'params': {'name': 'Title', 'width': op.width,
         'height': op.height, 'frameRate': op.fps, 'duration': op.duration, 'background': op.background}})
    margin = max(4, math.ceil(min(op.width, op.height) * .06))
    call('execute_command', {'id': 'layer.newText', 'params': {'text': op.text, 'name': 'Text',
         'box': [margin, margin, op.width - 2 * margin, op.height - 2 * margin],
         'justify': 'center', 'size': op.font_size, 'fill': op.color}})
    size = op.font_size
    for _ in range(24):
        # Fixed, reviewed inspection script. No client-supplied source code.
        reply = call('run_script', {'code': 'JSON.stringify(app.project.activeItem.layer(1).sourceRectAtTime(0, false));'})
        if not reply.get('ok') or reply.get('error'):
            raise RuntimeError('EffectCraft could not inspect title bounds')
        rect = json.loads(reply['result'])
        left, top = rect['left'] + op.width / 2, rect['top'] + op.height / 2
        bounds = [left, top, left + rect['width'], top + rect['height']]
        if bounds[0] >= margin and bounds[1] >= margin and bounds[2] <= op.width - margin and bounds[3] <= op.height - margin:
            break
        size = math.floor(size * .85)
        if size < 8:
            raise ValueError('Title cannot fit readably; shorten the text or enlarge the composition')
        call('execute_command', {'id': 'layer.setText', 'params': {'layer': 'Text', 'size': size}})
    else:
        raise ValueError('Title layout did not converge')
    source = call('get_property', {'layer': 'Text', 'path': 'text/sourceText'})
    if source.get('value') != op.text:
        raise ValueError('EffectCraft did not retain the complete title')
    call('add_keyframe', {'layer': 'Text', 'path': 'transform/opacity', 'keys': [
        {'time': 0, 'value': 100}, {'time': op.duration * .8, 'value': 100},
        {'time': op.duration, 'value': 0}]})
    return {'width': op.width, 'height': op.height, 'layers': [
        {'name': 'Text', 'text': op.text, 'bounds': bounds, 'font_size': size, 'fully_visible': True}]}
