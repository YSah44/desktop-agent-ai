import subprocess
import sys
import os

env = os.environ.copy()
env['PYTHONUNBUFFERED'] = '1'

proc = subprocess.Popen(
    [sys.executable, "-u", "main.py"],
    stdout=open("run_output.log", "w"),
    stderr=subprocess.STDOUT,
    cwd=r"C:\Users\Kabexnuf\desktop-agent",
    env=env
)
proc.wait()
print(f"Exit code: {proc.returncode}")
