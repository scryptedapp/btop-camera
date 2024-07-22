import os
import sys
import tempfile

import psutil


PIDFILE_DIR = os.getenv("SCRYPTED_BTOP_PIDFILE_DIR") or os.path.join(tempfile.gettempdir(), ".scrypted_btop")


if __name__ == "__main__":
    proc_name = sys.argv[1].strip()

    pidfile = os.path.join(PIDFILE_DIR, f"{proc_name}.pid")
    try:
        with open(pidfile) as f:
            pid = int(f.read())
            p = psutil.Process(pid)
            for child in p.children(recursive=True):
                if child.name() == proc_name:
                    child.kill()
            p.kill()
    except:
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