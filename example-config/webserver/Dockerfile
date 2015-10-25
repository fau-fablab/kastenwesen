FROM ubuntu:14.04

RUN apt-get update
RUN apt-get install -y apache2
RUN apt-get clean
# remove apt lists
RUN rm -rf /var/lib/apt/lists/*




EXPOSE 80
COPY ./run-service /usr/bin/run-service
CMD ["run-service", "apache2"]