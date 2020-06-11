import aiohttp


class MockHttpResponse(object):
    def __init__(self, jsonBody, code):
        self.jsonBody = jsonBody
        self.status = code
        self.headers = {"content-type": "application/json; charset=utf-8"}
        self.url = "/aws/lambda/test"

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(None, None, status=self.status)

    def read(self):
        return self.jsonBody

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url
