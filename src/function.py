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

This Lambda function receives log entries from CloudWatch Logs
and pushes them to New Relic Infrastructure - Cloud integrations.

It expects to be invoked based on CloudWatch Logs streams.

New Relic's license key must be encrypted using KMS following these
instructions:

1. After creating te Lambda based on the Blueprint, select it and open the
Environment Variables section.

2. Check that the "LICENSE_KEY" environment variable if properly filled-in.

3. If you changed anything, go to the start of the page and press "Save".
Logs should start to be processed by the Lambda. To check if everything is
functioning properly you can check the Monitoring tab and CloudWatch Logs.

For more detailed documentation, check New Relic's documentation site:
https://docs.newrelic.com/
'''
import os
import gzip
import json
import re
import datetime

from urllib import request
from base64 import b64decode
from enum import Enum

import aiohttp
import asyncio

try:
    import newrelic.agent
except ImportError:
    pass
else:
    # The agent shouldn't be running on this function. Ensure it is shutdown.
    newrelic.agent.shutdown_agent()

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
# Max length in bytes of the payload
MAX_PAYLOAD_SIZE = 1000 * 1024

VPC_LOG_GROUP_PATTERN = re.compile(r'"logGroup":\s*"/aws/vpc/flow-logs"')
LAMBDA_LOG_GROUP_PATTERN = re.compile(r'"logGroup":\s*"/aws/lambda/')
LAMBDA_NR_MONITORING_PATTERN = re.compile(r'"NR_LAMBDA_MONITORING\\?"')
REPORT_PATTERN = re.compile("REPORT RequestId:")


class EntryType(Enum):
    VPC = "vpc"
    LAMBDA = "lambda"
    OTHER = "other"


INGEST_SERVICE_VERSION = 'v1'
US_LOGGING_INGEST_HOST = 'https://log-api.newrelic.com/log/v1'
EU_LOGGING_INGEST_HOST = 'https://log-api.eu.newrelic.com/log/v1'
US_INFRA_INGEST_SERVICE_HOST = 'https://cloud-collector.newrelic.com'
EU_INFRA_INGEST_SERVICE_HOST = 'https://cloud-collector.eu01.nr-data.net'
INFRA_INGEST_SERVICE_PATHS = {
    EntryType.LAMBDA: "/aws/lambda",
    EntryType.VPC: "/aws/vpc",
    EntryType.OTHER: "/aws",
}

LAMBDA_REQUEST_ID_REGEX = re.compile(
    "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
LOGGING_LAMBDA_VERSION = '1.0.2'
LOGGING_PLUGIN_METADATA = {
    'type': 'lambda',
    'version': LOGGING_LAMBDA_VERSION
}


class MaxRetriesException(Exception):
    pass


class BadRequestException(Exception):
    pass


async def http_post(session, url, data, headers):
    def _format_error(e, text):
        return '{}. {}'.format(e, text)

    backoff = INITIAL_BACKOFF
    retries = 0

    while retries < MAX_RETRIES:
        if retries > 0:
            print('Retrying in {} seconds'.format(backoff))
            await asyncio.sleep(backoff)
            backoff *= BACKOFF_MULTIPLIER

        retries += 1

        try:
            resp = await session.post(url, data=data, headers=headers)
            resp.raise_for_status()
            return resp.status, resp.url
        except aiohttp.ClientResponseError as e:
            if e.status == 400:
                raise BadRequestException(
                    _format_error(e, 'Unexpected payload'))
            elif e.status == 403:
                raise BadRequestException(
                    _format_error(e, 'Review your license key'))
            elif e.status == 404:
                raise BadRequestException(_format_error(
                    e, 'Review the region endpoint'))
            elif e.status == 429:
                print('There was a {} error. Reason: {}'.format(e.status, e.message))
                # Now retry the request
            elif 400 <= e.status < 500:
                raise BadRequestException(e)

    raise MaxRetriesException()


def _filter_log_lines(log_entry):
    """
    The EntryType.LAMBDA check guarantees that we'll be left with at least one log after filtering
    """
    log_entry_json = json.loads(log_entry)
    final_log_events = []
    for event in log_entry_json['logEvents']:
        message = event['message']
        if REPORT_PATTERN.search(message) or LAMBDA_NR_MONITORING_PATTERN.search(message):
            final_log_events.append(event)

    log_entry_json['logEvents'] = final_log_events
    return json.dumps(log_entry_json)


async def _send_log_entry(log_entry, context):
    '''
    This function sends the log entry to New Relic Infrastructure's ingest
    server. If it is necessary, entries will be split in different payloads
    Log entry is sent along with the Lambda function's execution context
    '''
    entry_type = _get_entry_type(log_entry)

    context = {
        'function_name': context.function_name,
        'invoked_function_arn': context.invoked_function_arn,
        'log_group_name': context.log_group_name,
        'log_stream_name': context.log_stream_name
    }

    async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=3)
    ) as session:
        # Both Infrastructure and Logging require a "LICENSE_KEY" environment variable.
        # In order to send data to the Infrastructure Pipeline, the customer doesn't need
        # to do anything. To disable it, they'll set "INFRA_ENABLED" to "false".
        # To send data to the Logging Pipeline, an environment variable called "LOGGING_ENABLED"
        # is required and needs to be set to "true". To disable it, they don't need to do anything,
        # it is disabled by default
        # Instruction for how to find these keys are in the README.md
        requests = []
        if _infra_enabled():
            if entry_type == EntryType.LAMBDA:
                # If this is one of our lambda entries, we should only send the log lines we
                # actually care about
                data = {
                    'context': context,
                    'entry': _filter_log_lines(log_entry)
                }
            else:
                # VPC logs are infra requests that aren't Lambda invocations
                data = {
                    'context': context,
                    'entry': log_entry
                }
            for payload in _generate_payloads(data, _split_infra_payload):
                requests.append(_send_payload(
                    _get_infra_request_creator(entry_type, payload), session, True))

        if _logging_enabled():
            data = {
                'context': context,
                'entry': log_entry
            }
            for payload in _generate_payloads(_package_log_payload(data), _split_log_payload):
                requests.append(_send_payload(_get_logging_request_creator(payload), session))
        return await asyncio.gather(*requests)


async def _send_payload(request_creator, session, retry=False):
    try:
        req = request_creator()
        status, url = await http_post(session, req.get_full_url(), req.data, req.headers)
    except MaxRetriesException as e:
        print('Retry limit reached. Failed to send log entry.')
        if retry:
            raise e
    except BadRequestException as e:
        print(e)
    else:
        print('Log entry sent. Response code: {}. url: {}'.format(status, url))
        return status


def _generate_payloads(data, split_function):
    '''
    Return a list of payloads to be sent to New Relic.
    This method usually returns a list of one element, but can be bigger if the
    payload size is too big
    '''
    payload = gzip.compress(json.dumps(data).encode())

    if (len(payload) < MAX_PAYLOAD_SIZE):
        return [payload]

    split_data = split_function(data)
    return _generate_payloads(split_data[0], split_function) + \
        _generate_payloads(split_data[1], split_function)


def _get_license_key(license_key=None):
    '''
    This functions gets New Relic's license key from env vars.
    '''
    if license_key:
        return license_key

    return os.getenv('LICENSE_KEY', '')


def _debug_logging_enabled():
    '''
    Determines whether or not debug logging should be enabled based on the env var.
    Defaults to false.
    '''
    enable_debug = os.getenv('DEBUG_LOGGING_ENABLED', 'false').lower()
    return enable_debug == 'true'


##############
#  NR Infra  #
##############


def _infra_enabled():
    '''
    This function returns whether to send info to New Relic Infrastructure.
    Enabled by default.
    '''
    enable_infra = os.getenv('INFRA_ENABLED', 'true').lower()
    return enable_infra == 'true'


def _get_infra_request_creator(entry_type, payload, ingest_host=None, license_key=None):
    def create_request():
        req = request.Request(_get_infra_ingest_service_url(
            entry_type, ingest_host), payload)
        req.add_header('X-License-Key', _get_license_key(license_key))
        req.add_header('Content-Encoding', 'gzip')
        return req

    return create_request


def _get_infra_ingest_service_url(entry_type, ingest_host=None):
    '''
    Returns the ingest_service_url.
    This is a concatenation of the HOST + PATH + VERSION
    '''
    if ingest_host is None:
        ingest_host = _get_infra_ingest_service_host()

    path = INFRA_INGEST_SERVICE_PATHS[entry_type]
    return ingest_host + path + '/' + INGEST_SERVICE_VERSION


def _get_entry_type(log_entry):
    '''
    Returns the EntryType of the entry based on some text found in its value.
    '''
    if VPC_LOG_GROUP_PATTERN.search(log_entry):
        return EntryType.VPC
    elif LAMBDA_LOG_GROUP_PATTERN.search(log_entry) \
            and LAMBDA_NR_MONITORING_PATTERN.search(log_entry):
        return EntryType.LAMBDA
    else:
        return EntryType.OTHER


def _get_infra_ingest_service_host():
    '''
    Service url is determined by the lincese key's region.
    Any other URL could be passed by using the NR_INFRA_ENDPOINT env var.
    '''
    region = 'EU' if _get_license_key().startswith('eu') else 'US'
    custom_url = os.getenv('NR_INFRA_ENDPOINT')

    if custom_url:
        return custom_url
    elif region == 'EU':
        return EU_INFRA_INGEST_SERVICE_HOST

    return US_INFRA_INGEST_SERVICE_HOST


def _split_infra_payload(data):
    '''
    When data size is bigger than supported payload, it is divided in two
    different requests
    '''
    context = data['context']
    entry = json.loads(data['entry'])
    logEvents = entry['logEvents']
    half = len(logEvents) // 2

    return [
        _reconstruct_infra_data(context, entry, logEvents[:half]),
        _reconstruct_infra_data(context, entry, logEvents[half:])
    ]


def _reconstruct_infra_data(context, entry, logEvents):
    entry['logEvents'] = logEvents
    return {
        'context': context,
        'entry': json.dumps(entry)
    }


################
#  NR Logging  #
################


def _logging_enabled():
    '''
    This function returns whether to send info to New Relic Logging.
    Disabled by default.
    '''
    enable_logging = os.getenv('LOGGING_ENABLED', 'false').lower()
    return enable_logging == 'true'


def _get_logging_request_creator(payload, ingest_url=None, license_key=None):
    def create_request():
        req = request.Request(
            _get_logging_ingest_service_url(ingest_url), payload)
        req.add_header('X-License-Key', _get_license_key(license_key))
        req.add_header('X-Event-Source', 'logs')
        req.add_header('Content-Encoding', 'gzip')
        return req

    return create_request


def _get_logging_ingest_service_url(ingest_url=None):
    '''
    Service url is determined by the lincese key's region.
    Any other URL could be passed by using the NR_LOGGING_ENDPOINT env var.
    '''
    if ingest_url:
        return ingest_url

    region = 'EU' if _get_license_key().startswith('eu') else 'US'
    custom_url = os.getenv('NR_LOGGING_ENDPOINT')

    if custom_url:
        return custom_url
    elif region == 'EU':
        return EU_LOGGING_INGEST_HOST

    return US_LOGGING_INGEST_HOST


def _package_log_payload(data):
    '''
    Packages up a MELT request for log messages
    '''
    entry = json.loads(data["entry"])
    log_events = entry["logEvents"]
    log_messages = []

    for log_event in log_events:
        log_message = {
            'message': log_event['message'],
            'timestamp': log_event['timestamp'],
            'attributes': {
                'aws': {
                }
            }
        }

        for event_key in log_event:
            if event_key != 'id' and event_key != 'message' and event_key != 'timestamp':
                log_message['attributes'][event_key] = log_event[event_key]

        if '/aws/lambda' in entry['logGroup']:
            match = LAMBDA_REQUEST_ID_REGEX.search(log_event['message'])
            if match and match.group(0):
                log_message['attributes']['aws']['lambda_request_id'] = match.group(0)

        log_messages.append(log_message)

    packaged_payload = [{
        'common': {
            'attributes': {
                'plugin': LOGGING_PLUGIN_METADATA,
                'aws': {
                    'logStream': entry['logStream'],
                    'logGroup': entry['logGroup'],
                }
            }
        },
        'logs': log_messages
    }]

    return packaged_payload


def _split_log_payload(payload):
    '''
    When data size is bigger than supported payload, it is divided in two
    different requests
    '''
    common = payload[0]['common']
    logs = payload[0]['logs']
    half = len(logs) // 2

    return [
        _reconstruct_log_payload(common, logs[:half]),
        _reconstruct_log_payload(common, logs[half:])
    ]


def _reconstruct_log_payload(common, logs):
    return [{
        'common': common,
        'logs': logs
    }]


####################
#  Lambda handler  #
####################


def lambda_handler(event, context):
    '''
    This is the Lambda handler, which is called when the function is invoked.
    Changing the name of this function will require changes in Lambda
    function's configuration.
    '''
    # CloudWatch Log entries are compressed and encoded in Base64
    event_data = b64decode(event['awslogs']['data'])
    log_entry = gzip.decompress(event_data).decode('utf-8')

    # output additional helpful info if debug logging is enabled
    # not enabled by default since parsing into json might be slow
    if _debug_logging_enabled():
        log_entry_json = json.loads(log_entry)
        # calling '[0]' without a safety check looks sketchy, but Cloudwatch is never going
        # to send us a log without at least one event
        print('logGroup: {}, logStream: {}, timestamp: {}'.format(
            log_entry_json['logGroup'], log_entry_json['logStream'],
            datetime.datetime.fromtimestamp(
                log_entry_json['logEvents'][0]['timestamp']/1000.0)))

    asyncio.run(_send_log_entry(log_entry, context))
    # This makes it possible to chain this CW log consumer with others using a success destination
    return event
