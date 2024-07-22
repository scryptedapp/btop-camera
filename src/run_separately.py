import json
import os
import signal
import subprocess
import sys
import tempfile
import time

import psutil


PIDFILE_DIR = os.getenv("SCRYPTED_BTOP_PIDFILE_DIR") or os.path.join(tempfile.gettempdir(), ".scrypted_btop")
try:
    os.makedirs(PIDFILE_DIR, exist_ok=True)
except:
    pass


if __name__ == "__main__":
    cmd = sys.argv[1].strip()
    env = sys.argv[2].strip()
    kill_proc = sys.argv[3].strip()
    monitor_file = sys.argv[4].strip()

    env = json.loads(env)
    if kill_proc == 'None':
        kill_proc = None
    if monitor_file == 'None':
        monitor_file = None

    parent = psutil.Process(os.getppid())

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    name = cmd.split()[0]
    print(f"{name} starting")
    sp = subprocess.Popen(cmd, shell=True, env=dict(os.environ, **env))

    with open(os.path.join(PIDFILE_DIR, f"{kill_proc}.pid"), 'w') as f:
        f.write(str(sp.pid))

    monitor_not_found_count = 0
    while parent.is_running():
        # check if the subprocess is still alive, if not then exit
        if sp.poll() is not None:
            break
        if monitor_file:
            # check if the monitor file exists, if not then exit
            if not os.path.exists(monitor_file):
                monitor_not_found_count += 1
                if monitor_not_found_count > 3:
                    break
            else:
                monitor_not_found_count = 0
                try:
                    os.remove(monitor_file)
                except:
                    pass
        time.sleep(3)

    try:
        print(f"{name} exiting")
    except:
        # in case stdout was closed
        pass

    if kill_proc:
        try:
            p = psutil.Process(sp.pid)
            for child in p.children(recursive=True):
                if child.name() == kill_proc:
                    try:
                        child.kill()
                    except:
                        pass
            p.kill()
        except:
            pass

    sp.terminate()
    sp.wait()

    try:
        print(f"{name} exited")
    except:
        # in case stdout was closed
        pass
