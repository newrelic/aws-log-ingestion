#!/bin/bash

# For those unable to use SAM, this builds a zip file that can be deployed using the AWS CLI or terraform or the like.
# The resulting zip will be placed in the build directory. It uses a python3 virtual environment, per the
# instructions here: https://docs.aws.amazon.com/lambda/latest/dg/python-package.html

# A suffix may be added to the zip name by defining the SUFFIX environment variable before invoking this script.

# Constants
BUILDDIR=build

# Extract the version from the template.yaml file
VERSION=`grep SemanticVersion template.yaml | sed -e 's/ *SemanticVersion: *//'`
ZIPFILE=newrelic-log-ingestion-${VERSION}${SUFFIX}.zip

# Clean up any old build
echo "Cleaning old builds..."
rm -rf ${BUILDDIR}

# Create the virtual environment, and activate it
echo "Setting up virtual environment..."
python3 -m venv ${BUILDDIR}
source build/bin/activate

# Install the requirements, excluding boto3, which is pre-installed in AWS
echo "Installing dependencies..."
cat src/requirements.txt | grep -v boto3 > /tmp/requirements.txt
pip3 --disable-pip-version-check install --requirement /tmp/requirements.txt

# Deactivate the virtual environment
deactivate

# Package up the dependencies
echo "Creating zip of dependencies..."
(cd ${BUILDDIR}/lib/python*/site-packages && zip --quiet --recurse-paths -9 ../../../${ZIPFILE} .)

# Add the function to the zip file
echo "Adding function to zip..."
(cd src && zip --grow --quiet ../${BUILDDIR}/${ZIPFILE} function.py)

# All done!
echo "Done, zipfile: ${BUILDDIR}/${ZIPFILE}"

