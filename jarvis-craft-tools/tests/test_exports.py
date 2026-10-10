"""Real video decode checks and useful, bounded native failure diagnostics."""
import shutil
import subprocess
import sys
import zipfile

import pytest
from craft_gateway.engine import Engine, validate_exports


def engine(tmp_path):
    return Engine('/bin/true',tmp_path,lambda:False,lambda pid:None,timeout=30)


def test_truncated_mp4_is_rejected_and_diagnostic_is_retained(tmp_path):
    path=tmp_path/'truncated.mp4'
    path.write_bytes(b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2')
    with pytest.raises(RuntimeError,match='Native engine failed') as error:
        validate_exports(engine(tmp_path),[(path,'primary')])
    assert 'no diagnostic supplied' not in str(error.value)
    assert (tmp_path/'engine-error.log').stat().st_size>0


def test_real_mp4_passes_stream_and_full_decode_validation(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg gateway prerequisite not present')
    path=tmp_path/'tiny.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=32x32:r=4:d=0.5',
                    '-c:v','libx264','-pix_fmt','yuv420p',str(path)],check=True,timeout=20)
    validate_exports(engine(tmp_path),[(path,'primary')])


def test_bad_and_incomplete_project_archives_fail(tmp_path):
    path=tmp_path/'project.zip'
    path.write_bytes(b'not a zip')
    with pytest.raises(RuntimeError,match='Invalid project archive'):
        validate_exports(engine(tmp_path),[(path,'project')])
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('README.txt','missing native project')
    with pytest.raises(RuntimeError,match='Invalid project archive'):
        validate_exports(engine(tmp_path),[(path,'project')])


def test_native_stderr_is_bounded_and_reported(tmp_path):
    runner=Engine(sys.executable,tmp_path,lambda:False,lambda pid:None)
    with pytest.raises(RuntimeError,match='missing alpha feature') as error:
        runner.run('-c','import sys;sys.stderr.write("x"*10000+"missing alpha feature");sys.exit(2)')
    assert len(str(error.value))<1000 and runner.process is None


def test_mcp_error_text_is_reported(tmp_path):
    runner=Engine(sys.executable,tmp_path,lambda:False,lambda pid:None)
    runner.start(['-c', 'import sys,json; r=json.loads(sys.stdin.readline()); print(json.dumps({"id":r["id"],"error":{"message":"unsupported property"}}),flush=True)'],subprocess.PIPE)
    try:
        with pytest.raises(RuntimeError,match='unsupported property'):
            runner.rpc({'jsonrpc':'2.0','id':1,'method':'fixture'})
    finally:
        runner.stop()
