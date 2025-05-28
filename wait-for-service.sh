#!/bin/bash

echo "Waiting for mock service to be ready..."
until curl --output /dev/null --silent --fail http://mock-service:8000/health; do
    printf '.'
    sleep 1
done

echo "Mock service is ready!"
exec "$@" 