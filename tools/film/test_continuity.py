"""Local, model-free regression checks for opt-in edit safety."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
from continuity import audio_mix, trim_window, grade_filter
from continuity_report import scale_estimate, frame, duration
from check_shot_sizes import check
from ltx_stage import static_prompt, STATIC_CAMERA, framing_prompt

class ContinuityTests(unittest.TestCase):
    def test_script_rules(self):
        shots=[dict(id='a',scene='S01',shot_size='WS'),dict(id='b',scene='S01',shot_size='CU')]
        self.assertEqual(len(check(shots)),1)
        shots[1]['scene']='S02'; self.assertEqual(check(shots),[])
        self.assertIn(STATIC_CAMERA,static_prompt('locked-off camera with a very slow push-in.'))
        self.assertNotIn('very slow push-in',static_prompt('locked-off camera with a very slow push-in.'))
        self.assertIn('environment',framing_prompt({'shot_size':'MS'}))

    def test_speech_protection(self):
        shot=dict(dialogue=True,push_in=dict(reliable=True,scale=1.6),in_point=.25,out_point=6)
        self.assertEqual(trim_window(shot,{'out':5.9}),{'out':5.9})
        shot['dialogue']=False
        self.assertEqual(trim_window(shot,{'out':5.9}),{'out':5.9})
        self.assertLess(trim_window(shot,{})['out'],6)

    def test_scale(self):
        from PIL import Image
        rng=np.random.default_rng(4); a=rng.integers(0,255,(144,256,3),dtype=np.uint8)
        b=np.asarray(Image.fromarray(a[24:120,43:213]).resize((256,144),Image.Resampling.BILINEAR))
        self.assertAlmostEqual(scale_estimate(a,b)['scale'],1.5,delta=.05)

    def test_measure_rejects_replacement(self):
        from unittest.mock import patch
        from continuity_report import measure
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'raw.mp4'; path.write_bytes(b'old')
            shot=dict(id='test',scene='S01',engine='h3',seconds=2,_source=str(path))
            def changed(*args):
                path.write_bytes(b'new take with different length')
                return np.zeros((144,256,3),dtype=np.uint8)
            with patch('continuity_report.duration',return_value=2), patch('continuity_report.frame',side_effect=changed), patch('continuity_report.loudness',return_value=-18):
                with self.assertRaisesRegex(RuntimeError,'Source changed'):
                    measure((shot,{}))

    def test_audio_handles_preserve_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder); source=p/'source.wav'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=2','-ac','2',str(source)],check=True)
            timeline=[dict(id='a',scene='S01',start=0,length=1,**{'in':.25,'out':1.25}),dict(id='b',scene='S02',start=1,length=1,**{'in':.25,'out':1.25})]
            measured={k:dict(source=str(source),duration=2,lufs=-21) for k in ['a','b']}
            for mode in [None,'j','l']:
                out=p/f'{mode}.wav'; audio_mix(timeline,measured,out,-18,True,mode)
                self.assertAlmostEqual(duration(out),2,places=4)
                raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(out),'-f','f32le','-'])
                samples=np.frombuffer(raw,np.float32)
                self.assertTrue(np.isfinite(samples).all())
                self.assertLess(float(np.max(np.abs(samples))),.9)

if __name__=='__main__': unittest.main()
