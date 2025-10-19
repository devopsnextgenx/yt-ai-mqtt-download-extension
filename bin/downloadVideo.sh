#!/bin/bash
# create a function to log messages with timestamps to the logfile and console both
log_message() {
    echo "[$(date +"%Y-%m-%d %T")] $1" | tee -a $logfile
}

lockFile=./video.lock;
logfile=./video_download.log;
downloadFile=./videos.txt;
downloadFileTmp=./videos.txt.tmp;

MOVIE_STORE_DIR=//192.168.12.111/data/storage/ShareMe/media/movies
SONG_STORE_DIR=//192.168.12.111/data/Crucial-X6/ShareMe/media/songs/target

file="temp.txt"
DRY_RUN=false

# Parse command-line arguments
for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            log_message "DRY RUN MODE: Commands will be displayed but not executed"
            shift
            ;;
    esac
done

if [ -f $lockFile ] && [ "$DRY_RUN" = false ]
then
    exit;
else
    log_message "Start new downloads";
fi

log_message "================================================================================================"
log_message "File processing started at `date +"%Y-%m-%d %T"`"
if [ -f $downloadFile ]
then
    if [ "$DRY_RUN" = false ]; then
        touch $lockFile;
    fi
    TIMESTAMP=$(date +"%Y-%m-%d-%H%M%S")
    OUTPUT_DIR="./Videos/$TIMESTAMP"
    if [ "$DRY_RUN" = false ]; then
        mkdir -p "$OUTPUT_DIR"
    else
        log_message "DRY RUN: Would create directory $OUTPUT_DIR"
    fi
    
    # Initialize default values
    prev_RESOLUTION=1080
    prev_LANG="English"
    prev_actress="Unknown"
    
    # Iterate through each line in the downloadFile
    while IFS= read -r entry || [ -n "$entry" ]; do
        echo "Processing entry: $entry"
        # Split entry by '|', but parameters might be missing
        IFS='|' read -r url RESOLUTION LANG actress <<< "$entry"
        
        # Use previous values if parameters are missing
        url=$(echo "$url" | xargs)
        
        if [ -z "$RESOLUTION" ]; then
            RESOLUTION=$prev_RESOLUTION
            log_message "Using previous resolution: $RESOLUTION"
        else
            RESOLUTION=$(echo "$RESOLUTION" | xargs)
            prev_RESOLUTION=$RESOLUTION
        fi
        
        if [ -z "$LANG" ]; then
            LANG=$prev_LANG
            log_message "Using previous language: $LANG"
        else
            LANG=$(echo "$LANG" | xargs)
            prev_LANG=$LANG
        fi
        
        if [ -z "$actress" ]; then
            actress=$prev_actress
            log_message "Using previous actress: $actress"
        else
            actress=$(echo "$actress" | xargs)
            prev_actress=$actress
        fi
        
        log_message "Processing entry: URL=$url, RESOLUTION=$RESOLUTION, LANG=$LANG, Actress=$actress"

        # Set resDir based on RESOLUTION value
        resDir="1080p"

        if [ "$RESOLUTION" -ge 1440 ]; then
            resDir="4k"
        elif [ "$RESOLUTION" -gt 1080 ]; then
            resDir="2k"
        elif [ "$RESOLUTION" -gt 720 ]; then
            resDir="1080p"
        elif [ "$RESOLUTION" -eq 720 ]; then
            resDir="720p"
        elif [ "$RESOLUTION" -le 600 ]; then
            resDir="sd"
        else
            resDir="1080p"
        fi
        if [ -n "$url" ]; then
            log_message "Downloading video from URL: $url"
            
            if [ "$DRY_RUN" = false ]; then
                # List and store available formats to FORMATS variable
                log_message "Available formats for $url"
                FORMATS=$(./yt-dlp -F "$url")
                log_message "$FORMATS"
                VFORMAT=$(echo "$FORMATS" | grep "video only" | awk '{print "{\"id\":\""$1"\",\"type\":\""$2"\",\"resolution\":\""$3"\",\"encoding\":\""$10"\"}"}'| jq -s .)
                AFORMAT=$(echo "$FORMATS" | tr -s "," " "| grep "audio only" | awk '{print "{\"id\":\""$1"\",\"type\":\""$2"\",\"quality\":\""$17"\"}"}' | jq -s .)
            else
                log_message "DRY RUN: Would check formats for URL: $url"
                VFORMAT='[{"id":"137","type":"mp4","resolution":"1920x1080","encoding":"avc1"}]'
                AFORMAT='[{"id":"140","type":"m4a","quality":"medium"}]'
            fi
            
            # if quality is high, select it else select medium if not then use low, and use that id
            ADOWNLOADFORMAT=$(echo "$AFORMAT" \
                | jq -r '
                    (map(select(.quality=="high"))   | .[0].id) // 
                    (map(select(.quality=="medium")) | .[0].id) // 
                    (map(select(.quality=="low"))    | .[0].id)
                    ')
            log_message "Selected audio format ID: $ADOWNLOADFORMAT"
            if [ -z "$ADOWNLOADFORMAT" ] || [ "$ADOWNLOADFORMAT" == "null" ]; then
                ADOWNLOADFORMAT=$(echo "$AFORMAT" \
                | jq -r '
                    if length > 0 then .[-1].id else empty end
                    ')
                log_message "Selected audio format ID: $ADOWNLOADFORMAT"
            fi
            # Select video format based on resolution criteria
            VDOWNLOADFORMAT=$(echo "$VFORMAT" | jq -r --argjson target "$RESOLUTION" '
                def pref(enc):
                    if (enc | startswith("av01")) then 0
                    elif (enc | startswith("avc1")) then 1
                    elif (enc | startswith("vp9")) then 2
                    else 3 end;

                # Add parsed height + encoding preference
                map(. + {
                    height: (.resolution | split("x")[1] | tonumber),
                    enc_pref: pref(.encoding)
                })
                # Choose candidate group
                | (
                    (map(select(.height == $target)))      # exact match
                    // (map(select(.height > $target))     | sort_by(.height) | .[:1])  # nearest higher
                    // (sort_by(.height) | reverse | .[:1])                          # highest available
                    )
                # Pick best encoding within that group
                | sort_by(.enc_pref) | .[0].id
                ')

            log_message "Selected video format ID: $VDOWNLOADFORMAT"
            if [ -z "$VDOWNLOADFORMAT" ] || [ "$VDOWNLOADFORMAT" == "null" ]; then
                VDOWNLOADFORMAT=$(echo "$VFORMAT" \
                | jq -r '
                    if length > 0 then .[-1].id else empty end
                    ')
                log_message "Selected video format ID: $VDOWNLOADFORMAT"
            fi

            if [ $VDOWNLOADFORMAT == "null" ]; then
                VDOWNLOADFORMAT="401"
            fi

            if [ $ADOWNLOADFORMAT == "null" ]; then
                ADOWNLOADFORMAT="251"
            fi
            
            if [ "$DRY_RUN" = false ]; then
                # Add random sleep between 5 to 15 seconds
                SLEEP_TIME=$((RANDOM % 11 + 5))
                log_message "Sleeping for $SLEEP_TIME seconds"
                sleep $SLEEP_TIME
                # Example format selection, modify as needed
                ./yt-dlp -f "$VDOWNLOADFORMAT+$ADOWNLOADFORMAT" --no-progress -c --embed-thumbnail --add-metadata --merge-output-format mp4 -o "$OUTPUT_DIR/%(title)s.%(ext)s" "$url" >> $logfile 2>&1
                # get file name from downloaded video
                FILENAME=$(ls -1tr $OUTPUT_DIR | tail -n 1)
                log_message "Downloaded file: $OUTPUT_DIR/$FILENAME"
            else
                log_message "DRY RUN: Would run command: ./yt-dlp -f $VDOWNLOADFORMAT+$ADOWNLOADFORMAT --no-progress -c --embed-thumbnail --add-metadata --merge-output-format mp4 -o $OUTPUT_DIR/%(title)s.%(ext)s $url"
                FILENAME="example_video_name.mp4"  # Dummy filename for dry run
            fi
            
            # if convert lang to lowercase
            LANG=$(echo "$LANG" | tr '[:upper:]' '[:lower:]')
            # if convert lang to lowercase lang is Telugu/Tamil/Malayalam/Kannada then and set LANG to South
            if [[ "$LANG" == "telugu" || "$LANG" == "tamil" || "$LANG" == "malayalam" || "$LANG" == "kannada" ]]; then
                LANG="South"
            fi
            if [[ "$LANG" == "hindi" || "$LANG" == "bengali" ]]; then
                LANG="Hindi"
            fi
            if [[ "$LANG" == "english" ]]; then
                LANG="English"
            fi
            if [[ "$LANG" == "marathi" ]]; then
                LANG="Marathi"
            fi
            if [[ "$LANG" == "bhojpuri" ]]; then
                LANG="Bhojpuri"
            fi
            actressTitle=$(echo "$actress" | tr '[:upper:]' '[:lower:]')
            FINAL_DESTINATION="$SONG_STORE_DIR/$LANG/$resDir/$actress"
            if [ $actressTitle == "movie" ]; then
                if [ $LANG == "English" ]; then
                    LANG="hollywood"
                else
                    LANG="bollywood"
                fi
                FINAL_DESTINATION="$MOVIE_STORE_DIR/$LANG"
            else
                FINAL_DESTINATION="$SONG_STORE_DIR/$LANG/$resDir/$actress"
            fi
            
            if [ "$DRY_RUN" = false ]; then
                mkdir -p "$FINAL_DESTINATION"
                log_message "Moving file $OUTPUT_DIR/$FILENAME -> $FINAL_DESTINATION/"
                mv "$OUTPUT_DIR/$FILENAME" "$FINAL_DESTINATION/$FILENAME"
                log_message "Moved file to: $FINAL_DESTINATION/$FILENAME"
                # Add random sleep between 5 to 15 seconds
                SLEEP_TIME=$((RANDOM % 11 + 5))
                log_message "Sleeping for $SLEEP_TIME seconds"
                sleep $SLEEP_TIME
            else
                log_message "DRY RUN: Would create directory: $FINAL_DESTINATION"
                log_message "DRY RUN: Would move file from $OUTPUT_DIR/$FILENAME to $FINAL_DESTINATION/$FILENAME"
            fi
        fi
    done <$downloadFile
    
    if [ "$DRY_RUN" = false ]; then
        rm -r $OUTPUT_DIR
        rm $lockFile;
        if [ -f $downloadFileTmp ]; then
            mv $downloadFileTmp $downloadFile;
        fi
    else
        log_message "DRY RUN: Would remove directory $OUTPUT_DIR"
        log_message "DRY RUN: Would remove lock file $lockFile"
        if [ -f $downloadFileTmp ]; then
            log_message "DRY RUN: Would move $downloadFileTmp to $downloadFile"
        fi
    fi
else
    log_message "No file $downloadFile for Processing";
fi
log_message "File processing completed";
log_message "================================================================================================";
