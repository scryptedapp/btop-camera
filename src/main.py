import asyncio
import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import types
from typing import Any, Dict, Tuple
import urllib.request

import scrypted_sdk
from scrypted_sdk import ScryptedDeviceBase, VideoCamera, ResponseMediaStreamOptions, RequestMediaStreamOptions, Settings, Setting, ScryptedInterface, ScryptedDeviceType, ScryptedMimeTypes, DeviceProvider, Scriptable, ScriptSource, Readme

import btop_config


# patch SystemManager.getDeviceByName
def getDeviceByName(self, name: str) -> scrypted_sdk.ScryptedDevice:
    for check in self.systemState:
        state = self.systemState.get(check, None)
        if not state:
            continue
        checkInterfaces = state.get('interfaces', None)
        if not checkInterfaces:
            continue
        interfaces = checkInterfaces.get('value', [])
        if ScryptedInterface.ScryptedPlugin.value in interfaces:
            checkPluginId = state.get('pluginId', None)
            if not checkPluginId:
                continue
            pluginId = checkPluginId.get('value', None)
            if not pluginId:
                continue
            if pluginId == name:
                return self.getDeviceById(check)
        checkName = state.get('name', None)
        if not checkName:
            continue
        if checkName.get('value', None) == name:
            return self.getDeviceById(check)
scrypted_sdk.systemManager.getDeviceByName = types.MethodType(getDeviceByName, scrypted_sdk.systemManager)


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


async def run_self_cleanup_subprocess(cmd: str, env: Dict[str, str] = {}, kill_proc: str = None) -> None:
    """Launch an instance of Python which monitors the subprocess and kills it if the parent process dies."""
    exe = sys.executable

    if platform.system() == 'Windows':
        cmd = f"\"{BtopCamera.CYGWIN_LAUNCHER}\" \"{cmd}\""

    args = [
        BtopCamera.RUN_SEPARATELY_SCRIPT,
        cmd,
        json.dumps(env),
        kill_proc or 'None',
        BtopCamera.MONITOR_FILE if platform.system() == 'Windows' else 'None'
    ]

    script_env = os.environ.copy()
    script_env['SCRYPTED_BTOP_PIDFILE_DIR'] = BtopCamera.VOLUME_FILES
    p = await asyncio.create_subprocess_exec(exe, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True, env=script_env)

    async def read_streams():
        async def stream_stdout():
            async for line in p.stdout:
                print(line.decode('utf-8'))
        async def stream_stderr():
            async for line in p.stderr:
                print(line.decode('utf-8'))

        await asyncio.gather(stream_stdout(), stream_stderr(), p.wait())

    await read_streams()


async def run_cleanup_subprocess(kill_proc: str) -> None:
    """Launches an instance of Python to clean up dangling processes from a previous plugin instance."""
    exe = sys.executable
    args = [
        BtopCamera.CLEANUP_SEPARATELY_SCRIPT,
        kill_proc,
    ]

    script_env = os.environ.copy()
    script_env['SCRYPTED_BTOP_PIDFILE_DIR'] = BtopCamera.VOLUME_FILES
    p = await asyncio.create_subprocess_exec(exe, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True, env=script_env)

    async def read_streams():
        async def stream_stdout():
            async for line in p.stdout:
                print(line.decode('utf-8'))
        async def stream_stderr():
            async for line in p.stderr:
                print(line.decode('utf-8'))

        await asyncio.gather(stream_stdout(), stream_stderr(), p.wait())

    await read_streams()


def copy_file_to(path: str, dest: str, make_executable: bool = False) -> None:
    if platform.system() != "Windows":
        shutil.copyfile(path, dest)
        if make_executable:
            os.chmod(dest, 0o755)
    else:
        # read file
        with open(path, 'rb') as f:
            data = f.read()

        # launch tee as subprocess
        subprocess.Popen(f'"{BtopCamera.CYGWIN_LAUNCHER}" "tee {dest}"', stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True).communicate(data)

        if make_executable:
            # make executable
            subprocess.Popen(f'"{BtopCamera.CYGWIN_LAUNCHER}" "chmod 755 {dest}"', shell=True).communicate()


class BtopCamera(ScryptedDeviceBase, VideoCamera, Settings, DeviceProvider):
    VOLUME_FILES = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'files')
    CYGWIN_INSTALL_DONE = os.path.join(VOLUME_FILES, 'cygwin_install_done')
    CYGWIN_PORTABLE_INSTALLER = os.path.join(VOLUME_FILES, 'cygwin-portable-installer.cmd')
    CYGWIN_LAUNCHER = os.path.join(VOLUME_FILES, 'cygwin-portable.cmd')
    MONITOR_FILE = os.path.join(VOLUME_FILES, f"monitor.{os.getpid()}")

    FILES = "/tmp/.scrypted_btop" if platform.system() == "Windows" else VOLUME_FILES
    XAUTH = f"{FILES}/Xauthority"
    XVFB_RUN = f"{FILES}/xvfb-run"

    FFMPEG_IN_CYGWIN = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'zip', 'unzipped', 'fs', 'ffmpeg_in_cygwin.com')
    CYGWIN_PORTABLE_INSTALLER_SRC = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'zip', 'unzipped', 'fs', 'cygwin-portable-installer.cmd')
    XVFB_RUN_SRC = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'zip', 'unzipped', 'fs', 'xvfb-run')
    RUN_SEPARATELY_SCRIPT = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'zip', 'unzipped', 'run_separately.py')
    CLEANUP_SEPARATELY_SCRIPT = os.path.join(os.environ['SCRYPTED_PLUGIN_VOLUME'], 'zip', 'unzipped', 'cleanup_separately.py')

    def __init__(self, nativeId: str = None) -> None:
        super().__init__(nativeId)

        self.btop = asyncio.ensure_future(self.load_btop_exe())
        self.btop_config = None
        self.fontmanager = None
        self.thememanager = None
        self.fonts_cache = None
        self.dependencies_installed = asyncio.ensure_future(self.install_dependencies())
        self.stream_initialized = asyncio.ensure_future(self.init_stream())
        self.cygwin_ffmpeg = asyncio.ensure_future(self.get_cygwin_ffmpeg())

    async def load_btop_exe(self) -> str:
        try:
            btop_plugin = scrypted_sdk.systemManager.getDeviceByName('@scrypted/btop')
            if not btop_plugin:
                raise Exception("Please install the @scrypted/btop plugin.")
            btop = await btop_plugin.getDevice("btop-executable")
            if type(btop) == str:
                return btop
            else:
                settings = await btop_plugin.getSettings()
                for setting in settings:
                    if setting['key'] == 'btop_executable':
                        return setting['value']
        except:
            import traceback
            traceback.print_exc()
            await scrypted_sdk.deviceManager.requestRestart()
            await asyncio.sleep(3600)

    async def install_dependencies(self) -> None:
        try:
            btop = await self.btop
            print("Using btop executable:", btop)

            installation = os.environ.get('SCRYPTED_INSTALL_ENVIRONMENT')
            if installation in ('docker', 'lxc'):
                await run_and_stream_output('apt-get update')
                await run_and_stream_output('apt-get install -y xvfb xterm xfonts-base fontconfig')
            elif platform.system() == 'Windows':
                os.makedirs(BtopCamera.VOLUME_FILES, exist_ok=True)
                shutil.copyfile(BtopCamera.CYGWIN_PORTABLE_INSTALLER_SRC, BtopCamera.CYGWIN_PORTABLE_INSTALLER)

                with open(BtopCamera.CYGWIN_PORTABLE_INSTALLER, 'r') as f:
                    data = f.read()
                installer_md5 = hashlib.md5(data.encode()).hexdigest()
                needs_install = True
                try:
                    with open(BtopCamera.CYGWIN_INSTALL_DONE, 'r') as f:
                        if f.read() == installer_md5:
                            needs_install = False
                except:
                    pass

                if needs_install:
                    await run_and_stream_output(f'"{BtopCamera.CYGWIN_PORTABLE_INSTALLER}"')
                    with open(BtopCamera.CYGWIN_INSTALL_DONE, 'w') as f:
                        f.write(installer_md5)
            else:
                if platform.system() == 'Linux':
                    needed = []
                    if shutil.which('Xvfb') is None:
                        needed.append('xvfb')
                    if shutil.which('xterm') is None:
                        needed.append('xterm')
                        needed.append('xfonts-base')

                    if not self.fonts_supported:
                        print("Warning: fc-list not found. Changing fonts will not be enabled.")

                    if needed:
                        needed.sort()
                        raise Exception(f"Please manually install the following and restart the plugin: {needed}")
                elif platform.system() == 'Darwin':
                    needed = []
                    if not os.path.exists('/usr/local/bin/ffmpeg') and \
                        not os.path.exists('/opt/homebrew/bin/ffmpeg'):
                        needed.append('ffmpeg')
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

            try:
                await run_cleanup_subprocess('Xvfb')
            except:
                import traceback
                traceback.print_exc()
                pass
            try:
                await run_cleanup_subprocess('ffmpeg')
            except:
                pass
            if platform.system() == "Windows":
                try:
                    await run_cleanup_subprocess('cygserver')
                except:
                    pass

            if platform.system() != "Windows":
                pathlib.Path(BtopCamera.XAUTH).unlink(missing_ok=True)
                pathlib.Path(BtopCamera.FILES).mkdir(parents=True, exist_ok=True)
            else:
                subprocess.Popen(f'"{BtopCamera.CYGWIN_LAUNCHER}" "rm -rf {BtopCamera.FILES}"', shell=True).communicate()
                subprocess.Popen(f'"{BtopCamera.CYGWIN_LAUNCHER}" "mkdir -p {BtopCamera.FILES}"', shell=True).communicate()
            copy_file_to(BtopCamera.XVFB_RUN_SRC, BtopCamera.XVFB_RUN, make_executable=True)

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

            if platform.system() == "Windows":
                # clean up old monitors
                try:
                    for file in os.listdir(BtopCamera.VOLUME_FILES):
                        if file.startswith('monitor.'):
                            os.remove(os.path.join(BtopCamera.VOLUME_FILES, file))
                except:
                    pass

                async def periodic_monitor(proc):
                    while True:
                        try:
                            with open(BtopCamera.MONITOR_FILE+f".{proc}", 'w') as f:
                                f.write('')
                        except:
                            pass
                        await asyncio.sleep(3)
                asyncio.create_task(periodic_monitor('Xvfb'))
                asyncio.create_task(periodic_monitor('cygserver'))
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

        async def run_cygserver():
            await run_and_stream_output(f'"{BtopCamera.CYGWIN_LAUNCHER}" "cygserver-config -n"')
            while True:
                await run_self_cleanup_subprocess('/usr/sbin/cygserver', kill_proc='cygserver')
                print("cygserver crashed, restarting in 5s...")
                await asyncio.sleep(5)

        async def run_stream():
            await asyncio.sleep(3)

            exe = await self.btop
            env = {
                "LANG": "en_US.UTF-8",
            }
            xterm_tweaks = ""

            if not exe:
                raise Exception("btop executable not found, cannot start stream.")

            if platform.system() == "Windows":
                exe = subprocess.check_output([BtopCamera.CYGWIN_LAUNCHER, f"cygpath '{exe}'"]).decode().strip()
                exe = f"'{exe}'"
                xterm_tweaks = f"+tb +sb -fullscreen -geometry {self.display_dimensions}"

            if platform.system() == 'Darwin':
                path = os.environ.get('PATH')
                path = f'/opt/X11/bin:/opt/homebrew/opt/gnu-getopt/bin:/usr/local/opt/gnu-getopt/bin:{path}'
                env['PATH'] = path

            fontselection = ''
            if self.fonts_supported:
                font = self.xterm_font
                if font != 'Default':
                    fontselection = f'-fa \'{font}\''

            while True:
                await run_self_cleanup_subprocess(f'{BtopCamera.XVFB_RUN} -n {self.virtual_display_num} -s \'-screen 0 {self.display_dimensions}x24\' -f {BtopCamera.XAUTH} xterm {xterm_tweaks} {fontselection} -en UTF-8 -maximized -e {exe} -p {self.btop_preset}',
                                                  env=env, kill_proc='Xvfb')

                print("Xvfb crashed, restarting in 5s...")
                await asyncio.sleep(5)

        if platform.system() == "Windows":
            asyncio.create_task(run_cygserver())
        asyncio.create_task(run_stream())

    @property
    def virtual_display_num(self) -> int:
        if self.storage:
            return self.storage.getItem('virtual_display_num') or 99
        return 99

    @property
    def display_dimensions(self) -> str:
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
        if platform.system() == 'Windows':
            try:
                subprocess.check_output([BtopCamera.CYGWIN_LAUNCHER, "which fc-list"]).decode().strip()
                return True
            except:
                pass
        return False

    def list_fonts(self) -> list[str]:
        """For best results, ensure that BtopFontManager.fonts_loaded is awaited before calling this function."""
        if not self.fonts_supported:
            return []

        if self.fonts_cache is not None:
            return self.fonts_cache

        fonts = []
        fc_list_cmd = [BtopCamera.CYGWIN_LAUNCHER, 'fc-list : family'] if platform.system() == 'Windows' else \
            ['fc-list' if platform.system() == 'Linux' else '/opt/X11/bin/fc-list', ':', 'family']
        try:
            # list font families with fc-list
            out = subprocess.check_output(fc_list_cmd).decode().strip()
            for line in out.splitlines():
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
                "source": "synthetic",
                "tool": "ffmpeg",
                "userConfigurable": False,
            }
        ]

    async def get_cygwin_ffmpeg(self) -> str:
        assert platform.system() == 'Windows'
        await self.dependencies_installed
        return subprocess.check_output([BtopCamera.CYGWIN_LAUNCHER, "cygpath -w $(which ffmpeg)"]).decode().strip()

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
                "-c:v", "libx264" if platform.system() != "Windows" else "libopenh264",
                "-preset", "ultrafast",
                "-bf", "0",
                "-r", "15",
                "-g", "60",
            ]
        }

        if platform.system() == 'Darwin':
            if os.path.exists('/opt/homebrew/bin/ffmpeg'):
                ffmpeg_input['ffmpegPath'] = '/opt/homebrew/bin/ffmpeg'
            elif os.path.exists('/usr/local/bin/ffmpeg'):
                ffmpeg_input['ffmpegPath'] = '/usr/local/bin/ffmpeg'
        elif platform.system() == 'Windows':
            ffmpeg_input['ffmpegPath'] = await self.cygwin_ffmpeg

        return await scrypted_sdk.mediaManager.createFFmpegMediaObject(ffmpeg_input)

    async def getDevice(self, nativeId: str) -> Any:
        if nativeId == 'config':
            if not self.btop_config:
                self.btop_config = BtopConfig(nativeId, self)
            return self.btop_config
        elif nativeId == 'fontmanager':
            if not self.fontmanager:
                self.fontmanager = BtopFontManager(nativeId, self)
            return self.fontmanager
        elif nativeId == 'thememanager':
            if not self.thememanager:
                self.thememanager = BtopThemeManager(nativeId, self)
            return self.thememanager
        return None


class BtopConfig(ScryptedDeviceBase, Scriptable, Readme):
    DEFAULT_CONFIG = btop_config.BTOP_CONFIG
    CONFIG = os.path.expanduser(f'~/.config/btop/btop.conf')
    HOME_THEMES_DIR = os.path.expanduser(f'~/.config/btop/themes')

    def __init__(self, nativeId: str, parent: BtopCamera) -> None:
        super().__init__(nativeId)
        self.parent = parent
        self.config_path = asyncio.ensure_future(self.find_config())
        self.config_reconciled = asyncio.ensure_future(self.reconcile_from_disk())
        self.themes = []

    async def find_config(self) -> str:
        btop = await self.parent.btop
        assert btop is not None

        bin_dir = os.path.dirname(btop)
        if platform.system() == 'Windows':
            return os.path.join(bin_dir, 'btop.conf')
        else:
            return BtopConfig.CONFIG

    async def reconcile_from_disk(self) -> None:
        await self.parent.dependencies_installed

        thememanager = await self.parent.getDevice('thememanager')
        await thememanager.themes_loaded

        try:
            btop = await self.parent.btop
            assert btop is not None

            config = await self.config_path

            if not os.path.exists(config):
                os.makedirs(os.path.dirname(config), exist_ok=True)
                with open(config, 'w') as f:
                    f.write(BtopConfig.DEFAULT_CONFIG)
            self.print(f"Using config file: {config}")

            with open(config) as f:
                data = f.read()

            if self.storage.getItem('config') and data != self.config:
                with open(config, 'w') as f:
                    f.write(self.config)

            if not self.storage.getItem('config'):
                self.storage.setItem('config', data)

            bin_dir = os.path.dirname(btop)
            if platform.system() == 'Windows':
                theme_dir = os.path.realpath(os.path.join(bin_dir, 'themes'))
                self.print(f"Using themes dir: {theme_dir}")
                if os.path.exists(theme_dir):
                    self.themes = [
                        theme.removesuffix('.theme')
                        for theme in os.listdir(theme_dir)
                        if theme.endswith('.theme')
                    ]
            else:
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
        config = await self.config_path

        self.storage.setItem('config', script['script'])
        await self.onDeviceEvent(ScryptedInterface.Scriptable.value, None)

        updated = False
        with open(config) as f:
            if f.read() != script['script']:
                updated = True

        if updated:
            if not script['script']:
                os.remove(config)
            else:
                with open(config, 'w') as f:
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
    CYGWIN_FONT_DIR = '~/.local/share/fonts'

    def __init__(self, nativeId: str, parent: BtopCamera):
        super().__init__(nativeId)
        self.parent = parent
        self.fonts_loaded = asyncio.ensure_future(self.load_fonts())

    async def load_fonts(self) -> None:
        if platform.system() == 'Windows':
            await self.parent.dependencies_installed
            subprocess.Popen(f'"{BtopCamera.CYGWIN_LAUNCHER}" "mkdir -p {BtopFontManager.CYGWIN_FONT_DIR}"', shell=True).communicate()
        else:
            os.makedirs(BtopFontManager.LOCAL_FONT_DIR, exist_ok=True)
        try:
            urls = self.font_urls
            for url in urls:
                filename = url.split('/')[-1]
                fullpath = self.downloadFile(url, filename)
                if platform.system() == 'Windows':
                    target = f"{BtopFontManager.CYGWIN_FONT_DIR}/{filename}"
                    copy_file_to(fullpath, target)
                else:
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
                "description": f"List of URLs to download fonts from. Fonts will be downloaded to {BtopFontManager.CYGWIN_FONT_DIR if platform.system() == 'Windows' else BtopFontManager.LOCAL_FONT_DIR}.",
                "value": self.font_urls,
                "multiple": True,
            },
        ]

    async def putSetting(self, key: str, value: str) -> None:
        self.storage.setItem(key, json.dumps(value))
        await self.onDeviceEvent(ScryptedInterface.Settings.value, None)
        await scrypted_sdk.deviceManager.requestRestart()

    async def getReadmeMarkdown(self) -> str:
        fontdir = BtopFontManager.CYGWIN_FONT_DIR if platform.system() == 'Windows' else BtopFontManager.LOCAL_FONT_DIR
        return f"""
# Font Manager

List fonts to download and install in the local font directory. Fonts will be installed to `{fontdir}`.
"""


class BtopThemeManager(DownloaderBase, Settings, Readme):
    LOCAL_THEME_DIR = os.path.expanduser(f'~/.config/btop/themes')

    def __init__(self, nativeId: str, parent: BtopCamera):
        super().__init__(nativeId)
        self.parent = parent
        self.themes_dir = asyncio.ensure_future(self.find_themes_dir())
        self.themes_loaded = asyncio.ensure_future(self.load_themes())

    async def find_themes_dir(self) -> str:
        btop = await self.parent.btop
        assert btop is not None

        bin_dir = os.path.dirname(btop)
        if platform.system() == 'Windows':
            return os.path.realpath(os.path.join(bin_dir, 'themes'))
        else:
            return BtopThemeManager.LOCAL_THEME_DIR

    async def load_themes(self) -> None:
        themes_dir = await self.themes_dir
        self.print("Using themes dir:", themes_dir)
        os.makedirs(themes_dir, exist_ok=True)
        try:
            urls = self.theme_urls
            for url in urls:
                filename = url.split('/')[-1]
                fullpath = self.downloadFile(url, filename)
                target = os.path.join(themes_dir, filename)
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
        theme_dir = await self.themes_dir
        return [
            {
                "key": "theme_urls",
                "title": "Theme URLs",
                "description": f"List of URLs to download themes from. Themes will be downloaded to {theme_dir}.",
                "value": self.theme_urls,
                "multiple": True,
            },
        ]

    async def putSetting(self, key: str, value: str) -> None:
        self.storage.setItem(key, json.dumps(value))
        await self.onDeviceEvent(ScryptedInterface.Settings.value, None)
        await scrypted_sdk.deviceManager.requestRestart()

    async def getReadmeMarkdown(self) -> str:
        themes_dir = await self.themes_dir
        return f"""
# Theme Manager

List themes to download and install in the local theme directory. Themes will be installed to `{themes_dir}`.
"""


def create_scrypted_plugin():
    return BtopCamera()