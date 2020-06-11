import gzip
import json
import os
import pprint
import pytest
import uuid

from base64 import b64decode
from mock import patch
from src import function
from test.mock_http_response import MockHttpResponse
from test.aws_log_events import AwsLogEvents

import asyncio
from asynctest import CoroutineMock

US_URL = "https://log-api.newrelic.com/log/v1"
EU_URL = "https://log-api.eu.newrelic.com/log/v1"
OTHER_URL = "http://some-other-endpoint/logs/v1"


timestamp = 1548935491174
logging_enabled = "true"
infra_enabled = "false"  # These tests just test logging
license_key = "testlicensekey"
license_key_eu = "eutestlicensekey"
log_group_name = "/aws/lambda/sam-node-test-dev-triggered"
log_stream_name = "2019/01/31/[$LATEST]fe9b6a749a854acb95af7951c44a79e0"
aws_log_events = AwsLogEvents(timestamp, log_group_name, log_stream_name)
aws_vpc_log_events = AwsLogEvents(timestamp, "/aws/vpc/flow-logs", log_stream_name)
aws_rds_enhanced_log_events = AwsLogEvents(timestamp, "RDSOSMetrics", log_stream_name)

context = type("SomeTypeOfContext", (object,), {})()
context.function_name = "function-1"
context.invoked_function_arn = "arn-1"
context.log_group_name = log_group_name
context.log_stream_name = log_stream_name


@pytest.fixture(autouse=True)
def set_up():
    # Default environment variables needed by most tests
    os.environ["INFRA_ENABLED"] = infra_enabled
    os.environ["LOGGING_ENABLED"] = logging_enabled
    os.environ["LICENSE_KEY"] = license_key

    function.INITIAL_BACKOFF = 0.1


@pytest.fixture
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_aio_post():
    with patch("aiohttp.ClientSession.post", new=CoroutineMock()) as mocked_aio_post:
        yield mocked_aio_post


@patch.dict(
    os.environ,
    {"INFRA_ENABLED": infra_enabled, "LOGGING_ENABLED": logging_enabled},
    clear=True,
)
def test_logging_has_default_nr_endpoint():
    assert function._get_logging_endpoint() == US_URL


@patch.dict(
    os.environ,
    {
        "INFRA_ENABLED": infra_enabled,
        "LOGGING_ENABLED": logging_enabled,
        "NR_LOGGING_ENDPOINT": OTHER_URL,
    },
    clear=True,
)
def test_logging_can_override_nr_endpoint():
    assert function._get_logging_endpoint() == OTHER_URL


@patch.dict(
    os.environ,
    {
        "INFRA_ENABLED": infra_enabled,
        "LOGGING_ENABLED": logging_enabled,
        "LICENSE_KEY": license_key_eu,
    },
    clear=True,
)
def test_logging_has_eu_nr_endpoint():
    assert function._get_logging_endpoint() == EU_URL


def test_proper_headers_are_added(mock_aio_post):
    mock_aio_post.return_value = aio_post_response()
    message_1 = "Test Message 1"
    event = aws_log_events.create_aws_event([message_1])

    function.lambda_handler(event, context)

    # Note that header names are somehow lower-cased
    mock_aio_post.assert_called()
    headers = mock_aio_post.call_args[1]["headers"]
    assert headers["X-license-key"] == license_key
    assert headers["X-event-source"] == "logs"
    assert headers["Content-encoding"] == "gzip"


def test_filter_log_lines():
    message_1 = "START RequestId: b3c55437-3847-4230-a1ed-0e94425372e8 Version: $LATEST"
    message_2 = '[1,"NR_LAMBDA_MONITORING","H4sIAImox"]'
    message_3 = "END RequestId: b3c55437-3847-4230-a1ed-0e94425372e8"
    message_4 = (
        "REPORT RequestId: b3c55437-3847-4230-a1ed-0e94425372e8	Duration: 245.44 ms"
    )
    messages = [message_1, message_2, message_3, message_4]
    assert len(messages) == 4

    event = aws_log_events.create_aws_event(messages)
    # CloudWatch Log entries are compressed and encoded in Base64
    event_data = b64decode(event["awslogs"]["data"])
    log_entry = json.loads(gzip.decompress(event_data).decode("utf-8"))
    filtered_log_entry = function._filter_log_lines(log_entry)
    pprint.pprint(filtered_log_entry)

    assert len(filtered_log_entry["logEvents"]) == 2
    assert filtered_log_entry["logEvents"][0]["message"].startswith("[1,")
    assert filtered_log_entry["logEvents"][1]["message"].startswith("REPORT")


@patch.dict(
    os.environ, {"LOGGING_ENABLED": "false", "LICENSE_KEY": license_key}, clear=True
)
def test_log_line_filtering(mock_aio_post):
    # we don't want logging enabled 'cause that saves all messages, interesting or not
    mock_aio_post.return_value = aio_post_response()
    message_1 = "START RequestId: b3c55437-3847-4230-a1ed-0e94425372e8 Version: $LATEST"
    message_2 = '[1,"NR_LAMBDA_MONITORING","H4sIAImox"]'
    message_3 = "END RequestId: b3c55437-3847-4230-a1ed-0e94425372e8"
    message_4 = (
        "REPORT RequestId: b3c55437-3847-4230-a1ed-0e94425372e8	Duration: 245.44 ms"
    )
    message_5 = (
        "2020-02-04T00:26:18.068Z b3c55437-3847-4230-a1ed-0e94425372e8 Task timed out"
        " after 3.00 seconds"
    )
    messages = [message_1, message_2, message_3, message_4, message_5]
    assert len(messages) == 5

    # log entries are gzipped and base64 encoded and inside another json object
    event = aws_log_events.create_aws_event(messages)

    function.lambda_handler(event, context)

    # Note that header names are somehow lower-cased
    mock_aio_post.assert_called()
    assert (
        mock_aio_post.call_args[0][0]
        == "https://cloud-collector.newrelic.com/aws/lambda/v1"
    )
    data = mock_aio_post.call_args[1]["data"]
    entry = gunzip_json_object(data)["entry"]
    entry_json = json.loads(entry)
    assert len(entry_json["logEvents"]) == 3
    assert entry_json["logEvents"][0]["message"].startswith("[1,")
    assert entry_json["logEvents"][1]["message"].startswith("REPORT")
    assert "Task timed out" in entry_json["logEvents"][2]["message"]
    headers = mock_aio_post.call_args[1]["headers"]
    assert headers["X-license-key"] == license_key
    assert headers["Content-encoding"] == "gzip"


@patch.dict(
    os.environ, {"LOGGING_ENABLED": "false", "LICENSE_KEY": license_key}, clear=True
)
def test_log_line_filtering_no_agent_data(mock_aio_post):
    # we don't want logging enabled 'cause that saves all messages, interesting or not
    mock_aio_post.return_value = aio_post_response()
    message_1 = "START RequestId: b3c55437-3847-4230-a1ed-0e94425372e8 Version: $LATEST"
    message_2 = "some garbage"
    message_3 = "END RequestId: b3c55437-3847-4230-a1ed-0e94425372e8"
    message_4 = (
        "REPORT RequestId: b3c55437-3847-4230-a1ed-0e94425372e8	Duration: 245.44 ms"
    )
    message_5 = (
        "2020-02-04T00:26:18.068Z b3c55437-3847-4230-a1ed-0e94425372e8 Task timed out"
        " after 3.00 seconds"
    )
    messages = [message_1, message_2, message_3, message_4, message_5]
    assert len(messages) == 5

    # log entries are gzipped and base64 encoded and inside another json object
    event = aws_log_events.create_aws_event(messages)

    function.lambda_handler(event, context)

    # Note that header names are somehow lower-cased
    mock_aio_post.assert_called()
    assert (
        mock_aio_post.call_args[0][0]
        == "https://cloud-collector.newrelic.com/aws/lambda/v1"
    )
    data = mock_aio_post.call_args[1]["data"]
    entry = gunzip_json_object(data)["entry"]
    entry_json = json.loads(entry)
    assert len(entry_json["logEvents"]) == 2
    assert entry_json["logEvents"][0]["message"].startswith("REPORT")
    assert "Task timed out" in entry_json["logEvents"][1]["message"]
    headers = mock_aio_post.call_args[1]["headers"]
    assert headers["X-license-key"] == license_key
    assert headers["Content-encoding"] == "gzip"


@patch.dict(
    os.environ, {"LOGGING_ENABLED": "false", "LICENSE_KEY": license_key}, clear=True
)
def test_log_line_filtering_oom(mock_aio_post):
    # we don't want logging enabled 'cause that saves all messages, interesting or not
    mock_aio_post.return_value = aio_post_response()
    message_1 = "START RequestId: b3c55437-3847-4230-a1ed-0e94425372e8 Version: $LATEST"
    message_2 = "some garbage"
    message_3 = "END RequestId: b3c55437-3847-4230-a1ed-0e94425372e8"
    message_4 = (
        "REPORT RequestId: b3c55437-3847-4230-a1ed-0e94425372e8	Duration: 245.44 ms"
    )
    message_5 = (
        "RequestId: b3c55437-3847-4230-a1ed-0e94425372e8 Error: "
        "Runtime exited with error: signal: killed\n"
        "Runtime.ExitError\n"
    )
    messages = [message_1, message_2, message_3, message_4, message_5]
    assert len(messages) == 5

    # log entries are gzipped and base64 encoded and inside another json object
    event = aws_log_events.create_aws_event(messages)

    function.lambda_handler(event, context)

    # Note that header names are somehow lower-cased
    mock_aio_post.assert_called()
    assert (
        mock_aio_post.call_args[0][0]
        == "https://cloud-collector.newrelic.com/aws/lambda/v1"
    )
    data = mock_aio_post.call_args[1]["data"]
    entry = gunzip_json_object(data)["entry"]
    entry_json = json.loads(entry)
    assert len(entry_json["logEvents"]) == 2
    assert entry_json["logEvents"][0]["message"].startswith("REPORT")
    assert "Error: Runtime exited" in entry_json["logEvents"][1]["message"]
    headers = mock_aio_post.call_args[1]["headers"]
    assert headers["X-license-key"] == license_key
    assert headers["Content-encoding"] == "gzip"


@patch.dict(
    os.environ, {"LOGGING_ENABLED": "false", "LICENSE_KEY": license_key}, clear=True
)
def test_vpc_flow_log(mock_aio_post):
    # we don't want logging enabled 'cause that saves all messages, interesting or not
    mock_aio_post.return_value = aio_post_response()
    message_1 = "I have no idea"
    message_2 = "what the content of a VPC flow log"
    message_3 = "is like"
    messages = [message_1, message_2, message_3]
    assert len(messages) == 3

    # log entries are gzipped and base64 encoded and inside another json object
    event = aws_vpc_log_events.create_aws_event(messages)

    function.lambda_handler(event, context)

    # Note that header names are somehow lower-cased
    mock_aio_post.assert_called()
    assert (
        mock_aio_post.call_args[0][0]
        == "https://cloud-collector.newrelic.com/aws/vpc/v1"
    )
    data = mock_aio_post.call_args[1]["data"]
    entry = gunzip_json_object(data)["entry"]
    entry_json = json.loads(entry)
    assert len(entry_json["logEvents"]) == 3
    assert entry_json["logEvents"][0]["message"] == message_1
    assert entry_json["logEvents"][1]["message"] == message_2
    assert entry_json["logEvents"][2]["message"] == message_3
    headers = mock_aio_post.call_args[1]["headers"]
    assert headers["X-license-key"] == license_key
    assert headers["Content-encoding"] == "gzip"


@patch.dict(
    os.environ, {"LOGGING_ENABLED": "false", "LICENSE_KEY": license_key}, clear=True
)
def test_rds_enhanced_metrics(mock_aio_post):
    # we don't want logging enabled 'cause that saves all messages, interesting or not
    mock_aio_post.return_value = aio_post_response()
    message_1 = "This is a RDS"
    message_2 = "Enhanced metrics"
    message_3 = "message with a lot of data"
    messages = [message_1, message_2, message_3]
    assert len(messages) == 3

    # log entries are gzipped and base64 encoded and inside another json object
    event = aws_rds_enhanced_log_events.create_aws_event(messages)

    function.lambda_handler(event, context)

    # Note that header names are somehow lower-cased
    mock_aio_post.assert_called()
    assert (
        mock_aio_post.call_args[0][0] == "https://cloud-collector.newrelic.com/aws/v1"
    )
    data = mock_aio_post.call_args[1]["data"]
    entry = gunzip_json_object(data)["entry"]
    entry_json = json.loads(entry)
    assert len(entry_json["logEvents"]) == 3
    assert entry_json["logEvents"][0]["message"] == message_1
    assert entry_json["logEvents"][1]["message"] == message_2
    assert entry_json["logEvents"][2]["message"] == message_3
    headers = mock_aio_post.call_args[1]["headers"]
    assert headers["X-license-key"] == license_key
    assert headers["Content-encoding"] == "gzip"


def test_message_fields_in_body(mock_aio_post):
    mock_aio_post.return_value = aio_post_response()
    message = "Test Message 1"
    event = aws_log_events.create_aws_event([message])

    function.lambda_handler(event, context)

    mock_aio_post.assert_called()
    data = mock_aio_post.call_args[1]["data"]
    messages = gunzip_json_object(data)[0]["logs"]
    assert len(messages) == 1
    assert messages[0]["timestamp"] == timestamp
    assert messages[0]["message"] == message


@patch.dict(
    os.environ,
    {
        "INFRA_ENABLED": infra_enabled,
        "LOGGING_ENABLED": logging_enabled,
        "LICENSE_KEY": license_key,
    },
    clear=True,
)
@patch("src.function.MAX_PAYLOAD_SIZE", 1000)
def test_big_payloads_are_split(mock_aio_post):
    mock_aio_post.side_effect = [aio_post_response(), aio_post_response()]
    messages = []

    message_count = 500
    for message_index in range(message_count):
        messages.append("Test Message %s" % (message_index))
    assert (
        len(json.dumps(messages)) > function.MAX_PAYLOAD_SIZE
    ), "We do not have enough test data to force a split"
    event = aws_log_events.create_aws_event(messages)

    function.lambda_handler(event, context)

    # Payload should be split into multiple calls
    assert mock_aio_post.call_count > 1

    # Each call body size should be less than the max payload size
    observed_messages = []
    for request_index in range(mock_aio_post.call_count):
        data = mock_aio_post.call_args_list[request_index][1]["data"]
        assert len(data) < function.MAX_PAYLOAD_SIZE
        for observed_message in gunzip_json_object(data)[0]["logs"]:
            observed_messages.append(observed_message["message"])

    # The messages sent across all calls should be the same as in the original event
    assert len(observed_messages) == message_count
    for message_index in range(message_count):
        print(observed_messages[message_index])
        print(messages[message_index])
        assert observed_messages[message_index] == messages[message_index]


# Note: not sure why, this is just the way the production code behaves
def test_id_field_is_not_added(mock_aio_post):
    mock_aio_post.return_value = aio_post_response()
    message = "Test Message 1"
    event = aws_log_events.create_aws_event([message])

    function.lambda_handler(event, context)

    mock_aio_post.assert_called()
    data = mock_aio_post.call_args[1]["data"]
    messages = gunzip_json_object(data)[0]["logs"]
    assert len(messages) == 1
    assert "id" not in messages[0]


def test_multiple_messages(mock_aio_post):
    mock_aio_post.return_value = aio_post_response()
    message_1 = "Test Message 1"
    message_2 = "Test Message 2"
    message_3 = "Test Message 3"
    event = aws_log_events.create_aws_event([message_1, message_2, message_3])

    function.lambda_handler(event, context)

    mock_aio_post.assert_called()
    data = mock_aio_post.call_args[1]["data"]
    messages = gunzip_json_object(data)[0]["logs"]
    assert len(messages) == 3
    assert messages[0]["message"] == message_1
    assert messages[1]["message"] == message_2
    assert messages[2]["message"] == message_3


def test_when_first_call_fails_code_should_retry(mock_aio_post):
    # First fail, and then succeed
    mock_aio_post.side_effect = [urlopen_error_response(), aio_post_response()]
    event = aws_log_events.create_aws_event(["Test Message 1"])

    function.lambda_handler(event, context)

    assert mock_aio_post.call_count == 2


def test_when_first_two_calls_fail_code_should_retry(mock_aio_post):
    # First two fail, and then third succeeds
    mock_aio_post.side_effect = [
        urlopen_error_response(),
        urlopen_error_response(),
        aio_post_response(),
    ]
    event = aws_log_events.create_aws_event(["Test Message 1"])

    function.lambda_handler(event, context)

    assert mock_aio_post.call_count == 3


def test_logs_have_logstream_and_loggroup(mock_aio_post):
    mock_aio_post.return_value = aio_post_response()
    message = "Test Message 1"
    event = aws_log_events.create_aws_event([message])

    function.lambda_handler(event, context)

    mock_aio_post.assert_called()
    data = mock_aio_post.call_args[1]["data"]
    common = gunzip_json_object(data)[0]["common"]
    assert common["attributes"]["aws"]["logGroup"] == log_group_name
    assert common["attributes"]["aws"]["logStream"] == log_stream_name


def test_logs_have_plugin_info(mock_aio_post):
    mock_aio_post.return_value = aio_post_response()
    message = "Test Message 1"
    event = aws_log_events.create_aws_event([message])

    function.lambda_handler(event, context)

    mock_aio_post.assert_called()
    data = mock_aio_post.call_args[1]["data"]
    body = gunzip_json_object(data)
    messages = body[0]["logs"]
    assert len(messages) == 1
    assert messages[0]["timestamp"] == timestamp
    assert messages[0]["message"] == message

    assert body[0]["common"]["attributes"]["plugin"] == function.LOGGING_PLUGIN_METADATA


def test_lambda_request_ids_are_extracted(mock_aio_post):
    mock_aio_post.return_value = aio_post_response()
    expected_request_id = str(uuid.uuid4())
    expected_request_id2 = str(uuid.uuid4())
    unexpected_request_id = str(uuid.uuid4())
    event = aws_log_events.create_aws_event(
        [
            "START RequestId: {} Version: $LATEST".format(expected_request_id),
            "2019-07-22T21:37:22.353Z {} Some Log Line with a random UUID".format(
                unexpected_request_id
            ),
            "2019-07-22T21:37:22.353Z Doesn't have a RequestId",
            "END RequestId: {}".format(expected_request_id),
            "START RequestId: {} Version: $LATEST".format(expected_request_id2),
        ]
    )
    function.lambda_handler(event, context)
    mock_aio_post.assert_called()
    data = mock_aio_post.call_args[1]["data"]
    messages = gunzip_json_object(data)[0]["logs"]
    assert len(messages) == 5
    assert messages[0]["timestamp"] == timestamp
    assert messages[0]["attributes"]["aws"]["lambda_request_id"] == expected_request_id
    assert messages[1]["timestamp"] == timestamp
    assert messages[1]["attributes"]["aws"]["lambda_request_id"] == expected_request_id
    assert messages[2]["timestamp"] == timestamp
    assert messages[2]["attributes"]["aws"]["lambda_request_id"] == expected_request_id
    assert messages[3]["timestamp"] == timestamp
    assert messages[3]["attributes"]["aws"]["lambda_request_id"] == expected_request_id
    assert messages[4]["timestamp"] == timestamp
    assert messages[4]["attributes"]["aws"]["lambda_request_id"] == expected_request_id2


async def aio_post_response():
    return MockHttpResponse("", 202)


def urlopen_error_response():
    return MockHttpResponse("", 429)


def gunzip_json_object(body_bytes):
    json_string = gzip.decompress(body_bytes).decode("utf-8")
    return json.loads(json_string)
