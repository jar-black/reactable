import time

import pyo

VOICES = ("kick", "snare", "hihat", "clap", "tom")


class DrumKit:
    def __init__(self, sr=44100, buffersize=512):
        self.server = pyo.Server(sr=sr, nchnls=2, buffersize=buffersize, duplex=0)
        self.server.setOutputDevice(self._find_output())
        self.server.boot()
        self.server.start()
        self._objs = []
        self.triggers = []
        for name in VOICES:
            trig = pyo.Trig()
            self._objs.append(trig)
            self.triggers.append(trig)
            self._build(name, trig)
        time.sleep(0.4)

    def _keep(self, *objs):
        self._objs.extend(objs)

    @staticmethod
    def _find_output():
        try:
            names, _ = pyo.pa_get_output_devices()
            for i, name in enumerate(names):
                if "headphones" in name.lower() or "bcm2835" in name.lower():
                    return i
        except Exception:
            pass
        return 0

    def _build(self, name, trig):
        if name == "kick":
            amp_table = pyo.ExpTable([(0, 0.0), (16, 1.0), (8191, 0.0001)], exp=5.0)
            freq_table = pyo.LinTable([(0, 150.0), (8191, 45.0)])
            click_table = pyo.ExpTable([(0, 0.0), (16, 1.0), (8191, 0.0001)], exp=12.0)
            amp = pyo.TrigEnv(trig, table=amp_table, dur=0.35, mul=0.5)
            freq = pyo.TrigEnv(trig, table=freq_table, dur=0.35)
            body = pyo.Sine(freq=freq, mul=amp)
            noise = pyo.Noise()
            click_env = pyo.TrigEnv(trig, table=click_table, dur=0.02, mul=0.15)
            click = pyo.ButHP(noise, freq=4000, mul=click_env)
            out = (body + click).out()
            self._keep(amp_table, freq_table, click_table, amp, freq, body,
                       noise, click_env, click, out)
        elif name == "snare":
            amp_table = pyo.ExpTable([(0, 0.0), (16, 1.0), (8191, 0.0001)], exp=7.0)
            snap_table = pyo.ExpTable([(0, 0.0), (16, 1.0), (8191, 0.0001)], exp=12.0)
            amp = pyo.TrigEnv(trig, table=amp_table, dur=0.25, mul=0.55)
            noise = pyo.Noise()
            body = pyo.ButBP(noise, freq=1800, q=0.7, mul=amp)
            snap_env = pyo.TrigEnv(trig, table=snap_table, dur=0.05, mul=0.5)
            snap = pyo.ButHP(noise, freq=6500, mul=snap_env)
            tone_mul = amp * 0.5
            tone = pyo.Sine(freq=180, mul=tone_mul)
            out = (body + snap + tone).out()
            self._keep(amp_table, snap_table, amp, noise, body, snap_env, snap,
                       tone_mul, tone, out)
        elif name == "hihat":
            amp_table = pyo.ExpTable([(0, 0.0), (16, 1.0), (8191, 0.0001)], exp=12.0)
            amp = pyo.TrigEnv(trig, table=amp_table, dur=0.09, mul=0.4)
            noise = pyo.Noise()
            hat = pyo.ButHP(noise, freq=8000, mul=amp)
            out = hat.out()
            self._keep(amp_table, amp, noise, hat, out)
        elif name == "clap":
            env_table = pyo.LinTable([(0, 0.0), (400, 1.0), (900, 0.15),
                                      (1600, 0.85), (2100, 0.15),
                                      (3000, 0.6), (4000, 0.0), (8191, 0.0)])
            env = pyo.TrigEnv(trig, table=env_table, dur=0.3, mul=0.6)
            noise = pyo.Noise()
            clap = pyo.ButBP(noise, freq=1500, q=1.0, mul=env)
            out = clap.out()
            self._keep(env_table, env, noise, clap, out)
        elif name == "tom":
            amp_table = pyo.ExpTable([(0, 0.0), (16, 1.0), (8191, 0.0001)], exp=6.0)
            freq_table = pyo.LinTable([(0, 220.0), (8191, 90.0)])
            amp = pyo.TrigEnv(trig, table=amp_table, dur=0.45, mul=0.5)
            freq = pyo.TrigEnv(trig, table=freq_table, dur=0.45)
            body = pyo.Sine(freq=freq, mul=amp)
            out = body.out()
            self._keep(amp_table, freq_table, amp, freq, body, out)
        else:
            raise ValueError(f"unknown voice {name}")

    def trigger(self, index):
        self.triggers[index % len(self.triggers)].play()

    def shutdown(self):
        self.server.stop()
        self.server.shutdown()
