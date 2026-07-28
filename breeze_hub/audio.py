"""Audio capture helpers shared by the realtime service and the calibrator.

The interesting part is `open_capture`: instead of trusting a single configured
ALSA device, it builds a candidate list and walks it until one actually yields
PCM. A device that exists in `arecord -L` is not necessarily a device you can
read from -- that is the failure mode this module exists to absorb.
"""

import math
import struct
import subprocess
import time

from . import config


def _run(cmd):
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        return out.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def list_capture_devices():
    """Return ALSA PCM names that can capture, best guess first.

    `arecord -L` lists PCM names (`sysdefault:CARD=C525`); `arecord -l` lists raw
    hardware (`card 2: C525 ...`). We prefer the former because plug/sysdefault
    handles rate conversion, and fall back to `hw:` only if nothing else matches.
    """
    names = []
    for line in _run(["arecord", "-L"]).splitlines():
        if line and not line[0].isspace():
            names.append(line.strip())
    return names


def candidate_devices():
    """Ordered list of devices to try, from most to least specific."""
    candidates = []

    def add(name):
        if name and name not in candidates:
            candidates.append(name)

    # 1. Explicit configuration always wins.
    add(config.MIC_DEVICE)

    names = list_capture_devices()
    keyword = config.MIC_KEYWORD.lower()

    # 2. A PCM whose name matches the preferred keyword (e.g. a USB webcam mic).
    if keyword:
        for name in names:
            if keyword in name.lower() and name.startswith(("sysdefault", "plughw", "front")):
                add(name)

    # 3. Any USB-ish sysdefault that is not the SoC's own audio processor.
    #    On Jetson, `APE` is the onboard Tegra audio engine with nothing wired to
    #    it, so it appears usable and silently returns silence -- skip it.
    for name in names:
        if name.startswith("sysdefault:CARD=") and "APE" not in name.upper():
            add(name)

    # 4. Whatever the system considers default.
    add("default")

    return candidates


def _spawn(device):
    return subprocess.Popen(
        [
            "arecord",
            "-D", device,
            "-f", "S16_LE",
            "-r", str(config.SAMPLE_RATE),
            "-c", "1",
            "-t", "raw",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def open_capture(probe_seconds=1.0):
    """Start `arecord` on the first candidate that actually delivers samples.

    Returns (process, device_name). Raises RuntimeError if every candidate fails,
    which is a real error worth crashing on -- a listening service with no
    microphone has nothing to do.
    """
    errors = []
    for device in candidate_devices():
        proc = _spawn(device)
        deadline = time.time() + probe_seconds
        got_data = False
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            chunk = proc.stdout.read(config.FRAME_BYTES)
            if chunk and len(chunk) == config.FRAME_BYTES:
                got_data = True
                break
        if got_data:
            return proc, device
        errors.append(device)
        try:
            proc.kill()
        except OSError:
            pass
    raise RuntimeError(
        "No usable capture device. Tried: {}. "
        "Check `arecord -L`, then set MIC_DEVICE in .env.".format(", ".join(errors) or "none")
    )


def calculate_rms(raw_bytes):
    """RMS of a little-endian signed 16-bit PCM frame, in raw sample units."""
    count = len(raw_bytes) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack("<{}h".format(count), raw_bytes)
    return math.sqrt(sum(s * s for s in shorts) / count)


def wav_bytes(pcm_data, sample_rate=None):
    """Wrap raw PCM in a minimal 16-bit mono WAV container."""
    sample_rate = sample_rate or config.SAMPLE_RATE
    data_size = len(pcm_data)
    byte_rate = sample_rate * config.BYTES_PER_SAMPLE
    header = bytearray()
    header.extend(b"RIFF")
    header.extend((data_size + 36).to_bytes(4, "little"))
    header.extend(b"WAVEfmt ")
    header.extend((16).to_bytes(4, "little"))
    header.extend((1).to_bytes(2, "little"))   # PCM
    header.extend((1).to_bytes(2, "little"))   # mono
    header.extend(sample_rate.to_bytes(4, "little"))
    header.extend(byte_rate.to_bytes(4, "little"))
    header.extend(config.BYTES_PER_SAMPLE.to_bytes(2, "little"))
    header.extend((16).to_bytes(2, "little"))  # bits per sample
    header.extend(b"data")
    header.extend(data_size.to_bytes(4, "little"))
    return bytes(header) + bytes(pcm_data)


def write_wav(path, pcm_data, sample_rate=None):
    with open(str(path), "wb") as handle:
        handle.write(wav_bytes(pcm_data, sample_rate))
