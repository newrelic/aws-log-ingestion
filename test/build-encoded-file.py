"""
Build a properly encoded payload to test log ingestion without needing to invoke
the lambda.
"""
import json
import sys
import gzip
import base64


# Returns a json string of encoded data
# File should *only* contain decoded and unzipped message payload from lambda function
def get_message_from_file(filename):
    with open(filename, "rb") as file:
        return file.read()


# Assumes the message payload is decoded and unzipped and is
# included with the rest of the json payload
def get_message_from_json(json_data, event_idx):
    # the third element of the list is the actual encoded message data
    return json.dumps(json_data["logEvents"][event_idx]["message"][2]).encode()


if __name__ == "__main__":
    argc = len(sys.argv)
    if argc != 3 and argc != 2:
        print("Usage: python build-test-input <ingestion file> [data file]")
        sys.exit(1)

    with open(sys.argv[1]) as ingestion_file:
        ingestion_data = json.load(ingestion_file)

        # [0] accesses the first event
        message = (
            get_message_from_json(ingestion_data, 0)
            if argc == 2
            else get_message_from_file(sys.argv[2])
        )
        encoded_message = [
            1,
            "NR_LAMBDA_MONITORING",
            base64.b64encode(gzip.compress(message)).decode("utf-8"),
        ]
        ingestion_data["logEvents"][0]["message"] = json.dumps(encoded_message)

        with open("temp.txt", "w") as temp:
            binary_data = base64.b64encode(
                gzip.compress(json.dumps(ingestion_data).encode())
            )
            final_json = {"awslogs": {}}
            final_json["awslogs"]["data"] = binary_data.decode("utf-8")
            temp.write(json.dumps(final_json))
