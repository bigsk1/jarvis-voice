"""FilmCraft source trimming, fitted overlays, and native project revisions."""
import json
import math
import re
import shutil
import zipfile
from fractions import Fraction
from pathlib import Path

from .images import caption_box

TICKS = 254016000000


def native_number(value):
    """Accept both numeric JSON and FilmCraft's debug-formatted scalar values."""
    if isinstance(value, dict):
        value = value.get('value')
    if isinstance(value, str):
        match = re.fullmatch(r'Float\(([^()]+)\)', value)
        value = match[1] if match else value
    if isinstance(value, bool):
        raise ValueError('Invalid native font size')
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid native font size') from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError('Invalid native font size')
    return number


def output_settings(op, info):
    """Keep aspect ratio for implicit sizing; explicit dimensions remain user-controlled."""
    if op.action == 'assemble':
        return op.width, op.height, op.fps
    width, height = info['width'], info['height']
    if 'width' in op.model_fields_set and 'height' in op.model_fields_set:
        width, height = op.width, op.height
    elif 'width' in op.model_fields_set:
        height = max(16, round(height * op.width / width / 2) * 2)
        width = op.width
    elif 'height' in op.model_fields_set:
        width = max(16, round(width * op.height / height / 2) * 2)
        height = op.height
    else:
        scale = min(1, 1920 / width, 1080 / height)
        width, height = max(16, math.floor(width * scale / 2) * 2), max(16, math.floor(height * scale / 2) * 2)
    fps = op.fps if 'fps' in op.model_fields_set else min(60, info['fps'])
    return width, height, fps


def media_info(engine, path):
    probe = shutil.which('ffprobe')
    if not probe:
        raise RuntimeError('Video editing requires ffprobe')
    data = json.loads(engine.run('-v', 'error', '-show_streams', '-show_format', '-of', 'json', path, executable=probe))
    streams = [stream for stream in data.get('streams', []) if stream.get('codec_type') == 'video']
    if not streams:
        raise ValueError('Source has no video or image stream')
    stream = streams[0]
    rate = float(Fraction(stream.get('avg_frame_rate') or '0/1'))
    duration = data.get('format', {}).get('duration') or stream.get('duration')
    return {'width': int(stream['width']), 'height': int(stream['height']), 'fps': (rate or 24) if duration else 24,
            'duration': float(duration) if duration else None}


def command(call, name, params):
    result = call('command_run', {'id': name, 'params': params})
    if isinstance(result, dict) and (result.get('error') or result.get('errors')):
        raise RuntimeError('FilmCraft action failed: ' + str(result)[:800])
    return result or {}


def fit_source(call, placed, info, width, height):
    """A sequence resize alone crops at native 100% scale; fit each video clip."""
    ids = set(placed.get('clips', []))
    sequence = call('sequence_inspect', {})
    video_ids = [item['clip'] for track in sequence['video'] for item in track['items'] if item['clip'] in ids]
    if not video_ids:
        raise ValueError('FilmCraft did not place the source video/image clip')
    scale = min(width / info['width'], height / info['height']) * 100
    for clip in video_ids:
        for param, value in (('scale', scale), ('position', [width / 2, height / 2]),
                             ('anchor', [info['width'] / 2, info['height'] / 2])):
            command(call, 'effects.setParam', {'clip': clip, 'effect': 'motion', 'param': param, 'value': value})


def graphic_layers(call, sequence):
    result = []
    for track in sequence['video']:
        for clip in track['items']:
            if not any(effect['effect'] == 'graphic_text' for effect in clip.get('effects', [])):
                continue
            graphic = command(call, 'graphics.list', {'clip': clip['clip']})
            for layer in graphic['layers']:
                if layer['kind'] == 'text':
                    result.append({**layer, 'clip': clip['clip'], 'start': clip['start'] / TICKS,
                                   'duration': clip['duration'] / TICKS})
    return result


def fit_graphic(call, clip, layer, width, height, size):
    for _ in range(24):
        command(call, 'graphics.set', {'clip': clip, 'layer': layer, 'props': {'size': size}})
        graphic = command(call, 'graphics.list', {'clip': clip})
        matches = [item for item in graphic['layers'] if item['layer'] == layer and item['kind'] == 'text']
        if len(matches) != 1:
            raise ValueError('Selected graphic text layer does not exist')
        item = matches[0]
        if (not item['overflow'] and all(0 <= x <= width and 0 <= y <= height for x, y in item['quad'])):
            return item
        size = math.floor(size * .85)
        if size < 8:
            raise ValueError('Video text cannot fit readably; shorten it or enlarge the frame')
    raise ValueError('Video text layout did not converge')


def add_text(call, edit, sequence):
    settings = sequence['settings']
    width, height = settings['width'], settings['height']
    duration = sequence['duration'] / TICKS
    if edit.action == 'update_text':
        matches = [item for item in graphic_layers(call, sequence) if item['clip'] == edit.clip and item['layer'] == edit.layer]
        if len(matches) != 1:
            raise ValueError('Select an existing text overlay using its returned clip and layer IDs')
        saved = matches[0]
        # Document seconds can round during JSON serialization. Allow one
        # native tick of roundoff, never write these values back as timing.
        if ((edit.start != 0 and not math.isclose(edit.start, saved['start'], rel_tol=0, abs_tol=1 / TICKS))
                or (edit.duration is not None and not math.isclose(edit.duration, saved['duration'], rel_tol=0, abs_tol=1 / TICKS))):
            raise ValueError('Text revisions retain the existing clip timing; omit timing or copy it from document.overlays')
        clip, layer = edit.clip, edit.layer
        # Inspect and validate before mutating the editing session.
        effect = next(item['effects'][matches[0]['effectIndex']] for track in sequence['video']
                      for item in track['items'] if item['clip'] == clip)
        size = edit.font_size if edit.font_size is not None else native_number(effect['params']['size'])
        text = edit.text if edit.text is not None else matches[0]['text']
        if edit.text is not None:
            command(call, 'graphics.setText', {'clip': clip, 'layer': layer, 'text': text})
        if edit.placement:
            box = caption_box({'width': width, 'height': height}, edit.placement, 2)
            command(call, 'graphics.set', {'clip': clip, 'layer': layer, 'props': {
                'position': box[:2], 'box_width': box[2], 'box_height': box[3]}})
    else:
        text = edit.text
        length = edit.duration if edit.duration is not None else duration - edit.start
        if length <= 0 or edit.start + length > duration + .000001:
            raise ValueError('Title/caption timing must lie inside the edited footage')
        box = caption_box({'width': width, 'height': height}, edit.placement or ('bottom' if edit.action == 'caption' else 'top'), 2)
        size = edit.font_size or min(64, max(12, height * .12))
        track = next((index for index, item in enumerate(sequence['video']) if index > 0 and all(
            clip['end'] / TICKS <= edit.start or clip['start'] / TICKS >= edit.start + length
            for clip in item['items'])), None)
        if track is None:
            if len(sequence['video']) >= 64:
                raise ValueError('Timeline has reached its 64 video track limit')
            command(call, 'sequence.addTracks', {'video': 1, 'audio': 0, 'videoAfter': f'V{len(sequence["video"])}'})
            track = len(sequence['video'])
        created = command(call, 'graphics.newText', {'text': edit.text, 'position': box[:2], 'box': box[2:],
                    'size': size, 'seconds': length, 'track': track, 'time': round(edit.start * TICKS), 'newClip': True})
        clip, layer = created['clip'], created['layer']
        command(call, 'graphics.set', {'clip': clip, 'layer': layer, 'props': {
            'align': 'center', 'fill_color': edit.color or '#ffffff', 'stroke': True,
            'stroke_width': 2, 'stroke_color': '#000000'}})
    if edit.color is not None:
        command(call, 'graphics.set', {'clip': clip, 'layer': layer, 'props': {'fill_color': edit.color}})
    fitted = fit_graphic(call, clip, layer, width, height, size)
    if fitted['text'] != text:
        raise ValueError('FilmCraft did not retain the complete requested text')


def project_media(engine, project):
    """Only follow retained media paths within this gateway project."""
    data = json.loads(project.read_text())
    result = {}
    for item_id, item in data['project']['items'].items():
        media = item['kind'].get('Media', {}).get('media', {}).get('File')
        if media:
            path = Path(media['path']).resolve()
            if not path.is_relative_to(engine.workspace.parent) or not path.is_file():
                raise ValueError('Native media reference is missing or outside this gateway project')
            result[int(item_id)] = path
    return result


def revise_settings(call, op, source_infos):
    """Refit media and reflow text only when the saved frame actually changes."""
    options = {key: getattr(op, key) for key in ('width', 'height', 'fps') if key in op.model_fields_set}
    if not options:
        return
    sequence = call('sequence_inspect', {})
    old = sequence['settings']
    resizing = bool({'width', 'height'} & options.keys())
    if resizing:
        width, height, _ = output_settings(op, {'width': old['width'], 'height': old['height'],
            'fps': old['frame_rate']['num'] / old['frame_rate']['den']})
        if not 16 <= width <= 1920 or not 16 <= height <= 1080:
            raise ValueError('Specify supported output dimensions (16..1920 by 16..1080)')
        options.update(width=width, height=height)
        resizing = (width, height) != (old['width'], old['height'])
    sources, graphics = [], []
    if resizing:
        for track in sequence['video']:
            for item in track['items']:
                if not any(effect['effect'] == 'graphic_text' for effect in item.get('effects', [])):
                    info = source_infos.get(item['item'])
                    if info is None:
                        raise ValueError('Cannot refit a timeline clip without its retained source media')
                    sources.append((item['clip'], info))
        sx, sy = width / old['width'], height / old['height']
        for layer in graphic_layers(call, sequence):
            effect = next(item['effects'][layer['effectIndex']] for track in sequence['video']
                          for item in track['items'] if item['clip'] == layer['clip'])
            size = max(8, native_number(effect['params']['size']) * min(sx, sy))
            graphics.append((layer, size, {'position': [layer['position'][0] * sx, layer['position'][1] * sy],
                'box_width': layer['box'][0] * sx, 'box_height': layer['box'][1] * sy}))
    command(call, 'sequence.settings', options)
    if resizing:
        for clip, info in sources:
            fit_source(call, {'clips': [clip]}, info, width, height)
        for layer, size, props in graphics:
            command(call, 'graphics.set', {'clip': layer['clip'], 'layer': layer['layer'], 'props': props})
            fitted = fit_graphic(call, layer['clip'], layer['layer'], width, height, size)
            if fitted['text'] != layer['text']:
                raise ValueError('FilmCraft did not retain the complete saved text')


def metadata(call, sequence):
    settings = sequence['settings']
    result = {'width': settings['width'], 'height': settings['height'],
              'fps': settings['frame_rate']['num'] / settings['frame_rate']['den'],
              'duration': sequence['duration'] / TICKS, 'clips': [], 'overlays': []}
    for kind in ('video', 'audio'):
        for track in sequence[kind]:
            for item in track['items']:
                result['clips'].append({'id': item['clip'], 'track': kind, 'name': item['name'],
                    'start': item['start'] / TICKS, 'duration': item['duration'] / TICKS,
                    'source_start': item['sourceIn'] / TICKS, 'source_end': item['sourceOut'] / TICKS})
    for layer in graphic_layers(call, sequence):
        result['overlays'].append({key: layer[key] for key in ('clip', 'layer', 'text', 'position', 'quad', 'start', 'duration', 'overflow')})
        if layer['overflow'] or any(x < 0 or x > result['width'] or y < 0 or y > result['height'] for x, y in layer['quad']):
            raise ValueError('Saved video contains clipped text')
    for index, first in enumerate(result['overlays']):
        for second in result['overlays'][index + 1:]:
            if first['start'] + first['duration'] <= second['start'] or second['start'] + second['duration'] <= first['start']:
                continue
            a, b = first['quad'], second['quad']
            if (max(x for x, _ in a) > min(x for x, _ in b) and max(x for x, _ in b) > min(x for x, _ in a)
                    and max(y for _, y in a) > min(y for _, y in b) and max(y for _, y in b) > min(y for _, y in a)):
                raise ValueError('Timed text overlays overlap; choose different placement or timing')
    return result


def archive_project(engine, project):
    paths = project_media(engine, project).values()
    with zipfile.ZipFile(engine.workspace / 'video-project.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(project, 'video.fcproj')
        mapping = []
        for index, path in enumerate(dict.fromkeys(paths)):
            name = f'media/{index}_{path.name}'
            archive.write(path, name)
            mapping.append(f'{path.name} -> {name}')
        archive.writestr('README.txt', 'This project retains host media paths. Relink them to the included files when opening elsewhere.\n' + '\n'.join(mapping) + '\n')


def execute_video(engine, op, inputs):
    work = engine.workspace
    project = work / 'video.fcproj'
    reopening = Path(inputs[0]).suffix == '.fcproj'
    # Engine owns one process at a time; probe before opening its MCP session.
    infos = [] if reopening else [media_info(engine, path) for path in inputs]
    source_infos = {}
    if reopening and {'width', 'height'} & op.model_fields_set:
        paths = project_media(engine, Path(inputs[0]))
        cached = {path: media_info(engine, path) for path in dict.fromkeys(paths.values())}
        source_infos = {item: cached[path] for item, path in paths.items()}
    with engine.mcp() as call:
        if reopening:
            if op.action != 'edit' or len(inputs) != 1 or op.clips:
                raise ValueError('Reopen a native timeline with one project source and video_edits, without new clip ranges')
            command(call, 'file.open', {'path': str(inputs[0])})
            revise_settings(call, op, source_infos)
        else:
            width, height, fps = output_settings(op, infos[0])
            if width > 1920 or height > 1080 or not 1 <= fps <= 60 or width < 16 or height < 16:
                raise ValueError('Specify supported output dimensions (16..1920 by 16..1080) and fps (1..60)')
            ranges = [{'source': clip.source, 'start': clip.start, 'end': clip.end} for clip in op.clips]
            if not ranges:
                if op.action == 'assemble':
                    ranges = [{'source': index, 'start': 0, 'end': op.duration} for index in range(len(inputs))]
                elif len(inputs) == 1 and infos[0]['duration'] and infos[0]['duration'] <= 120:
                    ranges = [{'source': 0, 'start': 0, 'end': infos[0]['duration']}]
                else:
                    raise ValueError('Supply explicit clip ranges for these sources')
            if sum(row['end'] - row['start'] for row in ranges) > 120:
                raise ValueError('Timeline exceeds its 120 second limit')
            for row in ranges:
                info = infos[row['source']]
                if info['duration'] and row['end'] > info['duration'] + .000001:
                    raise ValueError('Clip range exceeds the source video duration')
                if info['duration'] is None and row['start'] != 0:
                    raise ValueError('Still images start at zero; end is their display duration')
            imported = command(call, 'file.import', {'paths': list(map(str, inputs))})
            if len(imported.get('items', [])) != len(inputs):
                raise ValueError('FilmCraft could not import all sources')
            command(call, 'file.newSequence', {'name': 'Edit', 'width': width, 'height': height, 'fps': fps, 'video': 2, 'audio': 1})
            position = 0
            for row in ranges:
                length = row['end'] - row['start']
                placed = command(call, 'timeline.place', {'item': imported['items'][row['source']], 'track': 'V1',
                    'seconds': position, 'sourceIn': round(row['start'] * TICKS), 'duration': round(length * TICKS),
                    'insert': False, 'audio': True, 'audioTrack': 'A1'})
                fit_source(call, placed, infos[row['source']], width, height)
                position += length
        for edit in op.video_edits:
            add_text(call, edit, call('sequence_inspect', {}))
        document = metadata(call, call('sequence_inspect', {}))
        if not 0 < document['duration'] <= 120:
            raise ValueError('Edited timeline must have a positive duration up to 120 seconds')
        command(call, 'file.saveAs', {'path': str(project)})
    (work / 'document.json').write_text(json.dumps(document))
    preview_time = min((document['overlays'][0]['start'] + .05) if document['overlays'] else 0, max(0, document['duration'] - 1 / document['fps']))
    engine.run('--project', project, 'render', '--seconds', str(preview_time), '--out', work / 'preview.png')
    if op.output == 'mp4':
        engine.run('--project', project, 'export', work / 'video.mp4')
        exports = [(work / 'video.mp4', 'primary'), (work / 'preview.png', 'preview')]
    else:
        exports = [(work / 'preview.png', 'primary')]
    archive_project(engine, project)
    return exports + [(project, 'project'), (work / 'video-project.zip', 'project'), (work / 'document.json', 'inspection')]
