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
            (output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
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
        meme=run('craft_image',{'action':'edit','sources':[refs['source.png']],
                              'edits':[{'action':'text','name':'Caption','text':'Craft meme','placement':'top','font_size':18}]})
        assert meme['document']['layers'][0]['text']=='Craft meme' and meme['document']['layers'][0]['fully_visible']
        revised=run('craft_image',{'action':'edit','sources':[meme['editable_project_ref']],
                    'project_revision':meme['project_revision'],
                    'edits':[{'action':'update_text','layer':'Caption','text':'Changed words','placement':'bottom'}]})
        assert revised['project_id']==meme['project_id'] and revised['project_revision']==2
        assert revised['document']['layers'][0]['id']==meme['document']['layers'][0]['id']
        results['craft_image:revision']=revised
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
        clip=output/'source.mp4'
        subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=12:duration=4',
                        '-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-pix_fmt','yuv420p',
                        '-c:a','aac','-shortest',str(clip)],check=True,capture_output=True,timeout=30)
        clip_ref=StashFile(space).save_binary(clip.read_bytes(),'source.mp4',mime_type='video/mp4')['ref']
        cut=run('craft_video',{'action':'edit','sources':[clip_ref], 'clips':[{'source':0,'start':1,'end':3}],
                'video_edits':[{'action':'title','text':'Text on footage'},
                               {'action':'caption','text':'Supplied caption','start':.5,'duration':1}], 'output':'mp4'})
        assert cut['document']['duration']==2 and len(cut['document']['overlays'])==2
        overlay_ids={item['clip'] for item in cut['document']['overlays']}
        base=next(item for item in cut['document']['clips'] if item['track']=='video' and item['id'] not in overlay_ids)
        assert base['source_start']==1 and base['source_end']==3
        overlay=cut['document']['overlays'][0]
        revision=run('craft_video',{'action':'edit','sources':[cut['editable_project_ref']],
                  'project_revision':cut['project_revision'], 'video_edits':[{'action':'update_text',
                   'clip':overlay['clip'],'layer':overlay['layer'],'text':'Revised overlay'}], 'output':'mp4'})
        assert revision['project_id']==cut['project_id'] and revision['project_revision']==2
        assert revision['document']['clips']==cut['document']['clips']
        assert revision['document']['overlays'][0]['clip']==overlay['clip']
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',revision['file_path']]))
        assert any(stream['codec_type']=='audio' for stream in info['streams'])
        assert 1.9<=float(info['format']['duration'])<=2.2
        results['craft_video:revision']=revision
        # Move a later-starting caption without repeating its words. Schema
        # copied document timing must not reset it, including on a resized frame.
        caption=revision['document']['overlays'][1]
        resized=run('craft_video',{'action':'edit','editable_project_ref':revision['editable_project_ref'],
                    'project_revision':revision['project_revision'],'width':160,
                    'video_edits':[{'action':'update_text','clip':caption['clip'],'layer':caption['layer'],
                                    'placement':'bottom','start':caption['start'],
                                    'duration':caption['duration']}], 'output':'mp4'})
        assert resized['document']['clips']==revision['document']['clips']
        assert (resized['document']['width'],resized['document']['height'])==(160,90)
        actual=resized['document']['overlays'][1]
        assert all(actual[key]==caption[key] for key in ('clip','layer','text','start','duration'))
        resized_probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',resized['file_path']]))
        assert any(stream['codec_type']=='audio' for stream in resized_probe['streams'])
        assert next(stream for stream in resized_probe['streams'] if stream['codec_type']=='video')['width']==160
        results['craft_video:resized']=resized
    (output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Verified all five adapters and saved projects. Results:',output/'results.json')

if __name__ == '__main__':
    main()
