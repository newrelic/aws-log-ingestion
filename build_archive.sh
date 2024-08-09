#!/bin/bash

cat /etc/*release*
pwd
ls -lrth
yum update
yum install -y zip

pip install --no-cache-dir -r /src/requirements.txt --target .

zip -r /out.zip .

cat $1 /out.zip > $2