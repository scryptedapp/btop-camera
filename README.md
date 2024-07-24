# `btop` Virtual Camera

This plugin will perform best in a Docker or LXC Scrypted installation, since dependencies will be automatically installed. The `@scrypted/btop` plugin is required to download a compatible version of `btop`.

For local Scrypted installs on **Linux**, several system packages must be manually installed: `xvfb`, `xterm`, `xfonts-base`. The optional dependency `fontconfig` can be installed to enable changing fonts.

For local Scrypted installs on **MacOS**, several brew packages must be manually installed: `xquartz`, `gnu-getopt`, `ffmpeg`.

This plugin provides a virtual camera device that continuously streams output from the `btop` system monitoring tool. Under the hood, a virtual X11 display is created to run `btop` and `xterm`.

On Windows, Cygwin will be automatically installed to handle the virtual X11 display.

## Advanced usage: Hardware-accelerated encoding

By default, this plugin requests that the Rebroadcast plugin use the FFmpeg arguments `-c:v libx264 -preset -ultrafast -bf 0 -r 15 -g 60` for encoding H264 video from the virtual X11 display (`libopenh264` is used on Windows instead of `libx264`). To enable hardware acceleration, copy the above into the "FFmpeg Output Prefix" settings for the stream, replacing `libx264` with the hardware-accelerated encoder for your platform. Note that for Windows, the encoder must be one supported within Cygwin.