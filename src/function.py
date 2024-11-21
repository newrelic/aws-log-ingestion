"""
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

1. After creating the Lambda based on the Blueprint, select it and open the
Environment Variables section.

2. Check that the "LICENSE_KEY" environment variable if properly filled-in.

3. If you changed anything, go to the start of the page and press "Save".
Logs should start to be processed by the Lambda. To check if everything is
functioning properly you can check the Monitoring tab and CloudWatch Logs.

For more detailed documentation, check New Relic's documentation site:
https://docs.newrelic.com/
"""

import datetime
import gzip
import json
import logging
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

from base64 import b64decode
from enum import Enum
from urllib import request

import aiohttp
import asyncio

logger = logging.getLogger()

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
# Decreasing these number could increase the probability of data loss.

# Upon receiving the following error codes, the request will be retried up to MAX_RETRIES times
RETRYABLE_ERROR_CODES = [408, 429]
# Maximum number of retries
MAX_RETRIES = 3
# Initial backoff (in seconds) between retries
INITIAL_BACKOFF = 1
# Multiplier factor for the backoff between retries
BACKOFF_MULTIPLIER = 2
# Max length in bytes of the payload
MAX_PAYLOAD_SIZE = 1000 * 1024
# Individual request timeout in seconds (non-configurable)
INDIVIDUAL_REQUEST_TIMEOUT_DURATION = 3
INDIVIDUAL_REQUEST_TIMEOUT = aiohttp.ClientTimeout(
    total=INDIVIDUAL_REQUEST_TIMEOUT_DURATION
)
# Session max processing time (non-configurable).
# Reserves a time buffer for logs to be formatted before being sent.
SESSION_MAX_PROCESSING_TIME = 1

LAMBDA_LOG_GROUP_PREFIX = os.getenv("NR_LAMBDA_LOG_GROUP_PREFIX", "/aws/lambda")
VPC_LOG_GROUP_PREFIX = os.getenv("NR_VPC_LOG_GROUP_PREFIX", "/aws/vpc/flow-logs")

LAMBDA_NR_MONITORING_PATTERN = re.compile(r'.*"NR_LAMBDA_MONITORING')
REPORT_PATTERN = re.compile("REPORT RequestId:")
TIMEOUT_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d+Z\s[\d\w-]+\sTask timed out after [\d.]+ seconds"
)
# Lines like this are generated by the Lambda service when it has to kill the function's runtime,
# e.g. for an out of memory error.
REQUEST_ID_PATTERN = re.compile(r"RequestId:\s([-a-zA-Z0-9]{36})\s(.*)", re.DOTALL)


class EntryType(Enum):
    VPC = "vpc"
    LAMBDA = "lambda"
    OTHER = "other"


INGEST_SERVICE_VERSION = "v1"
US_LOGGING_ENDPOINT = "https://log-api.newrelic.com/log/v1"
EU_LOGGING_ENDPOINT = "https://log-api.eu.newrelic.com/log/v1"
US_INFRA_ENDPOINT = "https://cloud-collector.newrelic.com"
EU_INFRA_ENDPOINT = "https://cloud-collector.eu01.nr-data.net"
INFRA_INGEST_SERVICE_PATHS = {
    EntryType.LAMBDA: "/aws/lambda",
    EntryType.VPC: "/aws/vpc",
    EntryType.OTHER: "/aws",
}

LAMBDA_REQUEST_ID_REGEX = re.compile(
    r"RequestId:\s"
    r"(?P<request_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)

LOGGING_LAMBDA_VERSION = "2.9.4"
LOGGING_PLUGIN_METADATA = {"type": "lambda", "version": LOGGING_LAMBDA_VERSION}

# Global cache for storing new relic license keys
LICENSE_KEY_CACHE = None


class MaxRetriesException(Exception):
    pass


class BadRequestException(Exception):
    pass


async def http_post(session, url, data, headers):
    def _format_error(e, text):
        return "{}. {}".format(e, text)

    backoff = INITIAL_BACKOFF
    retries = 0

    while retries < MAX_RETRIES:
        if retries > 0:
            logger.info("Retrying in {} seconds".format(backoff))
            await asyncio.sleep(backoff)
            backoff *= BACKOFF_MULTIPLIER

        retries += 1

        try:
            resp = await session.post(
                url, data=data, headers=headers, timeout=INDIVIDUAL_REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            return resp.status, resp.url
        except aiohttp.ClientResponseError as e:
            if e.status == 400:
                raise BadRequestException(_format_error(e, "Unexpected payload"))
            elif e.status == 403:
                raise BadRequestException(_format_error(e, "Review your license key"))
            elif e.status == 404:
                raise BadRequestException(
                    _format_error(e, "Review the region endpoint")
                )
            elif e.status in RETRYABLE_ERROR_CODES:
                logger.warning(f"There was a {e.status} error. Reason: {e.message}")
                # Now retry the request
                continue
            elif 400 <= e.status < 500:
                raise BadRequestException(e)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout on {url} at attempt {retries}/{MAX_RETRIES}")
            # Now retry the request
            continue

    raise MaxRetriesException()


def _filter_log_lines(log_entry):
    """
    The EntryType.LAMBDA check guarantees that we'll be left with at least one log after filtering
    """
    final_log_events = []
    for event in log_entry["logEvents"]:
        message = event["message"]
        if REPORT_PATTERN.match(message) or _is_lambda_message(message):
            final_log_events.append(event)

    ret = log_entry.copy()
    ret["logEvents"] = final_log_events
    return ret


def _calculate_session_timeout():
    # Request 0
    total = INDIVIDUAL_REQUEST_TIMEOUT_DURATION

    # Requests 1 to N-1
    backoff = INITIAL_BACKOFF
    for retry in range(MAX_RETRIES - 1):
        total += backoff + INDIVIDUAL_REQUEST_TIMEOUT_DURATION
        backoff *= BACKOFF_MULTIPLIER

    # Finally, add maximum worst-case-scenario expected processing time
    return total + SESSION_MAX_PROCESSING_TIME


async def _send_log_entry(log_entry, context):
    """
    This function sends the log entry to New Relic Infrastructure's ingest
    server. If it is necessary, entries will be split in different payloads
    Log entry is sent along with the Lambda function's execution context
    """
    entry_type = _get_entry_type(log_entry)

    context = {
        "function_name": context.function_name,
        "invoked_function_arn": context.invoked_function_arn,
        "log_group_name": context.log_group_name,
        "log_stream_name": context.log_stream_name,
    }

    session_timeout = _calculate_session_timeout()

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=session_timeout), trust_env=True
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
                    "context": context,
                    "entry": json.dumps(_filter_log_lines(log_entry)),
                }
            else:
                # VPC logs are infra requests that aren't Lambda invocations
                data = {"context": context, "entry": json.dumps(log_entry)}
            for payload in _generate_payloads(data, _split_infra_payload):
                requests.append(
                    _send_payload(
                        _get_infra_request_creator(entry_type, payload), session, True
                    )
                )

        if _logging_enabled():
            data = {"context": context, "entry": json.dumps(log_entry)}
            for payload in _generate_payloads(
                _package_log_payload(data), _split_log_payload
            ):
                requests.append(
                    _send_payload(_get_logging_request_creator(payload), session)
                )

        logger.debug("Sending data to New Relic.....")
        ini = time.perf_counter()
        result = await asyncio.gather(*requests)
        elapsed_millis = (time.perf_counter() - ini) * 1000
        logger.debug(f"Time elapsed to send to New Relic: {elapsed_millis:0.2f}ms")
        return result


async def _send_payload(request_creator, session, retry=False):
    try:
        req = request_creator()
        status, url = await http_post(
            session, req.get_full_url(), req.data, req.headers
        )
    except MaxRetriesException as e:
        logger.error("Retry limit reached. Failed to send log entry.")
        if retry:
            raise e
    except BadRequestException as e:
        logger.error(e)
    except asyncio.TimeoutError as e:
        logger.error("Session timed out. Failed to send log entry.")
        raise e
    except Exception as e:
        logger.error(f"Error occurred: {e}")
        raise e
    else:
        logger.info("Log entry sent. Response code: {}. url: {}".format(status, url))
        return status


def _generate_payloads(data, split_function):
    """
    Return a list of payloads to be sent to New Relic.
    This method usually returns a list of one element, but can be bigger if the
    payload size is too big
    """
    payload = gzip.compress(json.dumps(data).encode())

    if len(payload) < MAX_PAYLOAD_SIZE:
        return [payload]

    split_data = split_function(data)
    return _generate_payloads(split_data[0], split_function) + _generate_payloads(
        split_data[1], split_function
    )


def _get_license_key_source():
    """
    This function returns the source of the license key.
    LICENSE_KEY_SRC must be one of 'environment_var', 'ssm', or 'secrets_manager'.
    Defaults to 'environment_var'.
    """
    return os.getenv("LICENSE_KEY_SRC", "environment_var")


def _get_license_key(license_key=None):
    """
    This functions gets New Relic's license key from env vars.
    """
    if license_key:
        return license_key

    license_key_source = _get_license_key_source()

    if license_key_source == "ssm":
        return _get_license_key_from_ssm(os.getenv("LICENSE_KEY", ""))
    elif license_key_source == "secrets_manager":
        return _get_license_key_from_secrets_manager(os.getenv("LICENSE_KEY", ""))

    return os.getenv("LICENSE_KEY", "")


def _get_license_key_from_secrets_manager(secret_arn):
    """
    Fetches the secret value for the given secret ARN from AWS Secrets Manager.
    """
    global LICENSE_KEY_CACHE

    if not secret_arn:
        return ""

    enable_caching = os.getenv("ENABLE_CACHING", "false").lower() == "true"

    # Check cache first if caching is enabled
    if enable_caching and LICENSE_KEY_CACHE is not None:
        logger.info(
            "Using cached secret instead of fetching the license key from secrets manager"
        )
        return LICENSE_KEY_CACHE

    client = boto3.client("secretsmanager")

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_arn)
        logger.info("Successfully retrieved license key from Secrets Manager")
    except ClientError as e:
        logger.error(f"Unable to retrieve secret {secret_arn}: {e}")
        return ""

    if "SecretString" in get_secret_value_response:
        secret = get_secret_value_response["SecretString"]
    else:
        secret = b64decode(get_secret_value_response["SecretBinary"])

    # Cache the secret before returning if caching is enabled
    if enable_caching:
        LICENSE_KEY_CACHE = secret

    return "" if not secret else secret


def _get_license_key_from_ssm(parameter_path):
    """
    Fetches the parameter value for the given parameter path
    from AWS Systems Manager Parameter Store.
    """
    global LICENSE_KEY_CACHE

    if not parameter_path:
        return ""

    enable_caching = os.getenv("ENABLE_CACHING", "false").lower() == "true"

    # Check cache first if caching is enabled
    if enable_caching and LICENSE_KEY_CACHE is not None:
        logger.info(
            "Using cached parameter instead of fetching the license key from SSM"
        )
        return LICENSE_KEY_CACHE

    client = boto3.client("ssm")

    try:
        response = client.get_parameter(Name=parameter_path, WithDecryption=True)
        logger.info("Successfully retrieved license key from SSM")
        parameter_value = response["Parameter"]["Value"]
    except ClientError as e:
        logger.error(f"Unable to retrieve parameter {parameter_path}: {e}")
        raise e

    # Cache the parameter before returning if caching is enabled
    if enable_caching:
        LICENSE_KEY_CACHE = parameter_value

    return parameter_value


def _get_newrelic_tags(payload):
    """
    This functions gets New Relic's tags from env vars and adds it to the payload
    A tag is a key value pair. Multiple tags can be specified.
    Key and value are colon delimited. Multiple key value pairs are semi-colon delimited.
    e.g. env:prod;team:myTeam
    """
    nr_tags_str = os.getenv("NR_TAGS", "")
    nr_delimiter = os.getenv("NR_ENV_DELIMITER", ";")
    if nr_tags_str:
        nr_tags = dict(
            item.split(":")
            for item in nr_tags_str.split(nr_delimiter)
            if not item.startswith(tuple(["aws:", "plugin:"]))
        )
        payload[0]["common"]["attributes"].update(nr_tags)


def _debug_logging_enabled():
    """
    Determines whether or not debug logging should be enabled based on the env var.
    Defaults to false.
    """
    return os.getenv("DEBUG_LOGGING_ENABLED", "false").lower() == "true"


##############
#  NR Infra  #
##############


def _infra_enabled():
    """
    This function returns whether to send info to New Relic Infrastructure.
    Enabled by default.
    """
    return os.getenv("INFRA_ENABLED", "true").lower() == "true"


def _get_infra_request_creator(entry_type, payload, ingest_host=None, license_key=None):
    def create_request():
        req = request.Request(_get_infra_url(entry_type, ingest_host), payload)
        req.add_header("X-License-Key", _get_license_key(license_key))
        req.add_header("Content-Encoding", "gzip")
        return req

    return create_request


def _get_infra_url(entry_type, ingest_host=None):
    """
    Returns the ingest_service_url.
    This is a concatenation of the HOST + PATH + VERSION
    """
    if ingest_host is None:
        ingest_host = _get_infra_endpoint()

    path = INFRA_INGEST_SERVICE_PATHS[entry_type]
    return ingest_host + path + "/" + INGEST_SERVICE_VERSION


def _is_lambda_message(message):
    """
    Matches messages that are sufficient to report a Lambda invocation.
    REPORT lines are not sufficient, just nice to have.
    """
    return (
        LAMBDA_NR_MONITORING_PATTERN.match(message)
        or TIMEOUT_PATTERN.match(message)
        or REQUEST_ID_PATTERN.match(message)
    )


def _get_entry_type(log_entry):
    """
    Returns the EntryType of the entry based on some text found in its value.
    """
    log_group = log_entry["logGroup"]
    if log_group.startswith(VPC_LOG_GROUP_PREFIX):
        return EntryType.VPC
    elif log_group.startswith(LAMBDA_LOG_GROUP_PREFIX) and any(
        _is_lambda_message(event["message"]) for event in log_entry["logEvents"]
    ):
        return EntryType.LAMBDA
    return EntryType.OTHER


def _get_infra_endpoint():
    """
    Service url is determined by the license key's region.
    Any other URL could be passed by using the NR_INFRA_ENDPOINT env var.
    """
    if "NR_INFRA_ENDPOINT" in os.environ:
        return os.environ["NR_INFRA_ENDPOINT"]
    return (
        EU_INFRA_ENDPOINT if _get_license_key().startswith("eu") else US_INFRA_ENDPOINT
    )


def _split_infra_payload(data):
    """
    When data size is bigger than supported payload, it is divided in two
    different requests
    """
    context = data["context"]
    entry = json.loads(data["entry"])
    logEvents = entry["logEvents"]
    half = len(logEvents) // 2

    return [
        _reconstruct_infra_data(context, entry, logEvents[:half]),
        _reconstruct_infra_data(context, entry, logEvents[half:]),
    ]


def _reconstruct_infra_data(context, entry, logEvents):
    entry["logEvents"] = logEvents
    return {"context": context, "entry": json.dumps(entry)}


################
#  NR Logging  #
################


def _logging_enabled():
    """
    This function returns whether to send info to New Relic Logging.
    Disabled by default.
    """
    return os.getenv("LOGGING_ENABLED", "false").lower() == "true"


def _get_logging_request_creator(payload, ingest_url=None, license_key=None):
    def create_request():
        req = request.Request(_get_logging_endpoint(ingest_url), payload)
        req.add_header("X-License-Key", _get_license_key(license_key))
        req.add_header("X-Event-Source", "logs")
        req.add_header("Content-Encoding", "gzip")
        return req

    return create_request


def _set_console_logging_level():
    """
    Determines whether or not debug logging should be enabled based on the env var.
    Defaults to false.
    """
    if _debug_logging_enabled():
        logger.setLevel(logging.DEBUG)
        logger.debug("Enabled debug mode")
    else:
        logger.setLevel(logging.INFO)


def _get_logging_endpoint(ingest_url=None):
    """
    Service url is determined by the lincese key's region.
    Any other URL could be passed by using the NR_LOGGING_ENDPOINT env var.
    """
    if ingest_url:
        return ingest_url
    if "NR_LOGGING_ENDPOINT" in os.environ:
        return os.environ["NR_LOGGING_ENDPOINT"]
    return (
        EU_LOGGING_ENDPOINT
        if _get_license_key().startswith("eu")
        else US_LOGGING_ENDPOINT
    )


def _package_log_payload(data):
    """
    Packages up a MELT request for log messages
    """
    entry = json.loads(data["entry"])
    log_events = entry["logEvents"]
    log_messages = []
    lambda_request_id = None
    trace_id = ""

    for log_event in log_events:
        if LAMBDA_NR_MONITORING_PATTERN.match(log_event["message"]):
            trace_id = _get_trace_id(log_event["message"])

        log_message = {
            "message": log_event["message"],
            "timestamp": log_event["timestamp"],
            "attributes": {"aws": {}},
        }

        if trace_id:
            log_message["trace.id"] = trace_id

        for event_key in log_event:
            if event_key not in ("id", "message", "timestamp"):
                log_message["attributes"][event_key] = log_event[event_key]

        if entry["logGroup"].startswith(LAMBDA_LOG_GROUP_PREFIX):
            match = LAMBDA_REQUEST_ID_REGEX.search(log_event["message"])
            if match and match.group("request_id"):
                lambda_request_id = match.group("request_id")
            if lambda_request_id:
                log_message["attributes"]["aws"][
                    "lambda_request_id"
                ] = lambda_request_id

        log_messages.append(log_message)

    packaged_payload = [
        {
            "common": {
                "attributes": {
                    "plugin": LOGGING_PLUGIN_METADATA,
                    "aws": {
                        "logStream": entry["logStream"],
                        "logGroup": entry["logGroup"],
                    },
                }
            },
            "logs": log_messages,
        }
    ]

    _get_newrelic_tags(packaged_payload)

    return packaged_payload


def _split_log_payload(payload):
    """
    When data size is bigger than supported payload, it is divided in two
    different requests
    """
    common = payload[0]["common"]
    logs = payload[0]["logs"]
    half = len(logs) // 2

    return [
        _reconstruct_log_payload(common, logs[:half]),
        _reconstruct_log_payload(common, logs[half:]),
    ]


def _reconstruct_log_payload(common, logs):
    return [{"common": common, "logs": logs}]


def _get_trace_id(message_str):
    """
    message_str: str
        message = "[
            1,
            \"NR_LAMBDA_MONITORING\",
            \"base64.b64encode(gzip.compress(message)).decode("utf-8")\",
        ]"
    """

    def extract_trace_id(key):
        try:
            return data[key][2][0][0]["traceId"]
        except Exception:
            logger.debug(f"No trace ID found in {key}")
            return ""

    trace_id = ""
    try:
        message = json.loads(message_str)
        data_str = gzip.decompress(b64decode(message[2])).decode("utf-8")
        data = json.loads(data_str)["data"]

        trace_id = extract_trace_id("analytic_event_data")
        if trace_id:
            return trace_id
        else:
            return extract_trace_id("span_event_data")
    except Exception:
        logger.debug("Failed to decode payload")
        return trace_id


####################
#  Lambda handler  #
####################


def lambda_handler(event, context):
    """
    This is the Lambda handler, which is called when the function is invoked.
    Changing the name of this function will require changes in Lambda
    function's configuration.
    """

    _set_console_logging_level()

    # CloudWatch Log entries are compressed and encoded in Base64
    event_data = b64decode(event["awslogs"]["data"])
    log_entry_str = gzip.decompress(event_data).decode("utf-8")
    log_entry = json.loads(log_entry_str)

    # output additional helpful info if debug logging is enabled
    # not enabled by default since parsing into json might be slow
    # calling '[0]' without a safety check looks sketchy, but Cloudwatch is never going
    # to send us a log without at least one event
    logger.debug(
        "logGroup: {}, logStream: {}, timestamp: {}".format(
            log_entry["logGroup"],
            log_entry["logStream"],
            datetime.datetime.fromtimestamp(
                log_entry["logEvents"][0]["timestamp"] / 1000.0
            ),
        )
    )

    asyncio.run(_send_log_entry(log_entry, context))
    # This makes it possible to chain this CW log consumer with others using a success destination
    return event
