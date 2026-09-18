"""CSV loading, explicit motor mapping and video/data time alignment."""
import csv, io, json, math, re
from pathlib import Path
import numpy as np
import pandas as pd

DEFAULT=Path(__file__).resolve().parents[1]/'assets/default-config.json'
def merge(a,b):
    for k,v in b.items():
        if isinstance(v,dict) and isinstance(a.get(k),dict): merge(a[k],v)
        else: a[k]=v
    return a
def config(path=None):
    c=json.loads(DEFAULT.read_text(encoding='utf-8'))
    if path: merge(c,json.loads(Path(path).read_text(encoding='utf-8-sig')))
    if not 1<=c['fps']<=240: raise ValueError('fps must be 1..240')
    if not 1<=c['render_fps']<=c['fps'] or c['fps']%c['render_fps']:
        raise ValueError('render_fps must divide fps exactly')
    if not 1<=c['render_workers']<=32: raise ValueError('render_workers must be 1..32')
    if c.get('alpha_codec') not in ('prores4444','qtrle'):
        raise ValueError('alpha_codec must be prores4444 or qtrle')
    padding=c.get('padding_seconds',{})
    if any(not np.isfinite(float(padding.get(k,0))) or float(padding.get(k,0))<0 for k in ('head','tail')):
        raise ValueError('padding_seconds head/tail must be nonnegative')
    if min(c['width'],c['height'])<=0 or c['width']%2 or c['height']%2: raise ValueError('Use positive even dimensions')
    if abs(c['width']/c['height']-16/9)>0.001: raise ValueError('This layout requires 16:9')
    for k in ['speed_max_kmh','torque_max_nm','g_max','trail_seconds','max_gap_seconds']:
        if c[k]<=0: raise ValueError(k+' must be positive')
    if set(c['motors'])!={'FL','FR','RL','RR'}: raise ValueError('Motor slots must be FL, FR, RL, RR')
    if c['g_ball_direction'] not in [-1,1]: raise ValueError('g_ball_direction must be -1 (inertial) or 1 (acceleration)')
    for m in c['motors'].values():
        if not (isinstance(m['active'],bool) or m['active']=='auto'): raise ValueError('Motor active must be true, false, or auto')
    return c
def norm(s): return re.sub(r'[^a-z0-9]','',s.lower())
def load_csv(path):
    path=Path(path)
    if path.suffix.lower()=='.xrk': raise ValueError('XRK is not CSV. Export the session as AiM CSV in Race Studio first.')
    raw=path.read_bytes()
    for enc in ['utf-8-sig','gb18030','cp1252']:
        try: text=raw.decode(enc);break
        except UnicodeDecodeError: continue
    rows=list(csv.reader(io.StringIO(text)))
    candidates=[i for i,r in enumerate(rows) if r and norm(r[0])=='time']
    header=max(candidates,key=lambda i:len(rows[i])) if candidates else None
    if header is None: raise ValueError('No Time header found in CSV')
    columns=rows[header]
    if len(set(columns))!=len(columns): raise ValueError('Duplicate channel names; export distinct channel names')
    metadata={r[0]:r[1] for r in rows[:header] if len(r)>1}
    units={}
    if header+1<len(rows):
        try: float(rows[header+1][0])
        except (ValueError,IndexError): units=dict(zip(columns,rows[header+1]))
    d=pd.DataFrame([r for r in rows[header+1:] if len(r)==len(columns)],columns=columns)
    d=d.apply(pd.to_numeric,errors='coerce').replace([np.inf,-np.inf],np.nan)
    d=d.dropna(subset=[columns[0]]).sort_values(columns[0]).rename(columns={columns[0]:'Time'})
    if d.empty: raise ValueError('CSV contains no numeric timestamps')
    return d,metadata,units
def resolve(spec,columns):
    if spec is None: return None
    candidates=[spec] if isinstance(spec,str) else spec
    for name in candidates:
        found=[c for c in columns if norm(c)==norm(name)]
        if len(found)>1: raise ValueError('Ambiguous channel '+name)
        if found: return found[0]
    return None
def bound_channels(c):
    """布局控件绑定的额外数据通道：spec 的 source 或控件类 DEFAULT_SOURCE（可为列表）。"""
    keys = []
    for spec in (c.get('layout') or {}).get('widgets', []):
        if not isinstance(spec, dict):
            continue
        srcs = spec.get('source')
        if srcs is None:
            try:
                from widgets import REGISTRY
                w = REGISTRY.get(spec.get('type'))
                srcs = getattr(w, 'DEFAULT_SOURCE', None) if w else None
            except ImportError:
                srcs = None
        if srcs is None:
            continue
        for src in (srcs if isinstance(srcs, (list, tuple)) else [srcs]):
            if src and src not in keys and src != 'Data Time':
                keys.append(src)
    return keys
def _parse_segment(text):
    """AiM 'Segment Times'（如 '1:17.000'）→ 77.0；解析失败返回 0。"""
    try:
        parts = str(text).strip().split(':')
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(text)
    except (ValueError, TypeError):
        return 0
def seconds(value,fps):
    if isinstance(value,(int,float)): return float(value)
    if ';' in value: raise ValueError('Drop-frame timecode is not supported; use elapsed seconds or non-drop-frame timecode')
    parts=value.split(':')
    if len(parts)==4:
        h,m,s,f=map(int,parts)
        if not float(fps).is_integer(): raise ValueError('HH:MM:SS:FF requires integer timeline_fps; use decimal seconds for 29.97/59.94')
        if min(h,m,s,f)<0 or m>=60 or s>=60 or f>=fps: raise ValueError('Invalid timecode '+value)
        return h*3600+m*60+s+f/fps
    if len(parts)==3:
        h,m=map(int,parts[:2]);s=float(parts[2])
        if min(h,m,s)<0 or m>=60 or s>=60: raise ValueError('Invalid clock '+value)
        return h*3600+m*60+s
    return float(value)
def alignment(sync):
    fps=float(sync['timeline_fps'])
    if fps<=0: raise ValueError('timeline_fps must be positive')
    anchors=sync['anchors']
    if len(anchors)>2: raise ValueError('Supply zero, one or two sync anchors')
    if anchors and sync.get('offset_seconds',0)!=0: raise ValueError('Use anchors OR offset_seconds, not both')
    scale=1.;offset=float(sync.get('offset_seconds',0))
    if anchors:
        a=[(float(p['data_seconds']),seconds(p['video_time'],fps)) for p in anchors]
        if len(a)==2:
            if a[1][0]<=a[0][0] or a[1][1]<=a[0][1]: raise ValueError('Sync anchors must increase in both clocks')
            scale=(a[1][1]-a[0][1])/(a[1][0]-a[0][0])
        offset=a[0][1]-scale*a[0][0]
    if not np.isfinite(scale+offset): raise ValueError('Non-finite sync values')
    return scale,offset
def prepare(path,c,start=None,duration=None):
    d,meta,units=load_csv(path);scale,offset=alignment(c['sync'])
    fps=c['fps'];start=float(c['sync']['output_start'] if start is None else start)
    if not np.isfinite(start) or start<0: raise ValueError('output_start must be nonnegative seconds on the video timeline')
    source_end=max(float(meta.get('Duration',0) or 0),float(d.Time.max())+1/fps)
    length=duration if duration is not None else c['sync']['duration']
    if length is None: length=scale*source_end+offset-start
    if not np.isfinite(length) or length<=0: raise ValueError('Output duration must be positive')
    content_count=int(math.ceil(length*fps-1e-8))
    padding=c.get('padding_seconds',{});head=float(padding.get('head',0));tail=float(padding.get('tail',0))
    head_frames=int(round(head*fps));tail_frames=int(round(tail*fps));count=head_frames+content_count+tail_frames
    frame_index=np.arange(count);video_time=start+frame_index/fps
    content_video_time=start+(frame_index-head_frames)/fps
    query=(content_video_time-offset)/scale
    overlay_active=(frame_index>=head_frames)&(frame_index<head_frames+content_count)
    mappings={k:resolve(v,d.columns) for k,v in c['channels'].items()}
    if mappings['speed'] is None: raise ValueError('VehSpd not found. Set channels.speed explicitly; no silent GPS speed fallback.')
    warnings=[];motor_map={}
    def interpolate(name,kind=None):
        if name is None: return np.full(count,np.nan)
        a=d[['Time',name]].dropna().groupby('Time')[name].mean()
        if a.empty: return np.full(count,np.nan)
        u=units.get(name,'').strip().lower();factor=1.
        if kind=='speed' and u in ['m/s','mps']: factor=3.6
        elif kind=='speed' and u in ['mph']: factor=1.609344
        elif kind=='g' and u in ['m/s2','m/s^2','m/s²']: factor=1/9.80665
        elif kind=='speed' and u not in ['km/h','kph','kmh','']: raise ValueError('Unsupported speed unit '+u)
        elif kind=='g' and u not in ['g','']: raise ValueError('Unsupported acceleration unit '+u)
        elif kind=='torque' and u not in ['nm','n m','n*m','n·m','']: raise ValueError('Expected Nm for '+name)
        elif kind=='rpm' and u not in ['rpm','']: raise ValueError('Expected rpm for '+name)
        t=a.index.to_numpy();v=a.to_numpy()*factor
        result=np.interp(query,t,v,left=np.nan,right=np.nan)
        right=np.searchsorted(t,query,side='left');inside=(right>0)&(right<len(t));idx=np.clip(right,1,max(1,len(t)-1))
        if len(t)>1:
            gap=t[idx]-t[idx-1]
            result[inside&(gap>c['max_gap_seconds'])&(~np.isclose(query,t[np.minimum(right,len(t)-1)],rtol=0,atol=1e-8))]=np.nan
        return result
    names={'speed':'VehSpd','throttle':'Acc-2','brake':'Ave Brake','latitude':'GPS Latitude','longitude':'GPS Longitude','acc_x':'ACC X','acc_y':'ACC Y'}
    data={names[k]:interpolate(v,'speed' if k=='speed' else 'g' if k.startswith('acc_') else None) for k,v in mappings.items()}
    for k,v in mappings.items():
        if v is None: warnings.append('Missing channel: '+k)
    active=[]
    for slot,m in c['motors'].items():

        tq=resolve(m['torque'],d.columns);rpm=resolve(m['rpm'],d.columns)
        enabled=(tq is not None) if m['active']=='auto' else bool(m['active'])
        motor_map[slot]={'active':enabled,'torque':tq,'rpm':rpm}
        data[slot+' Torque']=interpolate(tq,'torque') if enabled else np.full(count,np.nan)
        data[slot+' RPM']=interpolate(rpm,'rpm') if enabled else np.full(count,np.nan)
        if enabled: active.append(slot)
        if enabled and (tq is None or rpm is None): warnings.append(slot+' incomplete torque/rpm: total power unavailable')
    assigned=[m['torque'] for m in motor_map.values() if m['active'] and m['torque']]
    if len(assigned)!=len(set(assigned)): raise ValueError('Do not map one torque channel to multiple motors')
    power=np.zeros(count) if active else np.full(count,np.nan)
    for slot in active: power+=data[slot+' Torque']*data[slot+' RPM']*2*math.pi/60000
    data['Power']=power
    brake=d[mappings['brake']].dropna() if mappings['brake'] else pd.Series(dtype=float)
    lo,hi=(float(brake.min()),float(brake.max())) if len(brake) else (None,None)
    if lo is None: data['Brake Relative']=np.full(count,np.nan)
    elif hi==lo:
        data['Brake Relative']=np.where(np.isfinite(data['Ave Brake']),0.,np.nan)
        warnings.append('Constant brake channel: relative range is undefined; display 0% for valid samples')
    else: data['Brake Relative']=(data['Ave Brake']-lo)/(hi-lo)*100
    data['Video Time']=video_time;data['Data Time']=query;data['Overlay Active']=overlay_active
    for key in bound_channels(c):
        col = resolve(key, d.columns)
        if col is None:
            if key in ('Steer Sense', 'Ave Steer') and (resolve('Steer Sense', d.columns) or resolve('Ave Steer', d.columns)):
                data[key] = np.full(count, np.nan)
                continue
            warnings.append('Missing channel: ' + key)
            data[key] = np.full(count,np.nan)
        else:
            data[key] = interpolate(col)
    lt=mappings['latitude'];ln=mappings['longitude']
    route=d[['Time',lt,ln]].copy() if lt and ln else None
    if route is not None:
        route=route.groupby('Time')[[lt,ln]].mean().dropna()
        data['Route Latitude']=route[lt].to_numpy();data['Route Longitude']=route[ln].to_numpy()
        data['Route Time']=route.index.to_numpy()
    else:
        data['Route Latitude']=np.array([]);data['Route Longitude']=np.array([]);data['Route Time']=np.array([])
    report={'source':str(Path(path).resolve()),'fps':fps,'frames':count,'duration':count/fps,
      'content_duration':content_count/fps,'size':[c['width'],c['height']],
      'alpha_codec':c['alpha_codec'],
      'padding':{'head_seconds':head,'tail_seconds':tail},
      'channels':mappings,'motors':motor_map,'brake_range':[lo,hi],
      'alignment':{'status':'anchored' if c['sync']['anchors'] else 'offset' if offset else 'unverified_identity',
        'formula':'video_seconds = data_seconds * scale + offset_seconds','scale':scale,'offset_seconds':offset,
        'output_start':start,'drift_ppm':(scale-1)*1e6,'timeline_fps':c['sync']['timeline_fps'],'anchors':c['sync']['anchors']},
      'meta': {'vehicle': str(meta.get('Vehicle', '')),
               'racer': str(meta.get('Racer', '')),
               'lap_seconds': _parse_segment(meta.get('Segment Times'))},
      'warnings':warnings}
    return data,query,report
