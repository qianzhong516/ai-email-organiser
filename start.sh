#!/bin/bash

set -e

docker compose up -d

# download the model
docker compose exec ollama ollama pull llama3.2:1b

docker compose exec ollama ollama list
