FROM ubuntu:14.04

RUN apt-get update
RUN apt-get install -y netcat
RUN apt-get clean
# remove apt lists
RUN rm -rf /var/lib/apt/lists/*




EXPOSE 1234
CMD ["netcat", "-k", "-l", "-p", "1234"]
