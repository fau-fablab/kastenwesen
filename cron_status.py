#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Update status HTML page and send emails.

Send mails on critical changes and when things got fixed.
"""

import json
import os
import re
import socket
import subprocess
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

from kastenwesen import ContainerStatus

STATUS_DIR = '/var/run/kastenwesen_status/'
STATUS_HTML = 'status.html'
STATUS_JSON = 'status.json'
LAST_MODIFIED_FILE = '.last_modified.txt'
MAIL_SRC = MAIL_DST = 'root'

PAGE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <title>%(title)s</title>
    <style>body{font-family:monospace;color:white;background:black;}</style>
  </head>
  <body>
    <h1>
      %(title)s<br>
      <small>Generated on %(date)s</small>
    </h1>
    %(content_html)s
    <h2>Stderr:</h2>
    <pre><code>%(stderr)s</code></pre>
  </body>
</html>
'''

def get_new_status():
    """Return the current status of kastenwesen."""
    proc = subprocess.run(
        './kastenwesen/kastenwesen.py status --cron'.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return (
        json.loads(proc.stdout.decode('utf8')),
        proc.stderr.decode('utf8'),
        proc.returncode,
    )


def get_old_status():
    """Return the status of the last run."""
    try:
        return json.load(open(os.path.join(STATUS_DIR, STATUS_JSON), 'r'))
    except FileNotFoundError:
        return json.loads('{}')


def send_mail(content_text, content_html, subject, sender, recipient):
    """Send E-Mail using sendmail."""
    multipart_mime = MIMEMultipart('alternative')
    multipart_mime.attach(MIMEText(content_text, _charset='utf-8'))
    multipart_mime.attach(MIMEText(content_html, 'html',  _charset='utf-8'))

    multipart_mime.add_header('Subject', subject)
    multipart_mime.add_header('From', sender)
    multipart_mime.add_header('To', recipient)
    multipart_mime.add_header('Date', formatdate(localtime=True))

    proc = subprocess.Popen("sendmail -t -oi".split(), stdin=subprocess.PIPE)
    proc.communicate(multipart_mime.as_bytes())


def status_json_to_text(status_json):
    """Return status_json as human readable plain text."""
    lines = []
    for container_name, status_report in status_json:
        container_status, msg = status_report
        if container_status == ContainerStatus.OKAY:
            lines.append('[ ok ] %s: %s' % (container_name, msg))
        elif container_status == ContainerStatus.STARTING:
            lines.append('[ ok ] %s: %s' % (container_name, msg))
        elif container_status == ContainerStatus.FAILED:
            lines.append('[fail] %s: %s' % (container_name, msg))
        else:
            raise ValueError('Invalid status %s' % container_status)

    return '\n'.join(lines)


def status_json_to_html(status_json):
    """Return status_json as human readable plain text."""
    lines = []
    for container_name, status_report in status_json:
        container_status, msg = status_report
        if container_status == ContainerStatus.OKAY:
            lines.append('<li style="color:green;">[ ok ] %s: %s</li>' % (container_name, msg))
        elif container_status == ContainerStatus.STARTING:
            lines.append('<li style="color:orange;">[ ok ] %s: %s</li>' % (container_name, msg))
        elif container_status == ContainerStatus.FAILED:
            lines.append('<li style="color:red;">[fail] %s: %s</li>' % (container_name, msg))
        else:
            raise ValueError('Invalid status %s' % container_status)

    return '<ul style="list-style:none;">\n' + '\n'.join(lines) + '</ul>'


def update_html(content_html, stderr, title):
    """Update the HTML status file."""
    page = PAGE_TEMPLATE % {
        'title': title, 'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'content_html': content_html, 'stderr':stderr,
    }
    open(os.path.join(STATUS_DIR, STATUS_HTML), 'w').write(page.strip())


def main():
    """Update HTML page and send emails on status changes."""
    os.makedirs(STATUS_DIR, exist_ok=True)
    # get old and new status json
    status_json_old = get_old_status()
    status_json_new, stderr, returncode = get_new_status()
    # update status json
    json.dump(status_json_new, open(os.path.join(STATUS_DIR, STATUS_JSON), 'w'))
    # convert json to text/html and update html page
    title = '%s kastenwesen status' % socket.getfqdn()
    content_html = status_json_to_html(status_json_new)
    content_text = status_json_to_text(status_json_new)
    update_html(content_html, stderr, title)
    # send mail if needed
    if (not status_json_old and returncode) \
            or status_json_old != status_json_new:
        # mail
        send_mail(content_text, content_html, title, MAIL_SRC, MAIL_DST)


if __name__ == '__main__':
    main()
