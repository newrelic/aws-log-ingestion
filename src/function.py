'''
Copyright 2017 New Relic, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

This Lambda function receives log entries from CloudWatch Logs or S3 buckets
and pushes them to New Relic Infrastructure - Cloud integrations.

It expects to be invoked based on CloudWatch Logs streams although it's
ready to read log files from S3 buckets too.

New Relic's license key must be encrypted using KMS following these
instructions:

1. After creating te Lambda based on the Blueprint, select it and open the Environment Variables
section.

2. Check the "Enable encryption helpers" and press "Encrypt" button next to the "LICENSE_KEY" 
environment variable.

3. Go to the start of the page and press "Save". Logs should start to be processed by the Lambda.
To check if everything is functioning properly you can check the Monitoring tab and CloudWatch Logs

For more detailed documentation, check New Relic's documentation site:
https://docs.newrelic.com/
'''
from __future__ import print_function
import os
import gzip
import json
import urllib2
import time
import boto3

from StringIO import StringIO
from base64 import b64decode


# New Relic Infractructure's ingest service. Do not modify.
INGEST_SERVICE_URL = 'https://infra-api.newrelic.com/integrations/aws'

# Retrying configuration.
# Increasing these numbers will make the function longer in case of
# communication failures and that will increase the cost.
# Decreasing these number could increase the probility of data loss.

# Maximum number of retries
MAX_RETRIES = 3
# Initial backoff (in seconds) between retries
INITIAL_BACKOFF = 1
# Multiplier factor for the backoff between retries
BACKOFF_MULTIPLIER = 2


class MaxRetriesException(Exception):
    pass


class BadRequestException(Exception):
    pass


def http_retryable(func):
    '''
    Decorator that retries HTTP calls.

    The decorated function should perform an HTTP request and return its
    response.
    
    That function will be called until it returns a 200 OK response or 
    MAX_RETRIES is reached. In that case a MaxRetriesException will be raised.
    
    If the function returns a 4XX Bad Request, it will raise a
    BadRequestException without any retry.
    '''
    def wrapper_func():
        backoff = INITIAL_BACKOFF
        retries = 0

        while retries < MAX_RETRIES:
            if retries > 0:
                print('Retrying in {} seconds'.format(backoff))
                time.sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER

            retries += 1

            try:
                response = func()

            # This exception is raised when receiving a non-200 response
            except urllib2.HTTPError as e:
                print('There was an error. Reason: {}'.format(e.reason))
                if 400 <= e.getcode() < 500:
                    raise BadRequestException(e.read())

            # This exception is raised when the service is not responding
            except urllib2.URLError as e:
                print('There was an error. Reason: {}'.format(e.reason))
            else:
                return response

        raise MaxRetriesException()

    return wrapper_func


def _get_log_type(event):
    '''
    This function determines if the given event is triggered by 
    CloudWatch Logs or S3's ObjectCreated action.
    '''
    if 'awslogs' in event:
        return 'cw_logs'
    elif ('Records' in event
        and 's3' in event['Records'][0]
        and 'ObjectCreated' in event['Records'][0]['eventName']):

        return 's3'

    return 'unknown'


def _get_s3_data(bucket, key):
    '''
    This function gets a specific log file from the given S3 bucket and
    decompresses it.
    '''
    s3_client = boto3.client('s3')
    data = s3_client.get_object(Bucket=bucket, Key=key)['Body'].read()

    if key.split('.')[-1] == 'gz':
        data = gzip.GzipFile(fileobj=StringIO(data)).read()

    return data


def _send_log_entry(log_entry, context):
    '''
    This function sends the given log entry (and Lambda function's execution
    context) to New Relic Infrastructure's ingest service, retrying the request
    if needed.
    '''
    data = {
        'context': {
            'function_name': context.function_name,
            'invoked_function_arn': context.invoked_function_arn,
            'log_group_name': context.log_group_name,
            'log_stream_name': context.log_stream_name
        },
        'entry': log_entry
    }

    @http_retryable
    def do_request():
        request = urllib2.Request(INGEST_SERVICE_URL, json.dumps(data))
        request.add_header('X-License-Key', _get_license_key())
        return urllib2.urlopen(request)

    try:
        response = do_request()
    except MaxRetriesException:
        print('Retry limit reached. Failed to send log entry.')
    except BadRequestException as e:
        print('Bad request: {}. Review your license key.'.format(e.message))
    else:
        print('Log entry sent. Response code: {}'.format(response.getcode()))


def _get_license_key():
    '''
    This functions gets encrypted New Relic's license key from env vars and
    decrypts it using KMS.
    '''
    kms_client = boto3.client('kms')
    encrypted_license_key = os.environ['LICENSE_KEY']

    return kms_client.decrypt(
        CiphertextBlob=b64decode(encrypted_license_key)).get('Plaintext')


def lambda_handler(event, context):
    '''
    This is the Lambda handler, which is called when the function is invoked.
    Changing the name of this function will require changes in Lambda
    function's configuration.
    '''
    log_type = _get_log_type(event)

    if log_type == 'cw_logs':
        # CloudWatch Log entries are compressed and encoded in Base64
        log_entry = gzip.GzipFile(fileobj=StringIO(
            event['awslogs']['data'].decode('base64'))).read()
        _send_log_entry(log_entry, context)

    elif log_type == 's3':
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key']

        data = _get_s3_data(bucket, key)

        # There are many log entries in a log file, so send them one by one
        for log_line in data.splitlines():
            _send_log_entry(log_line, context)

    else:
        print('Not supported')
        print(event)
