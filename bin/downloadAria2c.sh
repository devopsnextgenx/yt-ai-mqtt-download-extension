#!/bin/bash

URL=$1

if [ -z "$URL" ]; then
    echo "Usage: $0 <URL> [FOLDER] [EXTENTION]"
    exit 1
fi

if [ -z "$2" ]; then
    FOLDER=$(pwd)
else 
    FOLDER=$2
    mkdir -p "$FOLDER"
    cd "$FOLDER" || exit 1
    FOLDER=$(pwd)
fi
# extract current folder name from path
FOLDER_NAME=$(basename "$FOLDER")
echo "Downloading to folder: $FOLDER_NAME"
if [ -z "$3" ]; then
    EXTENTION="mp4"
else 
    EXTENTION=$3
fi
FILE_NAME="${FOLDER_NAME}.${EXTENTION}"
# touch "$FOLDER_NAME.txt"
nohup aria2c -x16 -s16 -k1M -o "$FILE_NAME" \
    $URL &