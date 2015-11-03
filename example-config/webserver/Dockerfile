FROM my-linux-base

RUN apt-get update
RUN apt-get install -y webfs
RUN apt-get clean
RUN mkdir /var/www


EXPOSE 80
CMD /usr/bin/webfsd -F -r /var/www -p 80