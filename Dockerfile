FROM python:3.7
RUN apt-get update
RUN apt-get install -y zip

WORKDIR /build
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target .
COPY src .
RUN zip -r /out.zip .

CMD ["/bin/sh"]