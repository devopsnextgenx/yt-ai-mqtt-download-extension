#!/bin/bash

# Configuration
TOPIC="vsong"
BROKER="localhost"   # change if remote broker
LOGFILE="/home/shared/logs/vsongs.log"
TMPDIR="/tmp/songs"
BASE_DIR="/media/data/Crucial-X6/ShareMe/media/songs/target"  # change to your target directory
BASE_MOVIE_DIR="/media/data/storage/ShareMe/media/movies"
# BASE_DIR="/media/data/Crucial-X6/ShareMe/media/songs/target"
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/xxxx"  # replace with your webhook

mkdir -p "$TMPDIR"

# Function: log
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOGFILE"
}

declare -A FVCODE_MAP=( ["2160"]="401" ["1440"]="400" ["1080"]="399" ["720"]="398" )
declare -A FVSTORE_MAP=( ["2160"]="4k" ["1440"]="2k" ["1080"]="1080p" ["720"]="720p" )

# Poll messages (run every 5 minutes via cron)
messages=$(timeout 10s mosquitto_sub -h "$BROKER" -t "$TOPIC" -c -i downloadmqttsub -q 1)

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
    RES=$(echo "$msg" | jq -r '.RES') # 2160/1440/1080/720
    MP4URL=$(echo "$msg" | jq -r '.MP4URL')
    TYPE=$(echo "$msg" | jq -r '.TYPE')

    # Validate
    if [ -z "$LNG" ] || [ -z "$ACT" ] || [ -z "$RES" ] || [ -z "$MP4URL" ]; then
        log "Invalid message: $msg"
        continue
    fi
    

    # Format string
    FVCODE="${FVCODE_MAP[$RES]}"
    if [ -z "$FVCODE" ]; then
        log "Unknown RES '$RES' — cannot determine video format code. Skipping."
        FVCODE=399  # default to 1080p
    fi

    FACODE=140  # m4a audio
    # FORMAT="${FVCODE}+${FACODE}"
    FORMAT="bestvideo[height<=${RES}]+bestaudio[ext=m4a]/mp4"

    # Download
    start_time=$(date +%s)
    log "Downloading: LNG=$LNG, ACT=$ACT, RES=$RES, URL=$MP4URL"
    
    yt-dlp -f "$FORMAT" --merge-output-format mp4 --no-progress -c "$MP4URL" --restrict-filenames -o "$TMPDIR/%(title)s.%(ext)s" >> "$LOGFILE" 2>&1

    if [ $? -ne 0 ]; then
        log "Download failed: $MP4URL"
        continue
    fi

    # Find most recent file
    FILE=$(ls -t "$TMPDIR" | head -1)
    SRC="$TMPDIR/$FILE"
    HEIGHT=`ffprobe -v quiet -select_streams v -show_streams "$TMPDIR/$FILE" | grep height |grep -v coded|cut -d "=" -f 2`

    RES="${FVSTORE_MAP[$HEIGHT]}"

    if [ -z "$RES" ]; then
        log "Could not determine storage RES for height $HEIGHT. Using original RES $RES."
        RES="UNKNOWN"
    fi

    normalized_lng="${LNG,,}"
    case "${normalized_lng,,}" in
        telugu|kannada|tamil|malayalam|malyalam)
            LNG="South"
            ;;
    esac
    # Paths
    TARGET_DIR="$BASE_DIR/$LNG/$RES/$ACT"
    if [ "$TYPE" == "Movie" ]; then
        LNG="bollywood"
        if [ "$LNG" = "English" ]; then
            LNG="hollywood"
        fi
        TARGET_DIR="$BASE_MOVIE_DIR/$LNG"
    fi
    
    mkdir -p "$TARGET_DIR"

    DEST="$TARGET_DIR/$FILE"
    
    log "Moving to: $TARGET_DIR"

    mv "$SRC" "$DEST"

    end_time=$(date +%s)
    elapsed=$((end_time - start_time))
    filesize=$(du -h "$DEST" | cut -f1)

    log "Downloaded: $DEST ($filesize in ${elapsed}s)"
    # Append to summary
    summary="${summary}✅ $FILE\nURL: $MP4URL\nSize: $filesize\nPath: $DEST\nTime: ${elapsed}s\n\n"
    count=$((count+1))

done
mosquitto_pub -h localhost -t "vsong" -n -r

# Notify Slack after batch if any downloads succeeded
if [ "$count" -gt 0 ]; then
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"✅ Batch Download Complete: $count file(s)\n\n$summary\"}" \
        "$SLACK_WEBHOOK_URL"
fi