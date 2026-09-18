"""Run inspect/render/verify without modifying the input telemetry."""
import argparse, collections, concurrent.futures, json, math, os, re, shutil, struct, subprocess, time
from pathlib import Path
import numpy as np
from PIL import Image
from telemetry import config, prepare
from hud import make_renderer

def render_indices(frame_count,output_fps,render_fps):
    if output_fps%render_fps:
        raise ValueError('fps must be an integer multiple of render_fps')
    return range(0,frame_count,output_fps//render_fps)

def ordered_parallel_map(fn,values,workers,prefetch=2):
    if workers<=1:
        yield from map(fn,values);return
    values=iter(values);limit=max(workers,workers*prefetch)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers,thread_name_prefix='hud') as pool:
        pending=collections.deque()
        for _ in range(limit):
            try: pending.append(pool.submit(fn,next(values)))
            except StopIteration: break
        while pending:
            yield pending.popleft().result()
            try: pending.append(pool.submit(fn,next(values)))
            except StopIteration: pass

def verification_samples(report):
    padding=report.get('padding') or {};head=float(padding.get('head_seconds',0));tail=float(padding.get('tail_seconds',0))
    if head or tail:
        content=float(report.get('content_duration',report['duration']-head-tail))
        samples=[]
        if head: samples.append((head/2,False))
        samples.append((head+content/2,False))
        if tail: samples.append((head+content+tail/2,False))
        return samples
    return [(t,False) for t in sorted(set([0,report['duration']/2,max(0,report['duration']-1/report['fps'])]))]

def alpha_codec_args(codec):
    if codec=='prores4444':
        return ['-c:v','prores','-profile:v','4','-pix_fmt','yuva444p10le']
    if codec=='qtrle':
        return ['-c:v','qtrle','-pix_fmt','argb']
    raise ValueError('alpha_codec must be prores4444 or qtrle')

def ffmpeg_path():
    candidate=os.environ.get('IMAGEIO_FFMPEG_EXE') or shutil.which('ffmpeg')
    if candidate: return candidate
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError,AttributeError) as e:
        raise RuntimeError('Install scripts/requirements.txt or provide IMAGEIO_FFMPEG_EXE') from e
def dump(path,obj): Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def encode(ff,frames,path,c,alpha,comment='',input_fps=None,output_fps=None,output_frames=None):
    input_fps=input_fps or c['fps'];output_fps=output_fps or input_fps
    args=[ff,'-y','-hide_banner','-loglevel','error','-f','rawvideo','-pixel_format','rgba' if alpha else 'rgb24',
        '-video_size',f"{c['width']}x{c['height']}",'-framerate',str(input_fps),'-i','pipe:0','-an']
    if output_fps!=input_fps: args+=['-vf',f'fps={output_fps}']
    if output_frames is not None: args+=['-frames:v',str(output_frames)]
    args+=alpha_codec_args(c.get('alpha_codec','qtrle')) if alpha else ['-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart']
    if comment: args+=['-metadata','comment='+comment]
    args+=[str(path)]
    with path.with_suffix('.log').open('w',encoding='utf-8') as log:
        p=subprocess.Popen(args,stdin=subprocess.PIPE,stderr=log)
        try:
            for frame in frames:
                data = frame if isinstance(frame, (bytes, bytearray)) else frame.tobytes()
                p.stdin.write(data)
            p.stdin.close()
            if p.wait()!=0: raise RuntimeError('Encoding failed; read '+str(path.with_suffix('.log')))
        except BaseException:
            p.kill();p.wait();raise
def verify(path,report=None):
    path=Path(path);ff=ffmpeg_path()
    meta=subprocess.run([ff,'-hide_banner','-i',str(path)],capture_output=True,text=True,encoding='utf-8',errors='replace').stderr
    codec=(report or {}).get('alpha_codec')
    is_qtrle='qtrle' in meta and 'argb' in meta
    is_prores='prores' in meta and re.search(r'yuva444p\d+le',meta)
    if codec=='qtrle' and not is_qtrle: raise ValueError('Not a QTRLE ARGB transparent MOV')
    if codec=='prores4444' and not is_prores: raise ValueError('Not a ProRes 4444 alpha MOV')
    if codec is None and not (is_qtrle or is_prores): raise ValueError('Not a supported transparent MOV')
    counts=[]
    def atoms(f,end):
        while f.tell()+8<=end:
            pos=f.tell();size,kind=struct.unpack('>I4s',f.read(8));header=8
            if size==1: size=struct.unpack('>Q',f.read(8))[0];header=16
            if size==0: size=end-pos
            if size<header or pos+size>end: raise ValueError('Invalid MOV atom')
            if kind in [b'moov',b'trak',b'mdia',b'minf',b'stbl']: atoms(f,pos+size)
            elif kind==b'stsz': f.read(8);counts.append(struct.unpack('>I',f.read(4))[0])
            f.seek(pos+size)
    with path.open('rb') as f: atoms(f,path.stat().st_size)
    if report:
        if counts!=[report['frames']]: raise ValueError('Frame count mismatch')
        w,h=report['size']
        if f'{w}x{h}' not in meta: raise ValueError('Resolution mismatch')
        match=re.search(r'(\d+(?:\.\d+)?) fps',meta)
        if not match or abs(float(match[1])-report['fps'])>0.01: raise ValueError('Frame rate mismatch')
        checks=[]
        for t,expected_blank in verification_samples(report):
            result=subprocess.run([ff,'-v','error','-ss',str(t),'-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgba','pipe:1'],capture_output=True,check=True)
            a=np.frombuffer(result.stdout,np.uint8).reshape(h,w,4)
            max_alpha=int(a[:,:,3].max())
            if expected_blank:
                if max_alpha!=0: raise ValueError('Padding frame is not fully transparent')
            elif a[h//2,w//2,3]!=0 or max_alpha!=255:
                raise ValueError('Invalid transparent overlay pixels')
            checks.append({'seconds':t,'expected_blank':expected_blank,
                'center_alpha':int(a[h//2,w//2,3]),'max_alpha':max_alpha})
    else: checks=[]
    return {'passed':True,'frames':counts,'bytes':path.stat().st_size,'samples':checks,'metadata':meta}
def render(args):
    c=config(args.config);data,ts,report=prepare(args.csv,c,args.start,args.duration)
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    final=out/'dashboard_100fps_alpha.mov' if c['fps']==100 else out/'dashboard_alpha.mov'
    if final.exists(): raise FileExistsError('Choose a fresh output directory; existing finished video is preserved')
    dump(out/'resolved-config.json',c);dump(out/'report.json',report)
    draw=make_renderer(data,ts,c,info=report['meta'])
    speed=data['VehSpd'];idx=int(np.nanargmax(speed)) if np.any(np.isfinite(speed)) else 0
    shot=draw(idx);shot.save(out/'transparent.png')
    def background(im):
        bg=Image.new('RGBA',im.size,(80,89,98,255));bg.alpha_composite(im);return bg.convert('RGB')
    background(shot).save(out/'preview.jpg')
    ff=ffmpeg_path();preview_cfg=dict(c,fps=25)
    # Sample source frames at wall-clock intervals so the preview retains correct playback speed.
    begin=max(0,idx/c['fps']-4);end=min(len(ts)/c['fps'],begin+8)
    indices=np.minimum((np.arange(begin,end,1/25)*c['fps']).astype(int),len(ts)-1)
    encode(ff,(background(draw(int(i))) for i in indices),out/'preview.mp4',preview_cfg,False)
    if args.preview_only:
        print('PREVIEW '+str(out),flush=True);return
    started=time.time();indices=list(render_indices(len(ts),c['fps'],c['render_fps']))
    temporary=out/'dashboard.partial.mov'
    workers=c.get('render_workers',8)
    def on_prog(d):
        dump(out/'progress.json',{
            'rendered_frames':d['current'],'render_total':d['total'],'output_frames':d['output_frames'],
            'elapsed':round(d['elapsed']),'complete':False})
    from render_mp import render_chunks_parallel
    render_chunks_parallel(data,ts,c,report['meta'],indices,temporary,workers=workers,progress_callback=on_prog)
    verified=verify(temporary,report)
    temporary.replace(final);dump(out/'verification.json',verified)
    dump(out/'progress.json',{'rendered_frames':len(indices),'render_total':len(indices),
        'output_frames':len(ts),'elapsed':round(time.time()-started),'complete':True})
    (out/'使用说明.txt').write_text(f"透明视频：{final.name}\n{c['width']}×{c['height']} / {c['fps']} fps / {report['duration']:.3f} 秒\n"
        f"文件头部有 {report['padding']['head_seconds']:.3f} 秒空数据 HUD，尾部有 {report['padding']['tail_seconds']:.3f} 秒空数据 HUD（UI 保留、数值为 --、柱条为空）；数据内容时长 {report['content_duration']:.3f} 秒。\n"
        f"放在录像上方轨道。文件第 0 帧应放在录像时间轴 {report['alignment']['output_start']:.3f} 秒。\n"
        "灰底 preview.mp4 仅用于预览。report.json 记录映射、同步公式与缺失通道。\n"
        "零偏移不表示已经和录像同步；未提供同步点时保留数据原始秒数。\n"
        "界面：左上 SCUT Racing 白色 logo，右上计时条（时间为主，车辆/车手辅助），底部通栏信息带从左到右为 "
        "GPS 迷你轨迹（红点定位）、电池（SOC/电压/功率/电流）、转向圆环（左正右负 ±160°）、速度与刻度条、"
        "四轮扭矩（柱+数字，无数据为空框 --）、踏板（BRK/THR，刹车为本次记录相对百分比）、G 力（X 上 Y 左，反向惯性）。"
        "扭矩柱表示扭矩绝对值，功率为启用电机的机械功率总和。布局可用 config 的 layout.widgets 调整。\n",encoding='utf-8')
    print('COMPLETE '+str(final),flush=True)
def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    for name in ['inspect','render']:
        a=sub.add_parser(name);a.add_argument('csv');a.add_argument('--config');a.add_argument('--start',type=float);a.add_argument('--duration',type=float)
        if name=='inspect': a.add_argument('--output',help='JSON report path')
        else: a.add_argument('--output',required=True);a.add_argument('--preview-only',action='store_true')
    a=sub.add_parser('verify');a.add_argument('video');a.add_argument('--report')
    a=sub.add_parser('init-config');a.add_argument('output')
    args=p.parse_args()
    if args.command=='init-config': dump(args.output,config())
    elif args.command=='inspect':
        _,_,report=prepare(args.csv,config(args.config),args.start,args.duration)
        if args.output: dump(args.output,report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    elif args.command=='verify':
        report=json.loads(Path(args.report).read_text(encoding='utf-8')) if args.report else None
        print(json.dumps(verify(args.video,report),ensure_ascii=False,indent=2))
    else: render(args)
if __name__=='__main__': main()
