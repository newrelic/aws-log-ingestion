#!/bin/bash

poetry install
poetry export -o ./src/requirements.txt --without-hashes
poetry run sam build --use-container
