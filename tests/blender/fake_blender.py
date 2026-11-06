"""A FAKE Blender for runner/film tests: speaks the SR_* protocol of blender_kits/lib/entry.py without bpy.

    python fake_blender.py [-b ...ignored...] -- <job.json>

Behaviour from ``job["params"]["_fake"]`` (default "ok"):
  ok            build, render each requested frame (Pillow, a gradient that depends on frame + params), SR_DONE
  crash_exit0   print a Python traceback after 1 frame and exit 0 (Blender's "script crashed, exit 0" case)
  error         SR_ERROR + traceback, exit 1
  partial       render the first 2 requested frames, then exit 1 without SR_DONE
  slow          like ok but sleeps ``_sleep`` s per frame (cancel tests); writes its PID to <out>/fake.pid
  blank         every frame one flat colour
  truncated     frames are cut-off JPEGs
  nodone        render all frames, exit 0, but never print SR_DONE
Every invocation appends one line to ``<out_dir>/../fake_calls.txt`` (cache tests count renders).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
    params = job.get("params") or {}
    mode = params.get("_fake", "ok")
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    with open(out.parent / "fake_calls.txt", "a", encoding="utf-8") as f:
        f.write(f"{out.name} {json.dumps(job.get('frames'))}\n")
    (out / "fake.pid").write_text(str(os.getpid()), encoding="utf-8")
    print(f"SR_START blender=fake scene={job['scene']}", flush=True)
    print("Fra:1 Mem:12.00M (noise Blender prints)", flush=True)
    if mode == "error":
        print("SR_ERROR ValueError: bad param 'x'", flush=True)
        print("Traceback (most recent call last):\n  File \"scene.py\", line 3, in build\nValueError: bad param 'x'",
              flush=True)
        return 1
    print("SR_BUILD_DONE s=0.010", flush=True)
    frames = job["frames"] if job.get("frames") is not None else list(range(1, int(job["frame_count"]) + 1))
    w, h = job["res"]
    ext = job.get("out_ext") or "jpg"
    from PIL import Image
    times = []
    for k, f in enumerate(frames):
        if mode == "partial" and k >= 2:
            return 1
        if mode == "slow":
            time.sleep(float(params.get("_sleep", 0.5)))
        if mode == "blank":
            im = Image.new("RGB", (w, h), (0, 0, 0))
        else:
            im = Image.linear_gradient("L").resize((w, h)).convert("RGB")
            im.paste((int(f * 7) % 255, 40, 200), (0, 0, max(1, w // 4), max(1, h // 4)))
        path = out / f"{int(f):06d}.{ext}"
        im.save(path, quality=90) if ext == "jpg" else im.save(path)
        if mode == "truncated":
            data = path.read_bytes()
            path.write_bytes(data[: len(data) // 2])
        times.append(0.01)
        print(f"SR_FRAME {f} 0.010", flush=True)
        if mode == "crash_exit0":
            print("Traceback (most recent call last):\n  File \"lib/flyers.py\", line 9, in on_frame\n"
                  "AttributeError: 'NoneType' object has no attribute 'location'", flush=True)
            return 0
    if job.get("cues_out"):
        Path(job["cues_out"]).write_text(json.dumps([{"t": 0.25, "sfx": "whoosh"}]), encoding="utf-8")
    if job.get("stats_out"):
        Path(job["stats_out"]).write_text(json.dumps({"build_s": 0.01, "mean_frame_s": 0.01, "frame_s": times,
                                                      "frames": len(times), "blender_version": "fake",
                                                      "engine": "FAKE", "device": "none"}), encoding="utf-8")
    if mode != "nodone":
        print(f"SR_DONE frames={len(times)} mean=0.010", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
