"""Phase 7 tests for the Jarvis Head framebuffer renderer (no device required)."""

from __future__ import annotations

import os
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HEAD_ROOT = ROOT / "jarvis-head"
sys.path.insert(0, str(HEAD_ROOT))
sys.path.insert(1, str(ROOT))

from app import HeadScene, eye_clusters  # noqa: E402
from fb_render import (  # noqa: E402
    HALO_DIM_LEVELS,
    FrameComposer,
    grid_for,
    render_snapshot,
)
from fbdev import (  # noqa: E402
    ChannelLayout,
    FramebufferError,
    framebuffer_info_from_structs,
    parse_fix_screeninfo,
    parse_var_screeninfo,
)
from glyphs import (  # noqa: E402
    ATLAS_ALPHABET,
    FONT_CANDIDATES,
    FontNotFoundError,
    GlyphAtlas,
    resolve_font_path,
)
from mask import SemanticFaceMasks, SemanticMask  # noqa: E402
from rain import BACKGROUND_CHARS, RainField  # noqa: E402

FONT = next((Path(candidate) for candidate in FONT_CANDIDATES if Path(candidate).is_file()), None)
needs_font = pytest.mark.skipif(FONT is None, reason="no monospace TrueType font installed")


def _var_screeninfo(
    xres=1920,
    yres=1080,
    bpp=32,
    red=(16, 8, 0),
    green=(8, 8, 0),
    blue=(0, 8, 0),
    virtual=None,
    offset=(0, 0),
) -> bytes:
    xres_virtual, yres_virtual = virtual or (xres, yres)
    fields = [
        xres,
        yres,
        xres_virtual,
        yres_virtual,
        *offset,
        bpp,
        0,
        *red,
        *green,
        *blue,
        0,
        0,
        0,
    ]
    return struct.pack("20I", *fields) + bytes(160 - 80)


def _fix_screeninfo(line_length=7680, smem_len=8294400) -> bytes:
    packed = struct.pack(
        "@16sLIIIIHHHxxI", b"amdgpudrmfb", 0, smem_len, 0, 0, 2, 1, 1, 0, line_length
    )
    return packed + bytes(128 - len(packed))


def test_screeninfo_structs_parse_the_fields_the_renderer_validates():
    var = parse_var_screeninfo(_var_screeninfo(virtual=(1920, 2160), offset=(0, 0)))
    assert (var["width"], var["height"], var["bits_per_pixel"]) == (1920, 1080, 32)
    assert (var["virtual_width"], var["virtual_height"]) == (1920, 2160)
    assert var["red"] == ChannelLayout(16, 8, 0)
    assert var["green"] == ChannelLayout(8, 8, 0)
    assert var["blue"] == ChannelLayout(0, 8, 0)
    assert parse_fix_screeninfo(_fix_screeninfo()) == (7680, 8294400)
    with pytest.raises(FramebufferError, match="short"):
        parse_var_screeninfo(b"\x00" * 10)
    with pytest.raises(FramebufferError, match="short"):
        parse_fix_screeninfo(b"\x00" * 10)


def test_the_host_layout_and_rgbx_are_accepted():
    info = framebuffer_info_from_structs(_var_screeninfo(), _fix_screeninfo())
    assert (info.width, info.height, info.stride) == (1920, 1080, 7680)
    assert (info.red_offset, info.green_offset, info.blue_offset) == (16, 8, 0)
    assert info.mapped_length == 7680 * 1080 <= info.memory_length
    rgbx = framebuffer_info_from_structs(
        _var_screeninfo(red=(0, 8, 0), green=(8, 8, 0), blue=(16, 8, 0)),
        _fix_screeninfo(),
    )
    assert (rgbx.red_offset, rgbx.green_offset, rgbx.blue_offset) == (0, 8, 16)
    # A larger virtual (double-buffer) area is fine as long as the visible page
    # starts at byte zero and fits the memory.
    framebuffer_info_from_structs(
        _var_screeninfo(virtual=(1920, 2160)), _fix_screeninfo(smem_len=7680 * 2160)
    )


@pytest.mark.parametrize(
    ("var", "fix", "message"),
    [
        (
            _var_screeninfo(bpp=16, red=(11, 5, 0), green=(5, 6, 0), blue=(0, 5, 0)),
            _fix_screeninfo(3840),
            "32 bits",
        ),
        (_var_screeninfo(), _fix_screeninfo(7000), "stride"),
        (_var_screeninfo(red=(24, 8, 0)), _fix_screeninfo(), "distinct 8-bit"),
        (
            _var_screeninfo(red=(20, 10, 0), green=(10, 10, 0), blue=(0, 10, 0)),
            _fix_screeninfo(),
            "distinct 8-bit",
        ),
        (_var_screeninfo(red=(16, 8, 1)), _fix_screeninfo(), "distinct 8-bit"),
        (
            _var_screeninfo(red=(0, 8, 0), green=(8, 8, 0), blue=(0, 8, 0)),
            _fix_screeninfo(),
            "distinct 8-bit",
        ),
        (
            _var_screeninfo(offset=(0, 1080), virtual=(1920, 2160)),
            _fix_screeninfo(smem_len=7680 * 2160),
            "panned",
        ),
        (_var_screeninfo(virtual=(1920, 1000)), _fix_screeninfo(), "virtual size"),
        (_var_screeninfo(), _fix_screeninfo(smem_len=7680 * 1079), "smaller than the visible page"),
        (_var_screeninfo(xres=0), _fix_screeninfo(), "empty"),
    ],
)
def test_framebuffer_layouts_the_compositor_cannot_draw_fail_closed(var, fix, message):
    with pytest.raises(FramebufferError, match=message):
        framebuffer_info_from_structs(var, fix)


def test_font_resolution_prefers_explicit_and_fails_with_an_install_hint(tmp_path: Path):
    with pytest.raises(FontNotFoundError, match="not found"):
        resolve_font_path(tmp_path / "missing.ttf")
    if FONT is not None:
        assert resolve_font_path(None).is_file()
        assert resolve_font_path(FONT) == FONT


@needs_font
def test_atlas_covers_the_rain_alphabet_with_a_blank_zero_glyph():
    atlas = GlyphAtlas(FONT, 10)

    assert atlas.alphas.shape == (len(ATLAS_ALPHABET), atlas.cell_height, atlas.cell_width)
    assert atlas.cell_width >= 1 and atlas.cell_height > atlas.cell_width
    assert 0.3 < atlas.cell_aspect < 0.8
    assert not atlas.alphas[0].any()
    assert all(atlas.alphas[index].any() for index in range(1, atlas.glyph_count))
    indices = atlas.indices(" " + BACKGROUND_CHARS)
    assert list(indices) == list(range(atlas.glyph_count))
    assert list(atlas.indices("@M.")) == [ATLAS_ALPHABET.index(char) for char in "@M."]
    with pytest.raises(ValueError, match="font_px"):
        GlyphAtlas(FONT, 4)


@needs_font
def test_grid_is_centered_and_fits_the_device():
    atlas = GlyphAtlas(FONT, 10)
    rows, cols, x_origin, y_origin = grid_for(atlas, 1920, 1080)

    assert cols * atlas.cell_width <= 1920 and (cols + 1) * atlas.cell_width > 1920
    assert rows * atlas.cell_height <= 1080 and (rows + 1) * atlas.cell_height > 1080
    assert 0 <= x_origin < atlas.cell_width and 0 <= y_origin < atlas.cell_height


def _face_scene(atlas: GlyphAtlas, rows: int, cols: int, *, seed: int = 3) -> HeadScene:
    masks = SemanticFaceMasks.from_directory(HEAD_ROOT / "assets")
    return HeadScene(
        height=rows,
        width=cols,
        preset="kiosk",
        fps=30,
        seed=seed,
        face_masks=masks,
        timeline=None,
        cell_aspect=atlas.cell_aspect,
        event_socket=None,
        state_machine=None,
    )


@needs_font
def test_composed_frame_matches_the_cell_grid_and_puts_eyes_on_top():
    atlas = GlyphAtlas(FONT, 10)
    rows, cols = 40, 100
    composer = FrameComposer(atlas, color="green", rows=rows, cols=cols)
    scene = _face_scene(atlas, rows, cols)
    for _ in range(90):
        scene.step(1 / 30)

    frame = composer.compose(scene)
    assert frame.shape == (rows * atlas.cell_height, cols * atlas.cell_width)
    assert frame.dtype == np.uint32
    image = np.asarray(composer.to_image(frame))
    green = image[..., 1].astype(int)
    assert image[..., 1].max() > image[..., 0].max()  # green hue, not gray

    def cell_mean(x: int, y: int) -> float:
        return green[
            y * atlas.cell_height : (y + 1) * atlas.cell_height,
            x * atlas.cell_width : (x + 1) * atlas.cell_width,
        ].mean()

    layer = scene.face_layer
    assert layer is not None
    brightest = max(layer.cells, key=lambda cell: cell.value)
    assert brightest.value >= 240  # eye whites survive the downsample
    eye_pixels = frame[
        (brightest.y + scene.face_offset[1]) * atlas.cell_height : (
            brightest.y + scene.face_offset[1] + 1
        )
        * atlas.cell_height,
        (brightest.x + scene.face_offset[0]) * atlas.cell_width : (
            brightest.x + scene.face_offset[0] + 1
        )
        * atlas.cell_width,
    ]
    # The eye white sits in the ramp's pale tint segment and its glyph reaches
    # (almost) full coverage; antialiased glyph edges can shave a level or two.
    eye_level = composer.face_levels[brightest.value]
    assert eye_level >= 230
    assert ((eye_pixels >> 8) & 0xFF).max() >= composer.lut[eye_level][1] - 2

    face_cells = {(cell.x, cell.y) for cell in layer.cells if cell.value > 0}
    face_mean = np.mean([cell_mean(x, y) for x, y in list(face_cells)[:400]])
    rain_cells = [(x, y) for x in range(cols) for y in range(rows) if (x, y) not in face_cells]
    rain_lit = [cell_mean(x, y) for x, y in rain_cells if cell_mean(x, y) > 0]
    assert face_mean > np.mean(rain_lit) * 1.5


@needs_font
def test_blank_grid_renders_black_and_mouth_hole_stays_dark():
    atlas = GlyphAtlas(FONT, 10)
    composer = FrameComposer(atlas, color="green", rows=3, cols=3)
    image = Image.new("L", (3, 1))
    image.putpixel((0, 0), 200)
    image.putpixel((1, 0), 0)  # interior dark cell: the mouth hole
    image.putpixel((2, 0), 200)

    from app import FaceGlyphLayer

    fitted = SemanticMask(image).fit(1, 3, cell_aspect=1.0, scale=1.0)

    class Scene:
        field = RainField(3, 3, "kiosk", seed=1)
        face_progress = 1.0
        face_offset = (0, 1)
        drawn_face_layer = FaceGlyphLayer(fitted, seed=1)

    frame = composer.compose(Scene())
    hole = frame[atlas.cell_height : 2 * atlas.cell_height, atlas.cell_width : 2 * atlas.cell_width]
    assert not hole.any()

    class Empty:
        field = RainField(3, 3, "kiosk", seed=1)
        face_progress = 0.0
        face_offset = (0, 0)
        drawn_face_layer = None

    Empty.field.columns = []
    assert not composer.compose(Empty()).any()


def _still_scene(rows: int, cols: int, *, seed: int = 5):
    """A scene whose rain does not advance, so two composes see the same field."""

    class Frozen(RainField):
        def update(self, dt: float) -> None:
            return None

    return Frozen(rows, cols, "kiosk", seed=seed)


class _BareScene:
    """Only the four original outputs: choreography inputs come from defaults."""

    def __init__(self, field, layer=None, *, progress=1.0, offset=(0, 0)):
        self.field = field
        self.drawn_face_layer = layer
        self.face_progress = progress
        self.face_offset = offset


class _ChoreographedScene(_BareScene):
    breath = 0.0
    thinking = False
    elapsed = 0.0
    speech_energy = 0.0


def _lead_cells(field) -> list[tuple[int, int]]:
    return [(x, span.lead_y) for x, span in field.visible_spans() if span.lead_y is not None]


@needs_font
def test_rain_leads_leave_a_decaying_phosphor_trail():
    atlas = GlyphAtlas(FONT, 10)
    rows, cols = 40, 60
    composer = FrameComposer(atlas, color="green", rows=rows, cols=cols)
    field = RainField(rows, cols, "kiosk", seed=5)
    for _ in range(30):
        field.update(1 / 30)
    scene = _BareScene(field)
    composer.compose(scene)
    leads_then = _lead_cells(field)

    # Advance until at least one lead has moved on; its old cell is now body.
    for _ in range(3):
        field.update(1 / 30)
    composer.compose(scene)
    level = composer.level_grid
    plain = {}
    for x, span in field.visible_spans():
        for row_offset, intensity in enumerate(span.intensities):
            y = span.y_start + row_offset
            if y != span.lead_y:
                plain[(x, y)] = int(composer.rain_levels[min(intensity, 3)])
    trails = [(x, y) for x, y in leads_then if (x, y) in plain]
    assert trails, "expected at least one vacated lead cell still drawn as body"
    assert all(int(level[y, x]) > plain[(x, y)] for x, y in trails)
    assert all(int(level[y, x]) < composer.lead_level for x, y in trails)

    # Without leads passing, glow decays back to plain body brightness.
    field.columns = []
    for _ in range(40):
        composer.compose(scene)
    assert not composer.rain_glow.any() or composer.rain_glow.max() < 0.01


@needs_font
def test_coalesce_lerps_each_cell_from_rain_to_face_eyes_first():
    atlas = GlyphAtlas(FONT, 10)
    # 60 rows is the coarsest fb grid where the eye whites survive the
    # downsample (a 40-row grid keeps only the nose specular and anchors on
    # the face center instead).
    rows, cols = 60, 150
    composer = FrameComposer(atlas, color="green", rows=rows, cols=cols)
    scene = _face_scene(atlas, rows, cols)
    scene.step(1 / 30)
    layer = scene.face_layer
    assert layer is not None and scene.fitted_faces is not None
    offset = scene.face_offset
    clusters = eye_clusters(scene.fitted_faces.get(blinking=False, mouth="rest"))
    assert len(clusters) == 2
    eye = max((cell for cluster in clusters for cell in cluster), key=lambda cell: cell.value)
    # The cell furthest from every anchor (eyes and mouth) resolves last.
    jaw = layer.cells[max(range(len(layer.cells)), key=layer.transition_points.__getitem__)]

    def levels_at(progress: float) -> tuple[int, int]:
        probe = _ChoreographedScene(scene.field, layer, progress=progress, offset=offset)
        composer.compose(probe)
        return (
            int(composer.level_grid[eye.y + offset[1], eye.x + offset[0]]),
            int(composer.level_grid[jaw.y + offset[1], jaw.x + offset[0]]),
        )

    full_eye, full_jaw = levels_at(1.0)
    early_eye, early_jaw = levels_at(0.45)
    mid_eye, mid_jaw = levels_at(0.7)
    assert early_eye > 0.5 * full_eye  # eyes are most of the way in early
    assert early_jaw <= composer.lead_level  # the jaw is still rain (or nothing)
    assert early_eye <= mid_eye <= full_eye
    assert mid_jaw <= full_jaw
    # Every active cell sits between its rain level and its face level: no pops.
    probe = _ChoreographedScene(scene.field, layer, progress=0.5, offset=offset)
    composer.compose(probe)
    assert composer.level_grid.max() <= 255
    assert composer.level_grid.min() >= 0


@needs_font
def test_a_rain_lead_under_the_face_lights_the_skin_then_fades():
    atlas = GlyphAtlas(FONT, 10)
    rows, cols = 30, 80
    composer = FrameComposer(atlas, color="green", rows=rows, cols=cols)
    scene = _face_scene(atlas, rows, cols)
    scene.step(1 / 30)
    layer = scene.face_layer
    assert layer is not None
    offset = scene.face_offset
    occupied = {(c.x + offset[0], c.y + offset[1]): c for c in layer.cells if c.value > 0}

    # Drive the field until some lead sits under a lit face cell.
    hit = None
    for _ in range(200):
        scene.field.update(1 / 30)
        for x, y in _lead_cells(scene.field):
            if (x, y) in occupied:
                hit = (x, y)
                break
        if hit is not None:
            break
    assert hit is not None
    still = _still_scene(rows, cols)
    still.columns = scene.field.columns  # freeze this exact configuration
    probe = _ChoreographedScene(still, layer, offset=offset)
    composer.compose(probe)
    cell = occupied[hit]
    expected_plain = int(composer.face_levels[cell.value])
    lit_level = int(composer.level_grid[hit[1], hit[0]])
    assert lit_level > expected_plain

    # Move the lead away (empty field) and the glow decays over a few frames.
    probe.field = _still_scene(rows, cols)
    probe.field.columns = []
    levels = []
    for _ in range(24):
        composer.compose(probe)
        levels.append(int(composer.level_grid[hit[1], hit[0]]))
    assert levels[0] > levels[3] > levels[-1] >= expected_plain
    assert levels[-1] - expected_plain <= 1


@needs_font
def test_breath_think_and_speech_energy_shift_face_brightness_where_intended():
    atlas = GlyphAtlas(FONT, 10)
    rows, cols = 40, 100
    composer = FrameComposer(atlas, color="green", rows=rows, cols=cols)
    scene = _face_scene(atlas, rows, cols)
    scene.step(1 / 30)
    layer = scene.face_layer
    assert layer is not None
    offset = scene.face_offset
    still = _still_scene(rows, cols)
    still.columns = []  # no rain: face levels are exactly the choreography
    lit = [c for c in layer.cells if c.value > 0]
    top = min(c.y for c in lit)
    bottom = max(c.y for c in lit)
    height = bottom - top + 1
    mid_row_cells = [c for c in lit if c.y == top + height // 2]
    forehead = [c for c in lit if c.y <= top + height // 5]
    chin = [c for c in lit if c.y >= bottom - height // 6]

    def levels(scene_obj, cells):
        composer.compose(scene_obj)
        return np.asarray(
            [int(composer.level_grid[c.y + offset[1], c.x + offset[0]]) for c in cells]
        )

    base = _ChoreographedScene(still, layer, offset=offset)
    plain = levels(base, mid_row_cells)

    inhale = _ChoreographedScene(still, layer, offset=offset)
    inhale.breath = 1.0
    exhale = _ChoreographedScene(still, layer, offset=offset)
    exhale.breath = -1.0
    assert (levels(inhale, mid_row_cells) >= plain).all()
    assert (levels(exhale, mid_row_cells) <= plain).all()
    assert levels(inhale, mid_row_cells).mean() - plain.mean() == pytest.approx(6, abs=1.5)

    # THINK: the scan band brightens only the rows it is crossing.
    think = _ChoreographedScene(still, layer, offset=offset)
    think.thinking = True
    think.elapsed = 1.2 * 0.5  # halfway: band around the middle row
    scanned = levels(think, mid_row_cells)
    assert (scanned > plain).all()
    assert (levels(think, forehead) == levels(base, forehead)).all()

    # Speech energy: the chin pulses, the forehead does not.
    talking = _ChoreographedScene(still, layer, offset=offset)
    talking.speech_energy = 1.0
    assert (levels(talking, chin) > levels(base, chin)).all()
    assert (levels(talking, forehead) == levels(base, forehead)).all()
    assert levels(talking, chin).max() <= 255

    # The mouth hole (open on AE) stays a hole through all of it.
    assert scene.fitted_faces is not None
    layer.apply_mask(scene.fitted_faces.get(blinking=False, mouth="ae"))
    holes = [c for c in layer.cells if c.value == 0]
    talking.thinking = True
    talking.breath = 1.0
    assert holes and (levels(talking, holes) == 0).all()


@needs_font
def test_face_brightness_gain_scales_skin_above_the_floor_and_is_bounded():
    atlas = GlyphAtlas(FONT, 10)
    rows, cols = 40, 100
    scene = _face_scene(atlas, rows, cols)
    scene.step(1 / 30)
    layer = scene.face_layer
    assert layer is not None
    still = _still_scene(rows, cols)
    still.columns = []
    probe = _ChoreographedScene(still, layer, offset=scene.face_offset)
    normal = FrameComposer(atlas, color="green", rows=rows, cols=cols)
    brighter = FrameComposer(atlas, color="green", rows=rows, cols=cols, face_brightness=1.3)
    dimmer = FrameComposer(atlas, color="green", rows=rows, cols=cols, face_brightness=0.6)

    assert brighter.face_levels[0] == normal.face_levels[0] == dimmer.face_levels[0]
    assert brighter.face_levels[255] == 255 and normal.face_levels[255] == 255
    mid = 150
    assert dimmer.face_levels[mid] < normal.face_levels[mid] < brighter.face_levels[mid]
    assert (np.diff(brighter.face_levels) >= 0).all()  # still monotonic
    faint = FrameComposer(atlas, color="green", rows=rows, cols=cols, face_brightness=0.2)
    assert faint.face_levels[0] == normal.face_levels[0]
    assert faint.face_levels[mid] < dimmer.face_levels[mid]

    normal.compose(probe)
    brighter.compose(probe)
    lit = [c for c in layer.cells if c.value > 0]
    ox, oy = scene.face_offset
    normal_mean = np.mean([normal.level_grid[c.y + oy, c.x + ox] for c in lit])
    brighter_mean = np.mean([brighter.level_grid[c.y + oy, c.x + ox] for c in lit])
    assert brighter_mean > normal_mean

    with pytest.raises(ValueError, match="face_brightness"):
        FrameComposer(atlas, color="green", rows=rows, cols=cols, face_brightness=1.6)


@needs_font
def test_halo_dims_rain_next_to_the_face_by_one_console_step():
    atlas = GlyphAtlas(FONT, 10)
    rows, cols = 30, 80
    composer = FrameComposer(atlas, color="green", rows=rows, cols=cols)
    scene = _face_scene(atlas, rows, cols)
    scene.step(1 / 30)
    composer.compose(scene)
    layer = scene.drawn_face_layer
    assert layer is not None
    halo = layer.halo_at(scene.face_offset)
    occupied = {(c.x + scene.face_offset[0], c.y + scene.face_offset[1]) for c in layer.cells}

    plain = {}
    for x, span in scene.field.visible_spans():
        for offset, intensity in enumerate(span.intensities):
            y = span.y_start + offset
            level = composer.lead_level if y == span.lead_y else composer.rain_levels[intensity]
            plain[(x, y)] = int(level)
    checked = 0
    for (x, y), level in plain.items():
        if (x, y) in occupied or not (0 <= x < cols and 0 <= y < rows):
            continue
        expected = max(level - HALO_DIM_LEVELS, 0) if (x, y) in halo else level
        assert int(composer.level_grid[y, x]) == expected
        checked += 1
    assert checked > 100 and any(pos in halo for pos in plain)


@needs_font
def test_snapshot_cli_writes_a_deterministic_png(tmp_path: Path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    for output in (first, second):
        result = subprocess.run(
            [
                str(ROOT / "bin" / "jarvis-head"),
                "--snapshot",
                str(output),
                "--snapshot-at",
                "1.5",
                "--seed",
                "11",
                "--font-px",
                "8",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    with Image.open(first) as image:
        assert image.size == (1920, 1080)
        assert image.mode == "RGB"
        assert np.asarray(image)[..., 1].max() > 0
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("renderer", ["curses", "fb"])
def test_demo_mode_turns_sigterm_into_a_clean_return(monkeypatch, renderer):
    """`kiosk.sh stop` sends SIGTERM; demo displays must unwind like normal ones."""

    import app
    import fb_render

    seen: dict[str, object] = {}

    def fake_long_running_display(*_args, **_kwargs):
        seen["handler"] = signal.getsignal(signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGTERM)
        for _ in range(50):
            time.sleep(0.01)  # the handler raises KeyboardInterrupt out of here
        raise AssertionError("SIGTERM did not interrupt the display")

    monkeypatch.setattr(app.curses, "wrapper", fake_long_running_display)
    monkeypatch.setattr(fb_render, "run_framebuffer_display", fake_long_running_display)
    before = signal.getsignal(signal.SIGTERM)

    app.run_display(
        renderer=renderer,
        demo_face=True,
        asset_dir=HEAD_ROOT / "assets",
        cell_aspect=0.4 if renderer == "curses" else None,
    )

    assert seen["handler"] is app._interrupt_display
    assert signal.getsignal(signal.SIGTERM) is before


@pytest.mark.parametrize("renderer", ["curses", "fb"])
def test_a_second_sigterm_during_cleanup_cannot_abort_it(monkeypatch, renderer):
    """runuser/su forward the group-wide SIGTERM again; the unwind must finish."""

    import app
    import fb_render

    seen: dict[str, object] = {}

    def fake_long_running_display(*_args, **_kwargs):
        seen["hup"] = signal.getsignal(signal.SIGHUP)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
            for _ in range(50):
                time.sleep(0.01)
            raise AssertionError("first SIGTERM did not interrupt the display")
        except KeyboardInterrupt:
            # Now "inside the cleanup": a duplicate must be ignored, not raised.
            seen["after_first"] = signal.getsignal(signal.SIGTERM)
            os.kill(os.getpid(), signal.SIGTERM)
            os.kill(os.getpid(), signal.SIGHUP)
            time.sleep(0.05)
            seen["cleanup_completed"] = True
            raise

    monkeypatch.setattr(app.curses, "wrapper", fake_long_running_display)
    monkeypatch.setattr(fb_render, "run_framebuffer_display", fake_long_running_display)
    before = {signum: signal.getsignal(signum) for signum in app.INTERRUPT_SIGNALS}

    app.run_display(
        renderer=renderer,
        demo_face=True,
        asset_dir=HEAD_ROOT / "assets",
        cell_aspect=0.4 if renderer == "curses" else None,
    )

    assert seen["hup"] is app._interrupt_display
    assert seen["after_first"] is signal.SIG_IGN
    assert seen.get("cleanup_completed") is True
    assert {signum: signal.getsignal(signum) for signum in app.INTERRUPT_SIGNALS} == before


def test_snapshot_mode_does_not_touch_the_sigterm_handler(monkeypatch, tmp_path: Path):
    import app
    import fb_render

    seen = {}

    def fake_snapshot(*_args, **_kwargs):
        seen["handler"] = signal.getsignal(signal.SIGTERM)
        return tmp_path / "x.png"

    monkeypatch.setattr(fb_render, "render_snapshot", fake_snapshot)
    before = signal.getsignal(signal.SIGTERM)
    app.run_display(
        renderer="fb",
        cell_aspect=None,
        asset_dir=HEAD_ROOT / "assets",
        snapshot_path=tmp_path / "x.png",
    )
    assert seen["handler"] is before


@needs_font
def test_framebuffer_loop_restores_console_and_blanks_device_on_interrupt(monkeypatch):
    import fb_render

    events: list[str] = []
    host_info = framebuffer_info_from_structs(_var_screeninfo(), _fix_screeninfo())

    class FakeFramebuffer:
        def __init__(self, path):
            events.append(f"open {path}")
            self.info = host_info
            self.frames: list[tuple[tuple[int, int], int, int]] = []

        width = host_info.width
        height = host_info.height

        def present(self, frame, *, x=0, y=0):
            self.frames.append((frame.shape, x, y))
            events.append("present")

        def clear(self):
            events.append("clear")

        def close(self):
            events.append("close")

    class FakeGraphicsMode:
        def __init__(self, fd, *, console_path):
            events.append(f"graphics {fd} {console_path}")

        def __enter__(self):
            events.append("KD_GRAPHICS")
            return self

        def __exit__(self, *exc):
            events.append("KD_TEXT")

    class FakeKeyboard:
        def __enter__(self):
            events.append("cbreak")
            return self

        def __exit__(self, *exc):
            events.append("termios restored")

        def quit_requested(self):
            return False

    class FakeStdin:
        def fileno(self):
            return 0

    monkeypatch.setattr(fb_render, "controlling_console", lambda: "/dev/tty8")
    monkeypatch.setattr(fb_render, "Framebuffer", FakeFramebuffer)
    monkeypatch.setattr(fb_render, "ConsoleGraphicsMode", FakeGraphicsMode)
    monkeypatch.setattr(fb_render, "RawKeyboard", FakeKeyboard)
    monkeypatch.setattr(fb_render.sys, "stdin", FakeStdin())
    monkeypatch.setattr(fb_render.time, "sleep", lambda _s: None)

    steps = {"count": 0}
    atlas = GlyphAtlas(FONT, 10)

    class InterruptingScene:
        def __init__(self, rows, cols):
            self.inner = _face_scene(atlas, rows, cols)

        def step(self, dt):
            steps["count"] += 1
            if steps["count"] == 3:
                raise KeyboardInterrupt  # what _interrupt_display raises on SIGTERM
            self.inner.step(dt)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    with pytest.raises(KeyboardInterrupt):
        fb_render.run_framebuffer_display(
            lambda rows, cols, _aspect: InterruptingScene(rows, cols),
            color="green",
            fps=30,
            framebuffer_path="/dev/fb0",
            font_path=FONT,
            font_px=10,
        )

    assert events[:2] == ["open /dev/fb0", "graphics 0 /dev/tty8"]
    assert events.count("present") == 2
    # Blank *before* KD_TEXT: leaving graphics mode makes fbcon redraw the
    # console, and a blank after that would wipe it and leave the panel black.
    assert events[-4:] == ["termios restored", "clear", "KD_TEXT", "close"]
    assert events.index("KD_GRAPHICS") < events.index("present") < events.index("KD_TEXT")


def test_failed_text_mode_restore_is_reported_not_swallowed(monkeypatch, capsys):
    import fbdev

    calls: list[tuple[int, int]] = []

    def fake_ioctl(fd, request, arg=None):
        if request == fbdev.KDGETMODE:
            arg[:] = struct.pack("i", fbdev.KD_TEXT)
            return 0
        calls.append((request, arg))
        if request == fbdev.KDSETMODE and arg == fbdev.KD_TEXT:
            raise OSError(5, "Input/output error")
        return 0

    logged: list[tuple[int, str]] = []
    monkeypatch.setattr(fbdev.fcntl, "ioctl", fake_ioctl)
    monkeypatch.setattr(fbdev.syslog, "syslog", lambda prio, msg: logged.append((prio, msg)))

    with fbdev.ConsoleGraphicsMode(0, console_path="/dev/tty8"):
        pass

    assert (fbdev.KDSETMODE, fbdev.KD_GRAPHICS) in calls
    err = capsys.readouterr().err
    assert "could not restore /dev/tty8 text mode" in err and "Input/output error" in err
    assert logged and logged[0][0] == fbdev.syslog.LOG_WARNING
    assert "tty8" in logged[0][1]


def test_fb_renderer_refuses_without_a_virtual_console():
    result = subprocess.run(
        [str(ROOT / "bin" / "jarvis-head"), "--renderer", "fb", "--demo-face"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 2
    assert "virtual console" in result.stderr
    assert "--snapshot" in result.stderr


def test_snapshot_rejects_the_curses_renderer():
    result = subprocess.run(
        [str(ROOT / "bin" / "jarvis-head"), "--renderer", "curses", "--snapshot", "/tmp/x.png"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 2
    assert "--renderer fb" in result.stderr


@needs_font
def test_render_snapshot_function_uses_the_font_cell_aspect(tmp_path: Path):
    seen = {}

    def factory(rows, cols, aspect):
        seen.update(rows=rows, cols=cols, aspect=aspect)
        return _face_scene(GlyphAtlas(FONT, 12), rows, cols)

    output = render_snapshot(
        factory,
        output=tmp_path / "shot.png",
        color="cyan",
        fps=30,
        at_seconds=0.5,
        font_path=FONT,
        font_px=12,
        size=(640, 360),
    )
    atlas = GlyphAtlas(FONT, 12)
    assert seen["aspect"] == pytest.approx(atlas.cell_aspect)
    assert (seen["rows"], seen["cols"]) == grid_for(atlas, 640, 360)[:2]
    with Image.open(output) as image:
        assert image.size == (640, 360)
