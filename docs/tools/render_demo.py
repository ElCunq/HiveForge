"""Render docs/demo.html frame by frame with headless Chrome (CDP virtual time), then encode MP4 + GIF.

One browser session, the clock frozen between frames, so every frame is deterministic. The page's own
performance.now() is sampled per frame and the video is encoded at the rate that clock actually advanced,
so playback runs at the speed the reel was designed for.

Usage: python docs/tools/render_demo.py [--fps 12] [--out docs] [--frames DIR]
Needs google-chrome-stable (or $CHROME), ffmpeg and aiohttp.
"""

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[2]
CHROME = os.environ.get("CHROME") or shutil.which("google-chrome-stable") or shutil.which("chromium")
FLAGS = [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--mute-audio",
    "--no-first-run",
    "--run-all-compositor-stages-before-draw",
    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--disable-checker-imaging",
]
MAX_SECONDS = 60  # safety stop if the page never reports it finished


class CDP:
    def __init__(self, ws):
        self.ws, self.n, self.waiters, self.events = ws, 0, {}, asyncio.Queue()

    async def pump(self):
        async for msg in self.ws:
            m = json.loads(msg.data)
            if "id" in m:
                self.waiters.pop(m["id"]).set_result(m)
            else:
                await self.events.put(m)

    async def call(self, method, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.waiters[self.n] = fut
        await self.ws.send_str(json.dumps({"id": self.n, "method": method, "params": params}))
        m = await fut
        if "error" in m:
            raise RuntimeError(f"{method}: {m['error']}")
        return m["result"]

    async def eval(self, expr, **kw):
        return (await self.call("Runtime.evaluate", expression=expr, returnByValue=True, **kw))["result"].get("value")

    async def wait_event(self, name):
        while True:
            e = await self.events.get()
            if e["method"] == name:
                return e


async def capture(browser_ws: str, frames_dir: Path, fps: int) -> float:
    """Writes frames, returns the real playback fps measured from the page clock."""
    port = browser_ws.split(":")[2].split("/")[0]
    async with aiohttp.ClientSession() as http:
        targets = await (await http.get(f"http://127.0.0.1:{port}/json")).json()
        page_ws = next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")
        async with http.ws_connect(page_ws, max_msg_size=0) as ws:
            cdp = CDP(ws)
            pump = asyncio.create_task(cdp.pump())
            await cdp.call("Page.enable")
            # --window-size would include window chrome; pin the viewport itself
            await cdp.call(
                "Emulation.setDeviceMetricsOverride", width=1280, height=720, deviceScaleFactor=1, mobile=False
            )
            await cdp.call("Page.navigate", url=(ROOT / "docs" / "demo.html").as_uri() + "?noloop&manual&timer")
            await cdp.wait_event("Page.loadEventFired")
            await cdp.eval("document.fonts.ready.then(() => true)", awaitPromise=True)  # fonts load in real time
            await cdp.call("Emulation.setVirtualTimePolicy", policy="pause")
            t0 = await cdp.eval("window.__go(), performance.now()")
            n, t = 0, t0
            while n < MAX_SECONDS * fps:
                await cdp.call("Emulation.setVirtualTimePolicy", policy="advance", budget=1000 / fps)
                await cdp.wait_event("Emulation.virtualTimeBudgetExpired")
                shot = await cdp.call("Page.captureScreenshot", format="png")
                (frames_dir / f"{n:04d}.png").write_bytes(base64.b64decode(shot["data"]))
                n += 1
                t = await cdp.eval("performance.now()")
                if await cdp.eval("!!window.__finished"):
                    break
            pump.cancel()
    return n / ((t - t0) / 1000)


async def render(frames_dir: Path, fps: int) -> float:
    profile = tempfile.mkdtemp(prefix="demo-chrome-")
    proc = subprocess.Popen(
        [CHROME, *FLAGS, f"--user-data-dir={profile}", "--remote-debugging-port=0", "about:blank"],
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        browser_ws = next(line.split()[-1] for line in proc.stderr if "DevTools listening on" in line)
        return await capture(browser_ws, frames_dir, fps)
    finally:
        proc.terminate()
        proc.wait()
        shutil.rmtree(profile, ignore_errors=True)


def encode(frames_dir: Path, rate: float, out: Path):
    src = ["-framerate", f"{rate:.4f}", "-i", str(frames_dir / "%04d.png")]
    run = lambda *a: subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *src, *a], check=True)  # noqa: E731
    run(
        "-vf",
        "fps=30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        str(out / "demo.mp4"),
    )
    run(
        "-vf",
        "fps=10,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff:max_colors=96[p];"
        "[b][p]paletteuse=dither=none:diff_mode=rectangle",
        str(out / "demo.gif"),
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=12, help="frames captured per second of page time")
    ap.add_argument("--out", type=Path, default=ROOT / "docs")
    ap.add_argument("--frames", type=Path, help="keep frames here (default: temp dir)")
    a = ap.parse_args()
    frames = a.frames or Path(tempfile.mkdtemp(prefix="demo-frames-"))
    frames.mkdir(parents=True, exist_ok=True)
    for old in frames.glob("[0-9][0-9][0-9][0-9].png"):
        old.unlink()
    rate = asyncio.run(render(frames, a.fps))
    encode(frames, rate, a.out)
    count = len(list(frames.glob("*.png")))
    print(
        f"{count} frames, page clock rate {rate:.2f} fps -> {count / rate:.1f} s\n"
        f"frames: {frames}\nwrote {a.out / 'demo.mp4'} and {a.out / 'demo.gif'}"
    )
