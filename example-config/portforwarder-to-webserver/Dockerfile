FROM my-linux-base

RUN apt-get update
RUN apt-get install -y socat

EXPOSE 1234
CMD socat TCP-LISTEN:1234,fork TCP:webserver:80
