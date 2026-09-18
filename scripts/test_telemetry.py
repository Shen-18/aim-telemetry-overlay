import csv, math, tempfile, threading, time, unittest
from pathlib import Path
import numpy as np
from PIL import Image
from telemetry import config,prepare,alignment,seconds
from hud import g_ball_offset,make_renderer
import dashboard
import widgets

class TelemetryTests(unittest.TestCase):
    def unpadded_config(self):
        c=config();c['padding_seconds']={'head':0,'tail':0};return c

    def test_inertial_g_ball_direction(self):
        c=self.unpadded_config()
        self.assertGreater(g_ball_offset(1,0,c,100)[1],0)
        self.assertLess(g_ball_offset(-1,0,c,100)[1],0)
        self.assertGreater(g_ball_offset(0,-1,c,100)[0],0)
        self.assertLess(g_ball_offset(0,1,c,100)[0],0)
    def sample(self,folder,four=True,constant=False,gap=False):
        path=Path(folder)/'session.csv'
        columns=['Time','VehSpd','Acc-2','Ave Brake','ACC X','ACC Y']
        motors=['FL','FR','RL','RR'] if four else ['RL','RR']
        for m in motors: columns += [m+' Torque',m+' RPM']
        with path.open('w',newline='') as f:
            w=csv.writer(f);w.writerow(['Time','8:59 PM']);w.writerow(['Duration','2']);w.writerow(columns)
            w.writerow(['s','km/h','%','#','g','g']+['Nm','rpm']*len(motors))
            for i in range(201):
                if gap and 50<i<150: continue
                w.writerow([i/100,36,50,8 if constant else i*0.4,0.1,0.2]+[10,1000]*len(motors))
        return path
    def test_four_and_two_motors_and_trim(self):
        with tempfile.TemporaryDirectory() as t:
            c=self.unpadded_config();c['fps']=100  # 断言按 100fps 采样索引
            p=self.sample(t);d,_,r=prepare(p,c,duration=1)
            self.assertAlmostEqual(d['Power'][50],4*10*1000*2*math.pi/60000)
            self.assertEqual(r['brake_range'],[0,80]);self.assertAlmostEqual(d['Brake Relative'][50],25)
            p=self.sample(t,four=False);d,_,r=prepare(p,c,duration=1)
            self.assertTrue(np.isnan(d['FL Torque']).all());self.assertFalse(r['motors']['FL']['active'])
            self.assertAlmostEqual(d['Power'][50],2*10*1000*2*math.pi/60000)
    def test_gap_and_constant_brake(self):
        with tempfile.TemporaryDirectory() as t:
            c=self.unpadded_config();c['fps']=100  # 断言按 100fps 采样索引
            p=self.sample(t,constant=True,gap=True);d,_,r=prepare(p,c)
            self.assertTrue(np.isnan(d['VehSpd'][100]));self.assertEqual(d['VehSpd'][150],36)
            self.assertEqual(d['Brake Relative'][10],0);self.assertTrue(np.isnan(d['Brake Relative'][100]))
    def test_alignment_and_sampling(self):
        c=self.unpadded_config();c['sync']['timeline_fps']=25
        c['sync']['anchors']=[{'data_seconds':5,'video_time':'00:00:12:10'}]
        scale,offset=alignment(c['sync']);self.assertEqual(scale,1);self.assertAlmostEqual(offset,7.4)
        c['sync']['anchors']=[{'data_seconds':0,'video_time':5},{'data_seconds':100,'video_time':105.1}]
        scale,offset=alignment(c['sync']);self.assertAlmostEqual(scale,1.001);self.assertEqual(offset,5)
        with tempfile.TemporaryDirectory() as t:
            c['fps']=100  # 帧数断言按 100fps
            d,_,r=prepare(self.sample(t),c,start=5.5005,duration=.1)
            self.assertAlmostEqual(d['Data Time'][0],.5);self.assertEqual(r['frames'],10)
        with self.assertRaises(ValueError): seconds('00:00:01;12',30)
        with self.assertRaises(ValueError): seconds('00:00:01:30',25)
    def test_missing_rpm_does_not_report_partial_total(self):
        c=self.unpadded_config();c['motors']['FL']['rpm']=None
        with tempfile.TemporaryDirectory() as t:
            d,_,r=prepare(self.sample(t),c,duration=.1)
            self.assertTrue(np.isnan(d['Power']).all())
    def test_no_channel_duplication(self):
        c=self.unpadded_config();c['motors']['FR']['torque']='FL Torque'
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError): prepare(self.sample(t),c,duration=.1)

    def test_render_indices_sample_20hz_for_100fps_output(self):
        self.assertEqual(
            list(dashboard.render_indices(frame_count=1000, output_fps=100, render_fps=20)),
            list(range(0, 1000, 5)),
        )

    def test_parallel_map_preserves_order_and_bounds_work(self):
        lock=threading.Lock();active=0;peak=0
        def work(value):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active)
            time.sleep((4-value)*.002)
            with lock: active-=1
            return value*10
        result=list(dashboard.ordered_parallel_map(work,range(5),workers=2,prefetch=2))
        self.assertEqual(result,[0,10,20,30,40])
        self.assertLessEqual(peak,2)

    def test_padding_extends_file_timeline_without_consuming_data_time(self):
        with tempfile.TemporaryDirectory() as t:
            c=config();c['fps']=100;c['padding_seconds']={'head':.1,'tail':.1}
            d,_,r=prepare(self.sample(t),c,duration=.1)
            self.assertEqual(r['frames'],30)
            self.assertEqual(r['padding'],{'head_seconds':.1,'tail_seconds':.1})
            self.assertFalse(d['Overlay Active'][9])
            self.assertTrue(d['Overlay Active'][10])
            self.assertAlmostEqual(d['Data Time'][10],0)
            self.assertFalse(d['Overlay Active'][20])

    def test_padding_keeps_ui_visible_while_data_is_inactive(self):
        with tempfile.TemporaryDirectory() as t:
            c=self.unpadded_config();c['fps']=100;c['padding_seconds']={'head':.1,'tail':.1}
            c['width']=1920;c['height']=1080
            c['layout']={'widgets':[{'type':'timecode','x':20,'y':20,'origin':'tl'}]}
            d,ts,r=prepare(self.sample(t),c,duration=.1);draw=make_renderer(d,ts,c,r['meta'])
            self.assertGreater(np.asarray(draw(0))[:,:,3].max(),0)
            self.assertGreater(np.asarray(draw(10))[:,:,3].max(),0)
            self.assertGreater(np.asarray(draw(20))[:,:,3].max(),0)

    def test_verification_samples_expect_blank_padding_and_visible_content(self):
        report={'duration':12,'content_duration':2,
                'padding':{'head_seconds':5,'tail_seconds':5}}
        self.assertEqual(dashboard.verification_samples(report),[(2.5,False),(6.0,False),(9.5,False)])

    def test_hud_value_labels_are_bounded_and_explicit(self):
        self.assertEqual(widgets.steer_text(12.4),'+12°')
        self.assertEqual(widgets.steer_text(float('nan')),'--')
        self.assertEqual(widgets.pedal_text(-5),'0')
        self.assertEqual(widgets.pedal_text(47.4),'47')
        self.assertEqual(widgets.pedal_text(140),'100')

    def test_speed_bar_uses_fixed_120_kmh_scale(self):
        self.assertEqual(widgets.speed_ticks(),[0,30,60,90,120])
        self.assertEqual(widgets.speed_fraction(60),.5)
        self.assertEqual(widgets.speed_fraction(150),1.0)

    def test_prores_4444_uses_alpha_capable_codec_settings(self):
        self.assertEqual(dashboard.alpha_codec_args('prores4444'),
            ['-c:v','prores','-profile:v','4','-pix_fmt','yuva444p10le'])
        self.assertEqual(dashboard.alpha_codec_args('qtrle'),
            ['-c:v','qtrle','-pix_fmt','argb'])
        with self.assertRaises(ValueError): dashboard.alpha_codec_args('h264')

    def test_logo_alpha_has_no_low_opacity_background_noise(self):
        alpha=np.asarray(Image.open(Path(__file__).parent/'assets'/'logo_white.png').convert('RGBA'))[:,:,3]
        visible=alpha>0;low=(alpha>0)&(alpha<32)
        self.assertLess(low.sum()/visible.sum(),.08)

if __name__=='__main__': unittest.main()
