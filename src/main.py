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
from typing import Any, Dict, Tuple
import urllib.request

import psutil

import scrypted_sdk
from scrypted_sdk import ScryptedDeviceBase, VideoCamera, ResponseMediaStreamOptions, RequestMediaStreamOptions, Settings, Setting, ScryptedInterface, ScryptedDeviceType, ScryptedMimeTypes, DeviceProvider, Scriptable, ScriptSource, Readme

import btop_config


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


class BtopCamera(ScryptedDeviceBase, VideoCamera, Settings, DeviceProvider):
    FILES = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'files')
    XAUTH = os.path.join(FILES, 'Xauthority')
    PIDFILE = os.path.join(FILES, 'Xvfb.pid')
    FFMPEG_PIDFILE = os.path.join(FILES, 'ffmpeg.pid')
    XVFB_RUN = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'zip', 'unzipped', 'fs', 'xvfb-run')
    THIS_FILE = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'zip', 'unzipped', 'main.py')

    def __init__(self, nativeId: str = None) -> None:
        super().__init__(nativeId)

        self.btop_config = None
        self.fontmanager = None
        self.thememanager = None
        self.fonts_cache = None
        self.dependencies_installed = asyncio.ensure_future(self.install_dependencies())
        self.stream_initialized = asyncio.ensure_future(self.init_stream())

    async def install_dependencies(self) -> None:
        try:
            installation = os.environ.get('SCRYPTED_INSTALL_ENVIRONMENT')
            if installation in ('docker', 'lxc'):
                await run_and_stream_output('apt-get update')
                await run_and_stream_output('apt-get install -y xvfb xterm btop xfonts-base fontconfig')
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

                    if not self.fonts_supported:
                        print("Warning: fc-list not found. Changing fonts will not be enabled.")

                    if needed:
                        needed.sort()
                        raise Exception(f"Please manually install the following and restart the plugin: {needed}")
                elif platform.system() == 'Darwin':
                    needed = []
                    if shutil.which('ffmpeg') is None:
                        needed.append('ffmpeg')
                    if shutil.which('btop') is None:
                        needed.append('btop')
                    if shutil.which('xterm') is None and not os.path.exists('/opt/X11/bin/xterm'):
                        needed.append('xquartz')
                    if not os.path.exists('/opt/homebrew/opt/gnu-getopt/bin/getopt') and \
                        not os.path.exists('/usr/local/opt/gnu-getopt/bin/getopt'):
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

            pathlib.Path(BtopCamera.XAUTH).unlink(missing_ok=True)
            pathlib.Path(BtopCamera.PIDFILE).unlink(missing_ok=True)
            pathlib.Path(BtopCamera.FFMPEG_PIDFILE).unlink(missing_ok=True)
            pathlib.Path(BtopCamera.FILES).mkdir(parents=True, exist_ok=True)

            os.chmod(BtopCamera.XVFB_RUN, 0o755)

            await scrypted_sdk.deviceManager.onDeviceDiscovered({
                "nativeId": "config",
                "name": "btop Configuration",
                "type": ScryptedDeviceType.API.value,
                "interfaces": [
                    ScryptedInterface.Scriptable.value,
                    ScryptedInterface.Readme.value,
                ],
            })
            await scrypted_sdk.deviceManager.onDeviceDiscovered({
                "nativeId": "thememanager",
                "name": "Theme Manager",
                "type": ScryptedDeviceType.API.value,
                "interfaces": [
                    ScryptedInterface.Settings.value,
                    ScryptedInterface.Readme.value,
                ],
            })
            if self.fonts_supported:
                await scrypted_sdk.deviceManager.onDeviceDiscovered({
                    "nativeId": "fontmanager",
                    "name": "Font Manager",
                    "type": ScryptedDeviceType.API.value,
                    "interfaces": [
                        ScryptedInterface.Settings.value,
                        ScryptedInterface.Readme.value,
                    ],
                })
        except:
            import traceback
            traceback.print_exc()
            await asyncio.sleep(3600)
            os._exit(1)

    async def init_stream(self) -> None:
        await self.dependencies_installed

        config = await self.getDevice('config')
        await config.config_reconciled

        if self.fonts_supported:
            fontmanager = await self.getDevice('fontmanager')
            await fontmanager.fonts_loaded

        async def run_stream():
            path = os.environ.get('PATH')
            exe = 'btop'
            if platform.system() == 'Darwin':
                path = f'/opt/X11/bin:/opt/homebrew/opt/gnu-getopt/bin:/usr/local/opt/gnu-getopt/bin:{path}'

            fontselection = ''
            if self.fonts_supported:
                font = self.xterm_font
                if font != 'Default':
                    fontselection = f'-fa "{font}"'

            while True:
                await run_self_cleanup_subprocess(f'{BtopCamera.XVFB_RUN} -n {self.virtual_display_num} -s "-screen 0 {self.display_dimensions}x24" -f {BtopCamera.XAUTH} xterm {fontselection} -en UTF-8 -maximized -e {exe} -p {self.btop_preset}',
                                                  env={'PATH': path, "LANG": "en_US.UTF-8"}, kill_proc='Xvfb')

                print("Xvfb crashed, restarting in 5s...")
                await asyncio.sleep(5)

        asyncio.create_task(run_stream())

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
    def btop_preset(self) -> int:
        if self.storage:
            return self.storage.getItem('btop_preset') or 0
        return 0

    @property
    def xterm_font(self) -> str:
        """For best results, ensure that BtopFontManager.fonts_loaded is awaited before calling this property."""
        if self.storage:
            font = self.storage.getItem('xterm_font') or 'Default'
            if font not in self.list_fonts():
                return 'Default'
            return font
        return 'Default'

    @property
    def fonts_supported(self) -> bool:
        installation = os.environ.get('SCRYPTED_INSTALL_ENVIRONMENT')
        if installation in ('docker', 'lxc'):
            return True
        if platform.system() == 'Linux':
            return shutil.which('fc-list') is not None
        if platform.system() == 'Darwin':
            return os.path.exists('/opt/X11/bin/fc-list')
        return False

    def list_fonts(self) -> list[str]:
        """For best results, ensure that BtopFontManager.fonts_loaded is awaited before calling this function."""
        if not self.fonts_supported:
            return []

        if self.fonts_cache is not None:
            return self.fonts_cache

        fonts = []
        fc_list = 'fc-list' if platform.system() == 'Linux' else '/opt/X11/bin/fc-list'
        try:
            # list font families with fc-list
            p = subprocess.Popen([fc_list, ':', 'family'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate(timeout=10)
            if p.returncode == 0:
                for line in out.decode().splitlines():
                    font = line.strip()
                    if font:
                        fonts.append(font)
        except:
            print("Could not enumerate fonts with fc-list")
            pass
        fonts.sort()
        fonts = ['Default'] + fonts
        self.fonts_cache = fonts
        return fonts

    async def getSettings(self) -> list[Setting]:
        settings = [
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
                "key": "btop_preset",
                "title": "btop Preset",
                "description": "The btop preset number to launch. Modify presets in the btop configuration page.",
                "type": "number",
                "value": self.btop_preset,
            },
        ]

        if self.fonts_supported:
            fontmanager = await self.getDevice('fontmanager')
            await fontmanager.fonts_loaded
            settings.append({
                "key": "xterm_font",
                "title": "Xterm Font",
                "description": "The Xterm font to use. Monospace fonts are recommended. Download additional fonts in the font manager page.",
                "type": "string",
                "value": self.xterm_font,
                "choices": self.list_fonts(),
            })

        return settings

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
                "container": "x11grab",
                "video": {
                    "codec": "rawvideo",
                },
                "audio": None,
                "source": "local",
                "tool": "ffmpeg",
                "userConfigurable": False,
            }
        ]

    async def getVideoStream(self, options: RequestMediaStreamOptions = None) -> scrypted_sdk.MediaObject:
        await self.stream_initialized

        ffmpeg_input = {
            "inputArguments": [
                "-f", "x11grab",
                "-framerate", "15",
                "-draw_mouse", "0",
                "-i", f":{self.virtual_display_num}",
            ],
            "env": {
                "XAUTHORITY": BtopCamera.XAUTH,
            },
            "h264EncoderArguments": [
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-bf", "0",
                "-r", "15",
                "-g", "60",
            ]
        }
        return await scrypted_sdk.mediaManager.createFFmpegMediaObject(ffmpeg_input)

    async def getDevice(self, nativeId: str) -> Any:
        if nativeId == 'config':
            if not self.btop_config:
                self.btop_config = BtopConfig(nativeId, self)
            return self.btop_config
        elif nativeId == 'fontmanager':
            if not self.fontmanager:
                self.fontmanager = BtopFontManager(nativeId)
            return self.fontmanager
        elif nativeId == 'thememanager':
            if not self.thememanager:
                self.thememanager = BtopThemeManager(nativeId)
            return self.thememanager
        return None


class BtopConfig(ScryptedDeviceBase, Scriptable, Readme):
    DEFAULT_CONFIG = btop_config.BTOP_CONFIG
    CONFIG = os.path.expanduser(f'~/.config/btop/btop.conf')
    HOME_THEMES_DIR = os.path.expanduser(f'~/.config/btop/themes')

    def __init__(self, nativeId: str, parent: BtopCamera) -> None:
        super().__init__(nativeId)
        self.parent = parent
        self.config_reconciled = asyncio.ensure_future(self.reconcile_from_disk())
        self.themes = []

    async def reconcile_from_disk(self) -> None:
        await self.parent.dependencies_installed

        thememanager = await self.parent.getDevice('thememanager')
        await thememanager.themes_loaded

        try:
            if not os.path.exists(BtopConfig.CONFIG):
                os.makedirs(os.path.dirname(BtopConfig.CONFIG), exist_ok=True)
                with open(BtopConfig.CONFIG, 'w') as f:
                    f.write(BtopConfig.DEFAULT_CONFIG)
            self.print(f"Using config file: {BtopConfig.CONFIG}")

            with open(BtopConfig.CONFIG) as f:
                data = f.read()

            if self.storage.getItem('config') and data != self.config:
                with open(BtopConfig.CONFIG, 'w') as f:
                    f.write(self.config)

            if not self.storage.getItem('config'):
                self.storage.setItem('config', data)

            btop = shutil.which('btop')
            assert btop is not None

            bin_dir = os.path.dirname(btop)
            config_dir = os.path.realpath(os.path.join(os.path.dirname(bin_dir), 'share', 'btop', 'themes'))
            self.print(f"Using themes dir: {config_dir}, {BtopConfig.HOME_THEMES_DIR}")
            if os.path.exists(config_dir):
                self.themes = [
                    theme.removesuffix('.theme')
                    for theme in os.listdir(config_dir)
                    if theme.endswith('.theme')
                ]
            if os.path.exists(BtopConfig.HOME_THEMES_DIR):
                self.themes.extend([
                    theme.removesuffix('.theme')
                    for theme in os.listdir(BtopConfig.HOME_THEMES_DIR)
                    if theme.endswith('.theme')
                ])
            self.themes.sort()

            await self.onDeviceEvent(ScryptedInterface.Readme.value, None)
            await self.onDeviceEvent(ScryptedInterface.Scriptable.value, None)
        except:
            import traceback
            traceback.print_exc()

    @property
    def config(self) -> str:
        if self.storage:
            return self.storage.getItem('config') or BtopConfig.DEFAULT_CONFIG
        return BtopConfig.DEFAULT_CONFIG

    async def eval(self, source: ScriptSource, variables: Any = None) -> Any:
        raise Exception("btop configuration cannot be evaluated")

    async def loadScripts(self) -> Any:
        await self.config_reconciled

        return {
            "btop.conf": {
                "name": "btop Configuration",
                "script": self.config,
                "language": "ini",
            }
        }

    async def saveScript(self, script: ScriptSource) -> None:
        await self.config_reconciled

        self.storage.setItem('config', script['script'])
        await self.onDeviceEvent(ScryptedInterface.Scriptable.value, None)

        updated = False
        with open(BtopConfig.CONFIG) as f:
            if f.read() != script['script']:
                updated = True

        if updated:
            if not script['script']:
                os.remove(BtopConfig.CONFIG)
            else:
                with open(BtopConfig.CONFIG, 'w') as f:
                    f.write(script['script'])

            self.print("Configuration updated, will restart...")
            await scrypted_sdk.deviceManager.requestRestart()

    async def getReadmeMarkdown(self) -> str:
        await self.config_reconciled
        return f"""
# `btop` Configuration

Saving the configuration will trigger a full plugin restart to ensure the stream loads the new configuration. Additional themes can be downloaded from the theme manager page.

Available themes:
{'\n'.join(['- ' + theme for theme in self.themes])}
"""


class DownloaderBase(ScryptedDeviceBase):
    def __init__(self, nativeId: str | None = None):
        super().__init__(nativeId)

    def downloadFile(self, url: str, filename: str):
        try:
            filesPath = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'files')
            fullpath = os.path.join(filesPath, filename)
            if os.path.isfile(fullpath):
                return fullpath
            tmp = fullpath + '.tmp'
            self.print("Creating directory for", tmp)
            os.makedirs(os.path.dirname(fullpath), exist_ok=True)
            self.print("Downloading", url)
            response = urllib.request.urlopen(url)
            if response.getcode() < 200 or response.getcode() >= 300:
                raise Exception(f"Error downloading")
            read = 0
            with open(tmp, "wb") as f:
                while True:
                    data = response.read(1024 * 1024)
                    if not data:
                        break
                    read += len(data)
                    self.print("Downloaded", read, "bytes")
                    f.write(data)
            os.rename(tmp, fullpath)
            return fullpath
        except:
            self.print("Error downloading", url)
            import traceback
            traceback.print_exc()
            raise


class BtopFontManager(DownloaderBase, Settings, Readme):
    FONT_DIR_PATTERN = '~/.local/share/fonts' if platform.system() == 'Linux' else '~/.fonts'
    LOCAL_FONT_DIR = os.path.expanduser(FONT_DIR_PATTERN)

    def __init__(self, nativeId: str | None = None):
        super().__init__(nativeId)
        self.fonts_loaded = asyncio.ensure_future(self.load_fonts())

    async def load_fonts(self) -> None:
        os.makedirs(BtopFontManager.LOCAL_FONT_DIR, exist_ok=True)
        try:
            urls = self.font_urls
            for url in urls:
                filename = url.split('/')[-1]
                fullpath = self.downloadFile(url, filename)
                target = os.path.join(BtopFontManager.LOCAL_FONT_DIR, filename)
                shutil.copyfile(fullpath, target)
                self.print("Installed", target)
        except:
            import traceback
            traceback.print_exc()

    @property
    def font_urls(self) -> list[str]:
        if self.storage:
            urls = self.storage.getItem('font_urls')
            if urls:
                return json.loads(urls)
        return []

    async def getSettings(self) -> list[Setting]:
        return [
            {
                "key": "font_urls",
                "title": "Font URLs",
                "description": f"List of URLs to download fonts from. Fonts will be downloaded to {BtopFontManager.FONT_DIR_PATTERN}.",
                "value": self.font_urls,
                "multiple": True,
            },
        ]

    async def putSetting(self, key: str, value: str) -> None:
        self.storage.setItem(key, json.dumps(value))
        await self.onDeviceEvent(ScryptedInterface.Settings.value, None)
        await scrypted_sdk.deviceManager.requestRestart()

    async def getReadmeMarkdown(self) -> str:
        return f"""
# Font Manager

List fonts to download and install in the local font directory. Fonts will be installed to `{BtopFontManager.FONT_DIR_PATTERN}`.
"""


class BtopThemeManager(DownloaderBase, Settings, Readme):
    LOCAL_THEME_DIR = os.path.expanduser(f'~/.config/btop/themes')

    def __init__(self, nativeId: str | None = None):
        super().__init__(nativeId)
        self.themes_loaded = asyncio.ensure_future(self.load_themes())

    async def load_themes(self) -> None:
        os.makedirs(BtopThemeManager.LOCAL_THEME_DIR, exist_ok=True)
        try:
            urls = self.theme_urls
            for url in urls:
                filename = url.split('/')[-1]
                fullpath = self.downloadFile(url, filename)
                target = os.path.join(BtopThemeManager.LOCAL_THEME_DIR, filename)
                shutil.copyfile(fullpath, target)
                self.print("Installed", target)
        except:
            import traceback
            traceback.print_exc()

    @property
    def theme_urls(self) -> list[str]:
        if self.storage:
            urls = self.storage.getItem('theme_urls')
            if urls:
                return json.loads(urls)
        return []

    async def getSettings(self) -> list[Setting]:
        return [
            {
                "key": "theme_urls",
                "title": "Theme URLs",
                "description": "List of URLs to download themes from. Themes will be downloaded to ~/.config/btop/themes.",
                "value": self.theme_urls,
                "multiple": True,
            },
        ]

    async def putSetting(self, key: str, value: str) -> None:
        self.storage.setItem(key, json.dumps(value))
        await self.onDeviceEvent(ScryptedInterface.Settings.value, None)
        await scrypted_sdk.deviceManager.requestRestart()

    async def getReadmeMarkdown(self) -> str:
        return """
# Theme Manager

List themes to download and install in the local theme directory. Themes will be installed to `~/.config/btop/themes`.
"""


def create_scrypted_plugin():
    return BtopCamera()

if __name__ == "__main__":
    multiprocess_main()