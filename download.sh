#!/bin/bash
yt-dlp -F "$1"
read -p "Video Format: " VFORMAT
read -p "Audio Format: " AFORMAT
yt-dlp -f "$VFORMAT+$AFORMAT" --embed-thumbnail --no-progress --merge-output-format mp4 -c -o "%(title)s.%(ext)s" $1 &
