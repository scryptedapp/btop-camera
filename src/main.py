import asyncio
import json
import os
import pathlib
import platform
import signal
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Tuple

import psutil

import scrypted_sdk
from scrypted_sdk import ScryptedDeviceBase, VideoCamera, ResponseMediaStreamOptions, Settings, Setting, ScryptedInterface, ScryptedMimeTypes


async def run_and_stream_output(cmd: str, env: Dict[str, str] = {}, return_pid: bool = False) -> Tuple[asyncio.Future, int] | None:
    p = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=dict(os.environ, **env))

    async def read_streams():
        async def stream_stdout():
            async for line in p.stdout:
                print(line.decode('utf-8'))
        async def stream_stderr():
            async for line in p.stderr:
                print(line.decode('utf-8'))

        await asyncio.gather(stream_stdout(), stream_stderr(), p.wait())

    if return_pid:
        return (asyncio.ensure_future(read_streams()), p.pid)
    await read_streams()


def multiprocess_main():
    cmd = sys.argv[1].strip()
    env = sys.argv[2].strip()
    kill_proc = sys.argv[3].strip()

    env = json.loads(env)
    if kill_proc == 'None':
        kill_proc = None

    parent = psutil.Process(os.getppid())

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    name = cmd.split()[0]
    print(f"{name} starting")
    sp = subprocess.Popen(cmd, shell=True, env=dict(os.environ, **env))

    with open(os.path.join(BtopCamera.FILES, f"{kill_proc}.pid"), 'w') as f:
        f.write(str(sp.pid))

    while parent.is_running():
        # check if the subprocess is still alive, if not then exit
        if sp.poll() is not None:
            break
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


async def run_self_cleanup_subprocess(cmd: str, env: Dict[str, str] = {}, kill_proc: str = None) -> None:
    exe = sys.executable
    args = [
        BtopCamera.THIS_FILE,
        cmd,
        json.dumps(env),
        kill_proc or 'None',
    ]

    p = await asyncio.create_subprocess_exec(exe, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)

    async def read_streams():
        async def stream_stdout():
            async for line in p.stdout:
                print(line.decode('utf-8'))
        async def stream_stderr():
            async for line in p.stderr:
                print(line.decode('utf-8'))

        await asyncio.gather(stream_stdout(), stream_stderr(), p.wait())

    await read_streams()


class BtopCamera(ScryptedDeviceBase, VideoCamera, Settings):
    FILES = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'files')
    XAUTH = os.path.join(FILES, 'Xauthority')
    PIDFILE = os.path.join(FILES, 'Xvfb.pid')
    FFMPEG_PIDFILE = os.path.join(FILES, 'ffmpeg.pid')
    XVFB_RUN = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'zip', 'unzipped', 'fs', 'xvfb-run')
    THIS_FILE = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'zip', 'unzipped', 'main.py')

    def __init__(self, nativeId: str = None) -> None:
        super().__init__(nativeId)

        self.dependencies_installed = asyncio.ensure_future(self.install_dependencies())
        self.stream_initialized = asyncio.ensure_future(self.init_stream())

    async def install_dependencies(self) -> None:
        try:
            installation = os.environ.get('SCRYPTED_INSTALL_ENVIRONMENT')
            if installation in ('docker', 'lxc'):
                await run_and_stream_output('apt-get update')
                await run_and_stream_output('apt-get install -y xvfb xterm btop xfonts-base')
            else:
                if platform.system() == 'Linux':
                    needed = []
                    if shutil.which('xvfb-run') is None:
                        needed.append('xvfb-run')
                    if shutil.which('xterm') is None:
                        needed.append('xterm')
                        needed.append('xfonts-base')
                    if shutil.which('btop') is None:
                        needed.append('btop')
                    if shutil.which('ffmpeg') is None:
                        needed.append('ffmpeg')

                    if needed:
                        needed.sort()
                        raise Exception(f"Please manually install the following and restart the plugin: {needed}")
                elif platform.system() == 'Darwin':
                    needed = []
                    if shutil.which('ffmpeg') is None:
                        needed.append('ffmpeg')
                    if shutil.which('bpytop') is None:
                        needed.append('bpytop')
                    if shutil.which('xterm') is None and not os.path.exists('/opt/X11/bin/xterm'):
                        needed.append('xquartz')
                    if not os.path.exists('/opt/homebrew/opt/gnu-getopt/bin/getopt'):
                        needed.append('gnu-getopt')

                    if needed:
                        needed.sort()
                        raise Exception(f"Please manually install the following and restart the plugin: {needed}")
                else:
                    raise Exception("This plugin only supports Linux and MacOS.")

            pid = self.read_pidfile()
            if pid:
                try:
                    xvfb_run_process = psutil.Process(pid)
                    for child in xvfb_run_process.children(recursive=True):
                        if child.name() == 'Xvfb':
                            child.kill()
                    xvfb_run_process.kill()
                except:
                    pass

            pid = self.read_ffmpeg_pidfile()
            if pid:
                try:
                    ffmpeg_process = psutil.Process(pid)
                    for child in ffmpeg_process.children(recursive=True):
                        if child.name() == 'ffmpeg':
                            child.kill()
                    ffmpeg_process.kill()
                except:
                    pass

            shutil.rmtree(BtopCamera.FILES, ignore_errors=True)
            pathlib.Path(BtopCamera.FILES).mkdir(parents=True, exist_ok=True)

            os.chmod(BtopCamera.XVFB_RUN, 0o755)
        except:
            import traceback
            traceback.print_exc()
            await asyncio.sleep(3600)
            os._exit(1)

    async def init_stream(self) -> None:
        await self.dependencies_installed

        async def run_stream():
            path = os.environ.get('PATH')
            exe = 'btop'
            if platform.system() == 'Darwin':
                path = f'/opt/X11/bin:/opt/homebrew/opt/gnu-getopt/bin:{path}'
                exe = 'bpytop'

            while True:
                #fut, pid = await run_and_stream_output(f'{BtopCamera.XVFB_RUN} -e /dev/stdout -n {self.virtual_display_num} -s "-screen 0 {self.display_dimensions}x24" -f {BtopCamera.XAUTH} xterm -en UTF-8 -maximized -e {exe}',
                #                                       env={'PATH': path, "LANG": "en_US.UTF-8"}, return_pid=True)
                await run_self_cleanup_subprocess(f'{BtopCamera.XVFB_RUN} -n {self.virtual_display_num} -s "-screen 0 {self.display_dimensions}x24" -f {BtopCamera.XAUTH} xterm -en UTF-8 -maximized -e {exe}',
                                                  env={'PATH': path, "LANG": "en_US.UTF-8"}, kill_proc='Xvfb')

                # write pid to file
                #with open(BtopCamera.PIDFILE, 'w') as f:
                #    f.write(str(pid))

                #await fut
                print("Xvfb crashed, restarting in 5s...")
                await asyncio.sleep(5)

        async def run_ffmpeg():
            await asyncio.sleep(5)
            while True:
                #fut, pid = await run_and_stream_output(f'ffmpeg -loglevel error -f x11grab -framerate 15 -draw_mouse 0 -i :{self.virtual_display_num} -c:v libx264 -pix_fmt yuvj420p -preset ultrafast -bf 0 -g 60 -an -dn -f flv -listen 1 rtmp://localhost:{self.rtmp_port}/stream',
                #                                       env={'XAUTHORITY': BtopCamera.XAUTH}, return_pid=True)
                await run_self_cleanup_subprocess(f'ffmpeg -loglevel error -f x11grab -framerate 15 -draw_mouse 0 -i :{self.virtual_display_num} -c:v libx264 -pix_fmt yuvj420p -preset ultrafast -bf 0 -g 60 -an -dn -f flv -listen 1 rtmp://localhost:{self.rtmp_port}/stream',
                                                  env={'XAUTHORITY': BtopCamera.XAUTH}, kill_proc='ffmpeg')

                # write pid to file
                #with open(BtopCamera.FFMPEG_PIDFILE, 'w') as f:
                #    f.write(str(pid))

                #await fut
                print("ffmpeg crashed, restarting in 5s...")
                await asyncio.sleep(5)

        asyncio.gather(run_stream(), run_ffmpeg())

    def read_pidfile(self) -> int:
        try:
            with open(BtopCamera.PIDFILE) as f:
                return int(f.read())
        except:
            return None

    def read_ffmpeg_pidfile(self) -> int:
        try:
            with open(BtopCamera.FFMPEG_PIDFILE) as f:
                return int(f.read())
        except:
            return None

    @property
    def virtual_display_num(self) -> int:
        if self.storage:
            return self.storage.getItem('virtual_display_num') or 99
        return 99

    @property
    def display_dimensions(self) -> int:
        if self.storage:
            return self.storage.getItem('display_dimensions') or '1024x720'
        return '1024x720'

    @property
    def rtmp_port(self) -> int:
        if self.storage:
            return self.storage.getItem('rtmp_port') or 4444
        return 4444

    async def getSettings(self) -> list[Setting]:
        return [
            {
                "key": "display_dimensions",
                "title": "Virtual Display Dimensions",
                "description": "The X11 virtual display dimensions to use. Format: WIDTHxHEIGHT.",
                "type": "string",
                "value": self.display_dimensions,
            },
            {
                "key": "virtual_display_num",
                "title": "Virtual Display Number",
                "description": "The X11 virtual display number to use.",
                "type": "number",
                "value": self.virtual_display_num,
            },
            {
                "key": "rtmp_port",
                "title": "RTMP Port",
                "description": "The RTMP server port to stream on.",
                "type": "number",
                "value": self.rtmp_port,
            },
        ]

    async def putSetting(self, key: str, value: str) -> None:
        self.storage.setItem(key, value)
        await self.onDeviceEvent(ScryptedInterface.Settings.value, None)
        print("Settings updated, will restart...")
        await scrypted_sdk.deviceManager.requestRestart()

    async def getVideoStreamOptions(self) -> list[ResponseMediaStreamOptions]:
        return [
            {
                "id": "default",
                "name": "Virtual Display",
                "container": "rtmp",
                "video": {
                    "codec": "h264",
                },
                "audio": None,
                "source": "local",
                "tool": "ffmpeg",
                "userConfigurable": False,
            }
        ]


    async def getVideoStream(self, options: scrypted_sdk.RequestMediaStreamOptions = None) -> scrypted_sdk.MediaObject:
        await self.stream_initialized
        return await scrypted_sdk.mediaManager.createMediaObject(str.encode(f'rtmp://localhost:{self.rtmp_port}/stream'), ScryptedMimeTypes.Url.value)


def create_scrypted_plugin():
    return BtopCamera()

if __name__ == "__main__":
    multiprocess_main()