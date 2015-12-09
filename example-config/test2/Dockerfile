FROM my-linux-base

RUN apt-get update
RUN apt-get install -y socat


EXPOSE 1234
CMD socat -v tcp-l:1234,fork exec:'/bin/date'
