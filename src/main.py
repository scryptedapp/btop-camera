import asyncio
import os
import pathlib
import platform
import shutil
from typing import Any, Callable, Dict, Tuple

import psutil

import scrypted_sdk
from scrypted_sdk import ScryptedDeviceBase, VideoCamera, ResponseMediaStreamOptions, Settings, Setting, ScryptedInterface, ScryptedMimeTypes


async def run_and_stream_output(cmd: str, env: Dict[str, str] = {}, on_stdout: Callable[[str], Any] = print, on_stderr: Callable[[str], Any] = print, return_pid: bool = False) -> Tuple[asyncio.Future, int] | None:
    p = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=dict(os.environ, **env))

    async def read_streams():
        async def stream_stdout():
            async for line in p.stdout:
                on_stdout(line.decode('utf-8'))
        async def stream_stderr():
            async for line in p.stderr:
                on_stderr(line.decode('utf-8'))

        await asyncio.gather(stream_stdout(), stream_stderr(), p.wait())

    if return_pid:
        return (asyncio.ensure_future(read_streams()), p.pid)
    await read_streams()


class BtopCamera(ScryptedDeviceBase, VideoCamera, Settings):
    FILES = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'files')
    XAUTH = os.path.join(FILES, 'Xauthority')
    PIDFILE = os.path.join(FILES, 'Xvfb.pid')

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
                if platform.system() != 'Linux':
                    raise Exception("This plugin is only supported on Linux.")

                needed = []
                if shutil.which('xvfb-run') is None:
                    needed.append('xvfb-run')
                if shutil.which('xterm') is None:
                    needed.append('xterm')
                    needed.append('xfonts-base')
                if shutil.which('btop') is None:
                    needed.append('btop')

                if needed:
                    needed.sort()
                    raise Exception(f"Please manually install the following and restart the plugin: {needed}")

            pid = self.read_pidfile()
            if pid:
                try:
                    xvfb_run_process = psutil.Process(pid)
                    for child in xvfb_run_process.children(recursive=True):
                        if child.name() == 'Xvfb':
                            child.terminate()
                except:
                    pass
                shutil.rmtree(BtopCamera.FILES, ignore_errors=True)

            pathlib.Path(BtopCamera.FILES).mkdir(parents=True, exist_ok=True)
        except:
            import traceback
            traceback.print_exc()
            os._exit(1)

    async def init_stream(self) -> None:
        await self.dependencies_installed

        ffmpeg = await scrypted_sdk.mediaManager.getFFmpegPath()

        async def run_stream():
            while True:
                fut, pid = await run_and_stream_output(f'xvfb-run -n {self.virtual_display_num} -s "-screen 0 {self.display_dimensions}x24" -f {BtopCamera.XAUTH} xterm -maximized -e btop', return_pid=True)

                # write pid to file
                with open(BtopCamera.PIDFILE, 'w') as f:
                    f.write(str(pid))

                await fut

        async def run_ffmpeg():
            while True:
                await run_and_stream_output(f'{ffmpeg} -loglevel error -f x11grab -framerate 15 -draw_mouse 0 -i :{self.virtual_display_num} -c:v libx264 -pix_fmt yuvj420p -preset ultrafast -bf 0 -g 60 -an -dn -f flv -listen 1 rtmp://localhost:{self.rtmp_port}/stream', env={'XAUTHORITY': BtopCamera.XAUTH})

        asyncio.gather(run_stream(), run_ffmpeg())

    def read_pidfile(self) -> int:
        try:
            with open(BtopCamera.PIDFILE) as f:
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