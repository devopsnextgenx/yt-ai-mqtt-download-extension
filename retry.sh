#!/bin/bash

TOPIC="vsong"
BROKER="192.168.12.111"   # change if remote broker

RETRY_FILE="/home/kira/git/devopsnextgenx/yt-ai-mqtt-download-extension/failed-msg.txt"

if [[ ! -f "$RETRY_FILE" ]]; then
    echo "Retry file not found: $RETRY_FILE"
    exit 1
fi

echo "Reading messages from $RETRY_FILE"
while IFS= read -r new_msg || [[ -n "$new_msg" ]]; do
    if [[ -n "$new_msg" ]]; then
        echo "Retrying message: $new_msg"
        mosquitto_pub -h "$BROKER" -t "$TOPIC" -m "$new_msg" -q 1
    fi
done < "$RETRY_FILE"