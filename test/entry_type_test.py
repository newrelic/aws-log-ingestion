import os
import sys
import json

from src import function


# Adding parent directory to the path for finding 'src' directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_vpc_flow_logs_entry_type():
    # given
    entry = _getVpcFlowLogsEntry()
    # when
    entry_type = function._get_entry_type(entry)
    # then
    assert function.EntryType.VPC == entry_type


def test_lambda_sam_entry_type():
    # given
    entry = _loadJson("./test/events/entry_lambda_sam.json")
    # when
    entry_type = function._get_entry_type(entry)
    # then
    assert function.EntryType.LAMBDA == entry_type


def test_lambda_timeout_entry_type():
    # given
    entry = _loadJson("./test/events/entry_lambda_timeout.json")
    # when
    entry_type = function._get_entry_type(entry)
    # then
    assert function.EntryType.LAMBDA == entry_type


def test_lambda_oom_entry_type():
    # given
    entry = _loadJson("./test/events/entry_lambda_oom.json")
    # when
    entry_type = function._get_entry_type(entry)
    # then
    assert function.EntryType.LAMBDA == entry_type


def test_rds_entry_type():
    # given
    entry = _loadJson("./test/events/entry_rds.json")
    # when
    entry_type = function._get_entry_type(entry)
    # then
    assert function.EntryType.OTHER == entry_type


def test_vpc_flow_logs_url():
    # given
    entry = _getVpcFlowLogsEntry()
    entry_type = function._get_entry_type(entry)
    # when
    url = function._get_infra_url(entry_type)
    # then
    assert "https://cloud-collector.newrelic.com/aws/vpc/v1" == url


def test_lambda_url():
    # given
    entry = _getLambdaEntry()
    entry_type = function._get_entry_type(entry)
    # when
    url = function._get_infra_url(entry_type)
    # then
    assert "https://cloud-collector.newrelic.com/aws/lambda/v1" == url


def test_rds_url():
    # given
    entry = _getRdsEntry()
    entry_type = function._get_entry_type(entry)
    # when
    url = function._get_infra_url(entry_type)
    # then
    assert "https://cloud-collector.newrelic.com/aws/v1" == url


def _getVpcFlowLogsEntry():
    return _loadJson("./test/events/entry_vpc_flow_logs.json")


def _getLambdaEntry():
    return _loadJson("./test/events/entry_lambda_sam.json")


def _getRdsEntry():
    return _loadJson("./test/events/entry_rds.json")


def _loadJson(filename):
    with open(filename, "r") as f:
        return json.load(f)
