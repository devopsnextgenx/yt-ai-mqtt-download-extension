#!/bin/bash
export PATH=/usr/local/bin:/usr/bin:/bin
export HOME=/home/admn

# Configuration
TOPIC="vsong"
BROKER="localhost"   # change if remote broker
LOGFILE="/home/shared/logs/vsongs.log"
FAILED_MSG_LOG="/home/shared/logs/failed-msg.txt"
TMPDIR="/tmp/songs"
BASE_SONG_DIR=$(grep '^BASE_SONG_DIR=' /home/shared/.secrets | cut -d'=' -f2-)
BASE_MOVIE_DIR=$(grep '^BASE_MOVIE_DIR=' /home/shared/.secrets | cut -d'=' -f2-)
# Read SLACK_WEBHOOK_URL from secret file
SLACK_WEBHOOK_URL=$(grep '^SLACK_WEBHOOK_URL=' /home/shared/.secrets | cut -d'=' -f2-)

mkdir -p "$TMPDIR"

# Function: log
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOGFILE"
}

declare -A FVCODE_MAP=( ["2160"]="401" ["1440"]="400" ["1080"]="399" ["720"]="398" )
declare -A FVSTORE_MAP=( ["2160"]="4k" ["1440"]="2k" ["1080"]="1080p" ["720"]="720p" )

# Poll messages (run every 5 minutes via cron)
messages=$(timeout 10s mosquitto_sub -h "$BROKER" -t "$TOPIC"  -q 1 -c -i downloadmqttsub)

if [ -z "$messages" ]; then
    log "No messages received from MQTT."
    exit 0
fi

log "Received messages: $(echo "$messages" | wc -l)"

# Prepare summary
summary=""
failed_summary=""
count=0
failed_count=0

# Process each JSON message
while IFS= read -r msg; do
    [ -z "$msg" ] && continue
    log "Processing message: $msg"
    LNG=$(echo "$msg" | jq -r '.LNG')
    TITLE=$(echo "$msg" | jq -r '.TITLE')
    ACT=$(echo "$msg" | jq -r '.ACT')
    RES=$(echo "$msg" | jq -r '.RES') # 2160/1440/1080/720
    MP4URL=$(echo "$msg" | jq -r '.MP4URL')
    TYPE=$(echo "$msg" | jq -r '.TYPE')
    RETRY=$(echo "$msg" | jq -r '.RETRY // 0')

    # Validate
    if [ -z "$LNG" ] || [ -z "$ACT" ] || [ -z "$RES" ] || [ -z "$MP4URL" ]; then
        log "Invalid message: $msg"
        failed_summary="${failed_summary}\n❌ Invalid message: $msg"
        # Increment RETRY and resend if less than 5, else log to FAILED_MSG_LOG
        RETRY=$((RETRY + 1))
        if [ "$RETRY" -lt 5 ]; then
            new_msg=$(echo "$msg" | jq -c --argjson retry "$RETRY" '.RETRY = $retry')
            mosquitto_pub -h "$BROKER" -t "$TOPIC" -m "$new_msg" -q 1
            log "Resent invalid message with RETRY=$RETRY"
        else
            echo "$msg" >> $FAILED_MSG_LOG
            log "Message failed after 5 retries, added to FAILED_MSG_LOG"
        fi
        failed_count=$((failed_count+1))
        continue
    fi

    

    # Format string
    FVCODE="${FVCODE_MAP[$RES]}"
    if [ -z "$FVCODE" ]; then
        log "Unknown RES '$RES' — cannot determine video format code. Skipping."
        FVCODE=399  # default to 1080p
    fi

    # Get format codes in one yt-dlp call
    FORMATS=$(yt-dlp -F "$MP4URL")
    log "$FORMATS"
    FACODE=$(echo "$FORMATS" | grep audio | tail -1 | awk '{print $1}')
    log "FACODE: $FACODE"
    FVCODE=$(echo "$FORMATS" | grep $RES | tail -1 | awk '{print $1}')
    log "FVCODE: $FVCODE"
    FORMAT=$FVCODE+$FACODE
    
    # FORMAT="bestvideo[height<=${RES}]+bestaudio[ext=m4a]/mp4"

    # Download
    start_time=$(date +%s)
    log "Downloading: LNG=$LNG, ACT=$ACT, RES=$RES, URL=$MP4URL, FORMAT=$FORMAT"
    
    sudo -u admn yt-dlp --user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36" \
        -f "$FVCODE+$FACODE" \
        --merge-output-format mp4 \
        --no-progress \
        --restrict-filenames \
        -c -o "$TMPDIR/%(title)s.%(ext)s" \
        "$MP4URL" >> "$LOGFILE" 2>&1

    if [ $? -ne 0 ]; then
        log "Download failed: $MP4URL"
        failed_summary="${failed_summary}\n❌ URL: $MP4URL\nTITLE: $TITLE\nReason: Download failed\n"
        # Increment RETRY and resend if less than 5, else log to FAILED_MSG_LOG
        RETRY=$((RETRY + 1))
        if [ "$RETRY" -lt 5 ]; then
            new_msg=$(echo "$msg" | jq -c --argjson retry "$RETRY" '.RETRY = $retry')
            mosquitto_pub -h "$BROKER" -t "$TOPIC" -m "$new_msg" -q 1
            log "Resent failed message with RETRY=$RETRY"
        else
            echo "$msg" >> $FAILED_MSG_LOG
            log "Message failed after 5 retries, added to FAILED_MSG_LOG"
        fi
        continue
    fi

    # Find most recent file
    FILE=$(ls -t "$TMPDIR" | head -1)
    SRC="$TMPDIR/$FILE"
    HEIGHT=`ffprobe -v quiet -select_streams v -show_streams "$TMPDIR/$FILE" | grep height |grep -v coded|cut -d "=" -f 2`

    VRES="${FVSTORE_MAP[$HEIGHT]}"

    if [ -z "$VRES" ]; then
        log "Could not determine storage RES for height $HEIGHT. Using original RES $RES."
        if [ "$RES" -le 720 ]; then
            VRES=720
        elif [ "$RES" -le 1080 ]; then
            VRES=1080
        elif [ "$RES" -le 1440 ]; then
            VRES=1440
        elif [ "$RES" -le 2160 ]; then
            VRES=2160
        else
            VRES=2160
            echo "Warning: RES ($RES) is higher than 2160, setting VRES to 2160"
        fi
    fi

    normalized_lng="${LNG,,}"
    case "${normalized_lng,,}" in
        telugu|kannada|tamil|malayalam|malyalam)
            LNG="South"
            ;;
    esac
    # Paths
    TARGET_DIR="$BASE_SONG_DIR/$LNG/$VRES/$ACT"

    normalized_type="${TYPE,,}"
    if [ "$normalized_type" == "movie" ]; then
        LNG="bollywood"
        if [ "$LNG" == "english" ]; then
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
    summary="${summary}\n✅ URL: $MP4URL\nPath: $DEST\nSize: $filesize (Time: ${elapsed}s)\n"
    summary="${summary}\n========================================================================\n"
    log "$summary"
    count=$((count+1))

done <<< "$messages"

mosquitto_pub -h localhost -t "vsong" -n -r

log "Finished processing batch. Total successful downloads: $count, failed: $failed_count"
log "Summary:\n$summary"

# Notify Slack after batch if any downloads succeeded or failed
if [ "$count" -gt 0 ] || [ "$failed_count" -gt 0 ]; then
    slack_msg="✅ Batch Download Complete: $count file(s)\n\n$summary"
    if [ "$failed_count" -gt 0 ]; then
        failed_summary="\n========================================================================\n❌ Failed Downloads: $failed_count\n${failed_summary}\n========================================================================\n"
        slack_msg="${slack_msg}$failed_summary"
        log "Failed Summary:\n$failed_summary"
    fi
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"$slack_msg\"}" \
        "$SLACK_WEBHOOK_URL"
fi