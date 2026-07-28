"""Derive a VAD threshold for whatever microphone this machine actually has.

The old hard-coded 1200 was correct for one Logitech C525 in one room. Any other
mic, gain setting or room gives a different noise floor, so a fixed number is the
single least portable thing in a "hardware agnostic" project.

    python3 -m breeze_hub.calibrate            # measure and print
    python3 -m breeze_hub.calibrate --write    # also persist to hardware.json

Stay quiet for the ambient phase, then speak normally for the speech phase.
"""

import argparse
import json
import sys
import time

from . import audio, config

# Multiplier applied to the ambient floor when the speech sample is unusable.
# 3x sits well above typical room noise without swallowing quiet speech.
FALLBACK_MARGIN = 3.0


def _measure(proc, seconds, label):
    samples = []
    deadline = time.time() + seconds
    last_print = 0.0
    while time.time() < deadline:
        frame = proc.stdout.read(config.FRAME_BYTES)
        if not frame or len(frame) < config.FRAME_BYTES:
            continue
        rms = audio.calculate_rms(frame)
        samples.append(rms)
        now = time.time()
        if now - last_print > 0.25:
            remaining = deadline - now
            bar = "#" * min(40, int(rms / 200))
            sys.stdout.write("\r  {} {:4.1f}s  RMS {:6.0f} |{:<40}|".format(label, remaining, rms, bar))
            sys.stdout.flush()
            last_print = now
    sys.stdout.write("\r" + " " * 78 + "\r")
    return samples


def _percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * fraction)))
    return ordered[index]


def calibrate(ambient_seconds=5.0, speech_seconds=5.0):
    proc, device = audio.open_capture()
    print("Capturing from: {}".format(device))
    try:
        print("\n[1/2] Ambient noise -- please stay silent.")
        ambient = _measure(proc, ambient_seconds, "ambient")
        print("\n[2/2] Speech -- please talk normally.")
        speech = _measure(proc, speech_seconds, "speech ")
    finally:
        try:
            proc.kill()
        except OSError:
            pass

    # 95th percentile of ambient ignores the occasional door slam; 25th
    # percentile of speech represents the quiet parts we still want to catch.
    floor = _percentile(ambient, 0.95)
    voice = _percentile(speech, 0.25)

    if voice > floor * 1.5:
        threshold = (floor + voice) / 2.0
        basis = "midpoint between noise floor and quiet speech"
    else:
        threshold = floor * FALLBACK_MARGIN
        basis = "ambient floor x{:g} (speech sample too close to noise)".format(FALLBACK_MARGIN)

    return {
        "device": device,
        "ambient_floor": round(floor),
        "speech_level": round(voice),
        "vad_noise_threshold": int(threshold),
        "basis": basis,
    }


def main():
    parser = argparse.ArgumentParser(description="Calibrate the VAD noise threshold.")
    parser.add_argument("--ambient", type=float, default=5.0, help="seconds of silence to sample")
    parser.add_argument("--speech", type=float, default=5.0, help="seconds of speech to sample")
    parser.add_argument("--write", action="store_true", help="save the result into hardware.json")
    args = parser.parse_args()

    result = calibrate(args.ambient, args.speech)

    print("\nResults")
    print("  ambient floor (p95) : {}".format(result["ambient_floor"]))
    print("  speech level  (p25) : {}".format(result["speech_level"]))
    print("  suggested threshold : {}  <- {}".format(result["vad_noise_threshold"], result["basis"]))

    if result["speech_level"] <= result["ambient_floor"]:
        print("\n  WARNING: speech was not louder than the room. Check mic gain or"
              "\n           move closer before trusting this number.")

    if args.write:
        data = {}
        if config.HARDWARE_FILE.exists():
            data = json.loads(config.HARDWARE_FILE.read_text(encoding="utf-8"))
        data["mic_device"] = result["device"]
        data["vad_noise_threshold"] = result["vad_noise_threshold"]
        config.HARDWARE_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print("\nSaved to {}".format(config.HARDWARE_FILE))
    else:
        print("\nTo apply, add to .env:")
        print("  MIC_DEVICE={}".format(result["device"]))
        print("  VAD_NOISE_THRESHOLD={}".format(result["vad_noise_threshold"]))
        print("or re-run with --write to store it in hardware.json.")


if __name__ == "__main__":
    main()
