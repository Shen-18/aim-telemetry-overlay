"""高并发分段并行渲染引擎 (Chunk-based Parallel Pipeline)
每个工作进程独立持有本地 FFmpeg 编码器，直写分段 MOV，0 内存管道开销，
最后通过 FFmpeg -c copy 瞬间无损拼接，跑满多核 CPU，彻底根除 [Errno 22]。
"""
import sys, os, time, subprocess, shutil, math
from pathlib import Path
import multiprocessing as mp

# ffmpeg 是控制台程序；pythonw 启动 GUI 时父进程无控制台，
# 子进程会被系统新开可见控制台窗口（黑框），必须显式禁止（仅 Windows 有效）
NO_WINDOW = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}

def _worker_render_chunk(chunk_id, indices, data, ts, cfg, info, out_mov_str, progress_queue, out_frames):
    from hud import make_renderer
    from dashboard import ffmpeg_path, alpha_codec_args
    
    ff = ffmpeg_path()
    draw = make_renderer(data, ts, cfg, info)
    w, h = cfg['width'], cfg['height']
    rfps = cfg['render_fps']
    ofps = cfg['fps']
    codec = cfg.get('alpha_codec', 'qtrle')
    
    out_path = Path(out_mov_str)
    log_path = out_path.with_suffix('.log')
    
    args = [
        ff, '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'rawvideo', '-pixel_format', 'rgba',
        '-video_size', f'{w}x{h}',
        '-framerate', str(rfps),
        '-i', 'pipe:0',
        '-vf', f'fps={ofps}',
        '-frames:v', str(out_frames),
    ] + alpha_codec_args(codec) + [
        str(out_path)
    ]
    
    with open(log_path, 'w', encoding='utf-8') as log_file:
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=log_file, **NO_WINDOW)
        try:
            batch = 0
            for idx in indices:
                im = draw(idx)
                p.stdin.write(im.tobytes())
                batch += 1
                if batch % 15 == 0:
                    progress_queue.put(batch)
                    batch = 0
            if batch > 0:
                progress_queue.put(batch)
            p.stdin.close()
            ret = p.wait()
            if ret != 0:
                raise RuntimeError(f"FFmpeg chunk {chunk_id} failed with exit code {ret}")
        except Exception as e:
            p.kill()
            p.wait()
            raise e

def render_chunks_parallel(data, ts, cfg, info, indices, out_mov_path, workers=8, progress_callback=None, cancel_check=None):
    """
    分段并行渲染主函数：
    1. 将 indices 均分成 workers 个分段
    2. 启动 workers 个独立进程，每个直写一个局部 MOV
    3. 实时收集各进程进度并回调
    4. 无损快速 concat 拼接
    """
    out_mov_path = Path(out_mov_path).resolve()
    temp_dir = out_mov_path.parent / f"_tmp_chunks_{os.getpid()}_{int(time.time()*1000)}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    total_render_frames = len(indices)
    num_workers = max(1, min(workers, total_render_frames))
    
    chunk_size = (total_render_frames + num_workers - 1) // num_workers
    chunks = []
    chunk_files = []
    
    for i in range(num_workers):
        start_idx = i * chunk_size
        end_idx = min(start_idx + chunk_size, total_render_frames)
        if start_idx < end_idx:
            chunks.append(indices[start_idx:end_idx])
            chunk_files.append(temp_dir / f"chunk_{i:03d}.mov")
            
    ofps = cfg['fps']
    rfps = cfg['render_fps']
    multiplier = ofps // rfps
    allocated_frames = 0
    chunk_out_frames = []
    for i, c_indices in enumerate(chunks):
        if i < len(chunks) - 1:
            cnt = len(c_indices) * multiplier
        else:
            cnt = len(ts) - allocated_frames
        allocated_frames += cnt
        chunk_out_frames.append(cnt)

    ctx = mp.get_context('spawn')
    q = ctx.Queue()
    procs = []
    
    for i, (c_indices, c_file, c_out_f) in enumerate(zip(chunks, chunk_files, chunk_out_frames)):
        p = ctx.Process(
            target=_worker_render_chunk,
            args=(i, c_indices, data, ts, cfg, info, str(c_file), q, c_out_f)
        )
        p.start()
        procs.append(p)
        
    started = time.time()
    rendered_count = 0
    last_update = 0
    
    try:
        while rendered_count < total_render_frames:
            if cancel_check and cancel_check():
                raise RuntimeError("用户终止了渲染任务")
                
            try:
                # 阻塞读取进度更新，超时 0.5 秒
                delta = q.get(timeout=0.5)
                rendered_count += delta
            except:
                # 检查子进程是否发生意外退出
                for p in procs:
                    if not p.is_alive() and p.exitcode not in (0, None):
                        raise RuntimeError(f"渲染子进程异常退出 (exitcode: {p.exitcode})")
                if all(not p.is_alive() for p in procs):
                    break
                    
            now = time.time()
            if progress_callback and (now - last_update >= 0.1 or rendered_count == total_render_frames):
                elapsed = now - started
                fps = rendered_count / max(0.001, elapsed)
                eta = (total_render_frames - rendered_count) / max(0.001, fps)
                percent = (rendered_count / total_render_frames) * 100
                progress_callback({
                    "current": rendered_count,
                    "total": total_render_frames,
                    "output_frames": len(ts),
                    "fps": fps,
                    "elapsed": elapsed,
                    "eta": eta,
                    "percent": percent
                })
                last_update = now
                
        for p in procs:
            p.join()
            if p.exitcode != 0:
                raise RuntimeError(f"子进程执行失败，退出码: {p.exitcode}")
                
        # 所有分段生成完毕，进行无损快速拼接
        from dashboard import ffmpeg_path
        ff = ffmpeg_path()
        list_txt = temp_dir / "concat_list.txt"
        with open(list_txt, "w", encoding="utf-8") as f:
            for cf in chunk_files:
                clean_path = str(cf.resolve()).replace("\\", "/")
                f.write(f"file '{clean_path}'\n")
                
        concat_args = [
            ff, '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'concat', '-safe', '0',
            '-i', str(list_txt),
            '-c', 'copy',
            str(out_mov_path)
        ]
        
        ret = subprocess.run(concat_args, capture_output=True, **NO_WINDOW)
        if ret.returncode != 0:
            raise RuntimeError(f"FFmpeg 无损拼接失败: {ret.stderr.decode('utf-8', errors='replace')}")
            
    finally:
        # 清理工作：无论成功还是被取消，终止存活进程并清理临时分段
        for p in procs:
            if p.is_alive():
                p.terminate()
                p.join(timeout=1.0)
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass
