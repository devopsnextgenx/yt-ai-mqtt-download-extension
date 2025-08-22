#!/bin/bash

# Configuration
TOPIC="VSONG"
BROKER="localhost"   # change if remote broker
LOGFILE="/home/shared/logs/vsongs.log"
TMPDIR="/tmp/songs"
BASE_DIR="/home/kira/Videos/HD"  # change to your target directory
# BASE_DIR="/media/data/Crucial-X6/ShareMe/media/songs/target"
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/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"  # replace with your webhook

mkdir -p "$TMPDIR"

# Function: log
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOGFILE"
}

# Poll messages (run every 5 minutes via cron)
messages=$(timeout 20s mosquitto_sub -h "$BROKER" -t "$TOPIC" -C 10)

if [ -z "$messages" ]; then
    log "No messages received from MQTT."
    exit 0
fi

log "Received messages: $(echo "$messages" | wc -l)"

# Prepare summary
summary=""
count=0

# Process each JSON message
echo "$messages" | while read -r msg; do
    [ -z "$msg" ] && continue
    log "Processing message: $msg"
    LNG=$(echo "$msg" | jq -r '.LNG')
    ACT=$(echo "$msg" | jq -r '.ACT')
    RES=$(echo "$msg" | jq -r '.RES')
    MP4URL=$(echo "$msg" | jq -r '.MP4URL')

    # Validate
    if [ -z "$LNG" ] || [ -z "$ACT" ] || [ -z "$RES" ] || [ -z "$MP4URL" ]; then
        log "Invalid message: $msg"
        continue
    fi

    # Paths
    TARGET_DIR="$BASE_DIR/$LNG/$ACT/$RES"
    mkdir -p "$TARGET_DIR"

    # Format string
    FORMAT="bestvideo[height<=${RES}]+bestaudio[ext=m4a]/mp4"

    # Download
    start_time=$(date +%s)
    log "Downloading: LNG=$LNG, ACT=$ACT, RES=$RES, URL=$MP4URL"

    yt-dlp -f "$FORMAT" --merge-output-format mp4 --no-progress -c "$MP4URL" \
        --restrict-filenames -o "$TMPDIR/%(title)s.%(ext)s" >> "$LOGFILE" 2>&1

    if [ $? -ne 0 ]; then
        log "Download failed: $MP4URL"
        continue
    fi

    # Find most recent file
    FILE=$(ls -t "$TMPDIR" | head -1)
    SRC="$TMPDIR/$FILE"
    DEST="$TARGET_DIR/$FILE"

    mv "$SRC" "$DEST"

    end_time=$(date +%s)
    elapsed=$((end_time - start_time))
    filesize=$(du -h "$DEST" | cut -f1)

    log "Downloaded: $DEST ($filesize in ${elapsed}s)"

    # Append to summary
    summary="${summary}✅ $FILE\nURL: $MP4URL\nSize: $filesize\nPath: $DEST\nTime: ${elapsed}s\n\n"
    count=$((count+1))

done

# Notify Slack after batch if any downloads succeeded
if [ "$count" -gt 0 ]; then
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"✅ Batch Download Complete: $count file(s)\n\n$summary\"}" \
        "$SLACK_WEBHOOK_URL"
fi