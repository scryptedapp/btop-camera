# `btop` Virtual Camera

**This plugin will only work on Linux and MacOS!** It will perform best in a Docker or LXC Scrypted installation, since dependencies will be automatically installed. In this device's Extensions list, the Snapshot plugin should be enabled *after* the Rebroadcast plugin.

For local Scrypted installs on **Linux**, several system packages must be manually installed: `xvfb`, `xterm`, `xfonts-base`, `btop`. `fontconfig` is required for changing fonts.

For local Scrypted installs on **MacOS**, several brew packages must be manually installed: `xquartz`, `gnu-getopt`, `ffmpeg`, `btop`.

This plugin provides a virtual camera device that continuously streams output from the `btop` system monitoring tool. Under the hood, a virtual X11 display is created to run `btop` and `xterm`. An instance of `ffmpeg` is used to stream the screen capture over RTMP from the virtual display.

## Advanced usage: Hardware-accelerated encoding

By default, this plugin requests that the Rebroadcast plugin use the FFmpeg arguments `-c:v libx264 -preset -ultrafast -bf 0 -r 15 -g 60` for encoding H264 video from the virtual X11 display. To enable hardware acceleration, copy the above into the "FFmpeg Output Prefix" settings for the stream, replacing `libx264` with the hardware-accelerated encoder for your platform.