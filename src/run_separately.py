import concurrent.futures
import json
import os
import platform
import signal
import subprocess
import sys
import time
import threading

import psutil


PIDFILE_DIR = os.getenv("SCRYPTED_BTOP_PIDFILE_DIR")
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
    else:
        if kill_proc:
            monitor_file = f'{monitor_file}.{kill_proc}'

    print("Running", cmd)

    parent = psutil.Process(os.getppid())

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    name = kill_proc or cmd.split()[0]

    print(f"{name} starting")
    done = concurrent.futures.Future()
    def run():
        try:
            subprocess.Popen(cmd, env=dict(os.environ, **env), shell=platform.system() != "Windows").communicate()
        except:
            pass
        finally:
            done.set_result(None)
    threading.Thread(target=run).start()

    me = psutil.Process()
    sp = None
    monitor_not_found_count = 0
    while sp is None:
        for child in me.children(recursive=True):
            try:
                if done.done() or child.name() == name or child.name() == f"{name}.exe":
                    sp = child
                    break
            except:
                pass
        if monitor_file:
            if not os.path.exists(monitor_file):
                monitor_not_found_count += 1
                if monitor_not_found_count > 100:
                    sys.exit(0)
            else:
                monitor_not_found_count = 0
                try:
                    os.remove(monitor_file)
                except:
                    pass
        time.sleep(0.1)

    with open(os.path.join(PIDFILE_DIR, f"{kill_proc}.pid"), 'w') as f:
        f.write(str(sp.pid))

    monitor_not_found_count = 0
    while parent.is_running():
        # check if the subprocess is still alive, if not then exit
        if done.done():
            try:
                print(f"{name} exited by itself")
                print(sp)
            except:
                # in case stdout was closed
                pass
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
                if child.name() == kill_proc or child.name() == f"{kill_proc}.exe":
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
