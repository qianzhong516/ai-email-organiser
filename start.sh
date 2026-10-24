#!/bin/bash

set -e

docker compose up -d

# download the model
docker compose exec ollama ollama pull qwen2.5:7b

docker compose exec ollama ollama list
