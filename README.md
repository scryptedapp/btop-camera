# `btop` Virtual Camera

**This plugin will only work on Linux!** It will perform best in a Docker or LXC Scrypted installation. For local Scrypted installs, several system packages must be manually installed: `xvfb`, `xterm`, `xfonts-base`, `btop`.

This plugin provides a virtual camera device that continuously streams output from the `btop` system monitoring tool. Under the hood, a virtual X11 display is created to run `btop` and `xterm`. An instance of `ffmpeg` is used to stream the screen capture over RTMP from the virtual display.