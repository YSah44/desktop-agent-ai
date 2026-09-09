import sounddevice as sd
import numpy as np
import time

print("=" * 50)
print("MICROPHONE DIAGNOSTIC TEST")
print("=" * 50)

print(f"\nDefault input device: {sd.default.device[0]}")
print(f"Default output device: {sd.default.device[1]}")

devices = sd.query_devices()
input_devices = []
print("\n--- All Input Devices ---")
for i, d in enumerate(devices):
    if d['max_input_channels'] > 0:
        default = " *** DEFAULT ***" if i == sd.default.device[0] else ""
        print(f"  [{i}] {d['name']}")
        print(f"       Channels: {d['max_input_channels']}, Sample Rate: {d['default_samplerate']}{default}")
        input_devices.append(i)

print(f"\n--- Testing each input device for 2 seconds ---")
print("Speak into your mic during each test!\n")

for dev_id in input_devices:
    dev_name = devices[dev_id]['name']
    print(f"Testing [{dev_id}] {dev_name}...")
    try:
        levels = []
        def callback(indata, frames, time_info, status):
            level = np.mean(np.abs(indata))
            levels.append(level)

        stream = sd.InputStream(
            device=dev_id,
            channels=1,
            samplerate=16000,
            blocksize=3200,
            callback=callback
        )
        stream.start()
        time.sleep(2)
        stream.stop()
        stream.close()

        if levels:
            avg = np.mean(levels)
            peak = np.max(levels)
            bar_count = int(peak * 500)
            bar = "#" * min(bar_count, 40)
            status = "SIGNAL DETECTED!" if peak > 0.005 else "NO SIGNAL"
            print(f"  Avg: {avg:.6f}  Peak: {peak:.6f}  [{bar}] {status}")
        else:
            print(f"  NO DATA CAPTURED")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()

print("Done. Use the device ID that shows SIGNAL DETECTED.")
