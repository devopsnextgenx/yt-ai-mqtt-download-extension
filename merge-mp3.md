#!/bin/bash

# Basic command to merge MP3 into MP4 with dual audio
ffmpeg -i input_video.mp4 -i audio_hindi.mp3 \
  -c:v copy \
  -c:a aac \
  -map 0:v:0 \
  -map 1:a:0 \
  -map 0:a:0 \
  -metadata:s:a:0 language=hin \
  -metadata:s:a:1 language=eng \
  -disposition:a:0 default \
  -disposition:a:1 0 \
  output_dual_audio.mp4

### Example
ffmpeg -i "Prince Of Persia (2010).mp4" -i "Hindi.mp3" \
  -c:v copy \
  -c:a:0 aac -b:a:0 128k \
  -c:a:1 aac -b:a:1 128k \
  -map 0:v:0 \
  -map 1:a:0 \
  -map 0:a:0 \
  -metadata:s:a:0 language=hin \
  -metadata:s:a:1 language=eng \
  -metadata:s:a:0 title="Hindi" \
  -metadata:s:a:1 title="English" \
  -disposition:a:0 default \
  -disposition:a:1 0 \
  "Prince Of Persia - The Sands of Time (2010).mp4"

# Method 1: Using itsoffset to delay only the Hindi MP3 audio
ffmpeg -i "Prince Of Persia (2010).mp4" -itsoffset 5 -i "Hindi.mp3" \
  -c:v copy \
  -c:a:0 aac -b:a:0 128k \
  -c:a:1 aac -b:a:1 128k \
  -map 0:v:0 \
  -map 1:a:0 \
  -map 0:a:0 \
  -metadata:s:a:0 language=hin \
  -metadata:s:a:1 language=eng \
  -metadata:s:a:0 title="Hindi" \
  -metadata:s:a:1 title="English" \
  -disposition:a:0 default \
  -disposition:a:1 0 \
  "Prince Of Persia - The Sands of Time (2010).mp4"

# Method 2: Using adelay filter (more precise control)
ffmpeg -i "Avatar The Way of Water (2022).mp4" -i "Hindi.mp3" \
  -c:v copy \
  -filter_complex "[1:a]adelay=5000|5000[delayed_hindi]" \
  -map 0:v:0 \
  -map "[delayed_hindi]" \
  -map 0:a:0 \
  -c:a:0 aac -b:a:0 128k \
  -c:a:1 aac -b:a:1 128k \
  -metadata:s:a:0 language=hin \
  -metadata:s:a:1 language=eng \
  -metadata:s:a:0 title="Hindi" \
  -metadata:s:a:1 title="English" \
  -disposition:a:0 default \
  -disposition:a:1 0 \
  "Prince Of Persia - The Sands of Time (2010).mp4"

# Command breakdown:
# -i input_video.mp4    : Input MP4 file
# -i audio_hindi.mp3    : Input MP3 audio file
# -c:v copy            : Copy video stream without re-encoding
# -c:a aac             : Encode audio streams to AAC
# -map 0:v:0           : Map video from first input
# -map 1:a:0           : Map audio from second input (MP3) as first audio track
# -map 0:a:0           : Map audio from first input (MP4) as second audio track
# -metadata:s:a:0 language=hin  : Set first audio track language to Hindi
# -metadata:s:a:1 language=eng  : Set second audio track language to English
# -disposition:a:0 default      : Set first audio track as default
# -disposition:a:1 0            : Remove default flag from second audio track