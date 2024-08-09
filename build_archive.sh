#!/bin/bash

cat /etc/*release*
pwd
ls -lrth
apt-get update
apt-get install -y zip

pip install --no-cache-dir -r requirements.txt --target .

zip -r /out.zip .

cat $1 /out.zip > $2