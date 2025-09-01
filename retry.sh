#!/bin/bash

TOPIC="vsong"
BROKER="localhost"   # change if remote broker

while IFS= read -r new_msg; do
    mosquitto_pub -h "$BROKER" -t "$TOPIC" -m "$new_msg" -q 1
done < failed