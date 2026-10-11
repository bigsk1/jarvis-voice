"""PhotoCraft edits with native layer inspection and verified text layout."""
import json
import math


def command(engine, project, name, params):
    replies = engine.run('run', project, '--cmd', name, '--params', json.dumps(params), '--out', project)
    results = [json.loads(line) for line in replies.splitlines() if line.strip()]
    if not results or any(row.get('error') or (row.get('result') or {}).get('error') for row in results):
        raise RuntimeError('PhotoCraft command failed: ' + replies[-800:])
    return results[-1]['result'] or {}


def inspect(engine, project):
    return json.loads(engine.run('info', project, '--compact'))


def layers(document):
    result = []
    for layer in document.get('layers', []):
        result.append(layer)
        result.extend(layers({'layers': layer.get('children', [])}))
    return result


def text_fits(info, box, text, padding=0):
    # PhotoCraft omits overflowing paragraph lines. Bounds alone can describe
    # a perfectly valid *partial* caption, so also check character coverage.
    lines = info.get('lines', [])
    if not lines or max(line['end'] for line in lines) < len(text.rstrip()):
        return False
    left, top, right, bottom = info['bounds']
    x, y, width, height = box
    return (left >= x + padding - 1 and top >= y + padding - 1
            and right <= x + width - padding + 1 and bottom <= y + height - padding + 1)


def caption_box(document, placement, outline):
    width, height = document['width'], document['height']
    margin = max(4, math.ceil(min(width, height) * .045), math.ceil(outline + 2))
    box_height = max(16, math.floor(height * .30))
    y = {'top': margin, 'center': (height - box_height) // 2,
         'bottom': height - margin - box_height}[placement]
    if width <= margin * 2 or y < margin:
        raise ValueError('Image is too small for a readable caption; resize it first')
    return [margin, y, width - 2 * margin, min(box_height, height - 2 * margin)]


def apply_text(engine, project, edit, document):
    all_layers = layers(document)
    if edit.action == 'text':
        if any(layer['name'] == edit.name for layer in all_layers):
            raise ValueError('A layer already has that name; use update_text or a unique name')
        box = caption_box(document, edit.placement or 'top', edit.outline_width)
        size = edit.font_size or min(64, max(12, document['height'] * .12))
        params = {'x': box[0], 'y': box[1], 'box': box, 'name': edit.name, 'text': edit.text,
                  'font': 'Inter', 'align': edit.align or 'center', 'color': edit.color or '#ffffff',
                  'size': size * 72 / document.get('resolution', 72)}
        layer_id = command(engine, project, 'type.create', params)['layer']
        text = edit.text
    else:
        matches = [layer for layer in all_layers if layer['id'] == edit.layer or layer['name'] == edit.layer]
        if len(matches) != 1 or matches[0]['kind'] != 'Type':
            raise ValueError('Select one existing text layer by its returned ID or exact unique name')
        layer_id = matches[0]['id']
        before = command(engine, project, 'type.info', {'layer': layer_id})
        text = edit.text if edit.text is not None else before['text']
        shape = before.get('shape')
        if edit.placement is None and isinstance(shape, dict) and 'Box' in shape:
            box_shape = shape['Box']
            matrix = before['transform']
            if matrix[:4] != [1, 0, 0, 1]:
                raise ValueError('Specify placement to reset the transformed text to a fitted caption')
            box = [matrix[4] + box_shape['x'], matrix[5] + box_shape['y'], box_shape['width'], box_shape['height']]
        else:
            box = caption_box(document, edit.placement or 'top', edit.outline_width)
        size = edit.font_size or before['runs'][0]['style']['size_pt'] * before['pxPerPt']
        command(engine, project, 'type.edit', {'layer': layer_id, 'text': text, 'box': box})
    command(engine, project, 'layer.select', {'layer': layer_id})
    style = {'layer': layer_id, 'size': size * 72 / document.get('resolution', 72)}
    if edit.align is not None:
        style['align'] = edit.align
    if edit.color is not None:
        style['color'] = edit.color
    command(engine, project, 'type.setStyle', style)
    # Fit downward only. This preserves the user's requested maximum size and
    # refuses a result that would hide words, instead of claiming success.
    for _ in range(24):
        info = command(engine, project, 'type.info', {'layer': layer_id})
        # Glyph bearings can extend above/left of a paragraph box without
        # clipping the image. Character coverage catches omitted lines; the
        # canvas boundary, with outline padding, catches actual clipping.
        if text_fits(info, [0, 0, document['width'], document['height']], text, padding=edit.outline_width):
            break
        size = math.floor(size * .85)
        if size < 8:
            raise ValueError('Caption cannot fit readably; shorten it, enlarge the image, or use fewer lines')
        command(engine, project, 'type.setStyle', {'layer': layer_id, 'size': size * 72 / document.get('resolution', 72)})
    else:
        raise ValueError('Caption layout did not converge')
    if edit.action == 'text' or {'outline_color', 'outline_width'} & edit.model_fields_set:
        command(engine, project, 'layer.layerStyle.stroke', {'size': max(1, edit.outline_width),
                'position': 'outside', 'color': edit.outline_color, 'opacity': 100 if edit.outline_width else 0})
    return layer_id


def image_metadata(engine, project):
    document = inspect(engine, project)
    result = {'width': document['width'], 'height': document['height'], 'layers': []}
    for layer in layers(document):
        row = {key: layer[key] for key in ('id', 'name', 'kind', 'visible', 'bounds') if key in layer}
        if layer['kind'] == 'Type':
            info = command(engine, project, 'type.info', {'layer': layer['id']})
            row.update(text=info['text'], bounds=info['bounds'],
                       fully_visible=text_fits(info, [0, 0, document['width'], document['height']], info['text']),
                       font_size=info['runs'][0]['style']['size_pt'] * info['pxPerPt'])
        result['layers'].append(row)
    return result


def execute_image(engine, operation, inputs):
    work = engine.workspace
    project = work / 'image.pcraft'
    engine.run('convert', inputs[0], project)
    if operation.action in ('invert', 'grayscale'):
        # A global adjustment stays editable and works when the active layer
        # is text or an embedded image, unlike a pixel-only adjustment.
        command(engine, project, 'layer.newAdjustmentLayer.' + ('invert' if operation.action == 'invert' else 'hueSaturation'),
                {} if operation.action == 'invert' else {'saturation': -100})
    else:
        for edit in operation.edits:
            document = inspect(engine, project)
            if edit.action in ('text', 'update_text'):
                apply_text(engine, project, edit, document)
            elif edit.action == 'crop':
                if edit.x + edit.width > document['width'] or edit.y + edit.height > document['height']:
                    raise ValueError('Crop must be inside the source image')
                command(engine, project, 'image.crop', edit.model_dump(exclude={'action'}))
            elif edit.action == 'resize':
                command(engine, project, 'image.imageSize', edit.model_dump(exclude={'action'}))
            elif edit.action == 'rotate':
                command(engine, project, 'image.imageRotation.' + {90: '90cw', 180: '180', 270: '90ccw'}[edit.degrees], {})
            elif edit.action == 'overlay':
                if edit.x + edit.width > document['width'] or edit.y + edit.height > document['height']:
                    raise ValueError('Overlay must fit inside the canvas')
                added = command(engine, project, 'file.placeEmbedded', {'path': str(inputs[edit.source]), 'fit': False})
                layer_id = added.get('layer') or inspect(engine, project)['activeLayer']
                command(engine, project, 'edit.transform', {'layer': layer_id, 'quad': [
                        [edit.x, edit.y], [edit.x + edit.width, edit.y],
                        [edit.x + edit.width, edit.y + edit.height], [edit.x, edit.y + edit.height]]})
    metadata = image_metadata(engine, project)
    if operation.action == 'edit' and any(layer.get('fully_visible') is False for layer in metadata['layers']):
        raise ValueError('An edit would clip text; place geometry edits before captions or reposition the text')
    (work / 'document.json').write_text(json.dumps(metadata))
    engine.run('convert', project, work / 'image.png')
    return [(work / 'image.png', 'primary'), (project, 'project'), (work / 'document.json', 'inspection')]
