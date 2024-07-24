import os
import sys

import psutil


PIDFILE_DIR = os.getenv("SCRYPTED_BTOP_PIDFILE_DIR")


if __name__ == "__main__":
    proc_name = sys.argv[1].strip()

    pidfile = os.path.join(PIDFILE_DIR, f"{proc_name}.pid")
    try:
        with open(pidfile) as f:
            pid = int(f.read())
            p = psutil.Process(pid)
            for child in p.children(recursive=True):
                if child.name() == proc_name or child.name() == f"{proc_name}.exe":
                    child.kill()
            p.kill()
    except Exception as e:
        import traceback
        traceback.print_exc()
        pass
    finally:
        try:
            os.remove(pidfile)
        except:
            pass
        try:
            print(f"{proc_name} stopped")
        except:
            pass