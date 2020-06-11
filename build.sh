#!/bin/bash

pipenv lock --requirements --keep-outdated > ./src/requirements.txt

sam build --use-container

