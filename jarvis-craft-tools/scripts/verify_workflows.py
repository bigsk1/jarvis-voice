#!/usr/bin/env python3
"""Real gateway edits with independent pixel/PDF/video checks; run in Jarvis venv."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))
from config_loader import config_scope  # noqa: E402
from configure_jarvis import read_settings  # noqa: E402
from craft_tools import execute_tool  # noqa: E402
from stash_helper import StashFile, open_space  # noqa: E402


def main():
    import fitz
    from PIL import Image, ImageChops, ImageStat
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--api-url')
    parser.add_argument('--ca-bundle',type=Path)
    args=parser.parse_args()
    output=args.output_dir.expanduser().resolve()
    output.mkdir(parents=True,exist_ok=True)
    settings=read_settings(args.settings.expanduser())
    if args.api_url:
        settings['CRAFT_API_URL']=args.api_url
    if args.ca_bundle:
        settings['CRAFT_CA_BUNDLE']=str(args.ca_bundle)
    settings['STASH_DIR']=str(output/'stash')
    results={}
    with config_scope('cloud',settings):
        source=Image.new('RGB',(160,90),(60,80,100))
        source.save(output/'source.png')
        pdf=fitz.open()
        for index in range(2):
            page=pdf.new_page(width=160,height=90)
            page.insert_text((10,40),f'Craft page {index+1}')
        pdf.save(output/'source.pdf')
        pdf.close()
        space,_=open_space(scope='project',labels=['craft_validation'])
        refs={name:StashFile(space).save_binary((output/name).read_bytes(),name)['ref'] for name in ('source.png','source.pdf')}
        def run(name,parameters):
            result=execute_tool(name,parameters)
            if not result['ok'] or result['data'].get('state')!='succeeded':
                raise RuntimeError(json.dumps(result))
            results[name+':'+parameters['action']]=result['data']
            print(name,parameters['action'],'completed',flush=True)
            return result['data']
        inverted=run('craft_image',{'action':'invert','sources':[refs['source.png']]})
        inverse=Image.open(inverted['file_path']).convert('RGB')
        assert max(ImageStat.Stat(ImageChops.difference(inverse,ImageChops.invert(source))).mean)<2
        project=next(item for item in inverted['outputs'] if item['role']=='project')
        gray=run('craft_image',{'action':'grayscale','project_id':inverted['project_id'],'sources':[project['craft_ref']]})
        assert gray['project_revision']==2
        r,g,b=Image.open(gray['file_path']).convert('RGB').split()
        assert ImageChops.difference(r,g).getbbox() is None and ImageChops.difference(g,b).getbbox() is None
        rotated=run('craft_pdf',{'action':'rotate','sources':[refs['source.pdf']],'degrees':90,'pages':[1]})
        with fitz.open(rotated['file_path']) as doc:
            assert doc[0].rotation==90 and len(doc)==2
        extracted=run('craft_pdf',{'action':'extract','sources':[refs['source.pdf']],'pages':[2]})
        with fitz.open(extracted['file_path']) as doc:
            assert len(doc)==1 and 'Craft page 2' in doc[0].get_text()
        combined=run('craft_pdf',{'action':'combine','sources':[refs['source.pdf'],refs['source.pdf']]})
        with fitz.open(combined['file_path']) as doc:
            assert len(doc)==4
        page=run('craft_pdf',{'action':'render','sources':[refs['source.pdf']],'pages':[1]})
        Image.open(page['file_path']).verify()
        photo=run('craft_photos',{'action':'develop','sources':[refs['source.png']],'exposure':0.6})
        developed=Image.open(photo['file_path']).convert('RGB')
        assert developed.size==source.size and ImageStat.Stat(developed).mean[0]>60
        motion=run('craft_motion',{'action':'title','text':'Craft gateway proof','width':160,'height':90,
                                  'fps':12,'duration':1,'font_size':18,'output':'mp4','gpu':True})
        video=run('craft_video',{'action':'assemble','sources':[motion['stash_ref']],'width':160,'height':90,
                                'fps':12,'duration':1,'output':'mp4'})
        for result in (motion,video):
            path=result['file_path']
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',path]))
            assert probe['streams'][0]['width']==160 and probe['streams'][0]['height']==90
            assert .9<=float(probe['format']['duration'])<=1.2
            subprocess.run(['ffmpeg','-v','error','-xerror','-i',path,'-f','null','-'],check=True,capture_output=True,timeout=30)
    (output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Verified all five adapters and saved projects. Results:',output/'results.json')

if __name__ == '__main__':
    main()
