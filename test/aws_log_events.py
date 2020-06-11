import gzip
import json
from base64 import b64encode


class AwsLogEvents:
    def __init__(self, timestamp, log_group_name, log_stream_name):
        self.timestamp = timestamp
        self.log_group_name = log_group_name
        self.log_stream_name = log_stream_name

    def create_aws_event(self, messages):
        log_entry = self._create_aws_log_entry(messages)
        log_entry_json = json.dumps(log_entry).encode("utf-8")
        base64GzippedEntry = b64encode(gzip.compress(log_entry_json))
        return {"awslogs": {"data": base64GzippedEntry}}

    def _create_aws_log_entry(self, messages):
        return {
            "messageType": "DATA_MESSAGE",
            "owner": "463657938898",
            "logGroup": self.log_group_name,
            "logStream": self.log_stream_name,
            "subscriptionFilters": ["triggered"],
            "logEvents": self._create_aws_log_events(messages),
        }

    def _create_aws_log_events(self, messages):
        assert len(messages) < 1000000, "ID logic only handles up to 1,000,000 messages"
        log_events = []
        for i in range(0, len(messages)):
            log_events.append(
                {
                    "id": "34542415717632252900687466827843614893660878434223"
                    + str(i).zfill(6),
                    "timestamp": self.timestamp,
                    "message": messages[i],
                }
            )
        return log_events
