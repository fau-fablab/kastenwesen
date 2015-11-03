FROM my-linux-base

RUN apt-get update
RUN apt-get install -y netcat
RUN apt-get clean




EXPOSE 1234
CMD ["netcat", "-k", "-l", "-p", "1234"]
