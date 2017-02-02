#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# kastenwesen: a python tool for managing multiple docker containers
#
# Copyright (C) 2016 kastenwesen contributors [see git log]
# https://github.com/fau-fablab/kastenwesen
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Monitoring script run by cron.

Update status HTML page and send emails.
Send mails on critical changes and when things got fixed. Recognizes flapping.
"""

import json
import os
import re
import socket
import subprocess
from collections import namedtuple
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

import kastenwesen

STATUS_DIR = '/var/run/kastenwesen_status/'
STATUS_HTML = 'status.html'
STATUS_JSON = 'status.json'
LAST_MODIFIED_FILE = '.last_modified.txt'
MAIL_SRC = MAIL_DST = 'root'
# Status changes will be mailed when they were constant 5 times in a row:
FLAPPING_HYSTERESIS = 5

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

class ContainerStatus(kastenwesen.ContainerStatus):
    FLAPPING = "FLAPPING"
    UNKNOWN = 'UNKNOWN'


def get_new_status():
    """Return the current status of kastenwesen."""
    proc = subprocess.run(
        './kastenwesen/kastenwesen.py status --cron'.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    status_report_list = json.loads(proc.stdout.decode('utf8'))
    status_report_dict = {
        container_name: (status, msg)
        for container_name, status, msg in status_report_list
    }
    return (
        status_report_dict,
        proc.stderr.decode('utf8'),
        proc.returncode,
    )


def get_old_status():
    """Return the status of the last run."""
    try:
        return json.load(open(os.path.join(STATUS_DIR, STATUS_JSON), 'r'))
    except FileNotFoundError:
        return []


def send_mail(content_text, content_html, subject, sender, recipient):
    """Send E-Mail using sendmail."""
    multipart_mime = MIMEMultipart('alternative')
    multipart_mime.attach(MIMEText(content_text, _charset='utf-8'))
    multipart_mime.attach(MIMEText(content_html, 'html', _charset='utf-8'))

    multipart_mime.add_header('Subject', subject)
    multipart_mime.add_header('From', sender)
    multipart_mime.add_header('To', recipient)
    multipart_mime.add_header('Date', formatdate(localtime=True))

    proc = subprocess.Popen("sendmail -t -oi".split(), stdin=subprocess.PIPE)
    proc.communicate(multipart_mime.as_bytes())


def format_status(status_report_list, out_format='html'):
    """Return status human readable in out_format format."""
    FORMAT = {
        'ascii': {
            ContainerStatus.OKAY: '[ ok ] %(name)s: %(msg)s%(changed)s',
            ContainerStatus.FAILED: '[fail] %(name)s: %(msg)s%(changed)s',
            ContainerStatus.STARTING: '[ ok ] %(name)s: %(msg)s%(changed)s',
            ContainerStatus.FLAPPING: '[flap] %(name)s: %(msg)s (flapping)%(changed)s',
        },
        'html': {
            ContainerStatus.OKAY: '<li style="color:green;">[ ok ] %(name)s: %(msg)s%(changed)s</li>',
            ContainerStatus.FAILED:'<li style="color:red;">[fail] %(name)s: %(msg)s%(changed)s</li>',
            ContainerStatus.STARTING: '<li style="color:yellow;">[ ok ] %(name)s: %(msg)s%(changed)s</li>',
            ContainerStatus.FLAPPING: '<li style="color:orange;">[flap] %(name)s: %(msg)s (flapping)%(changed)s</li>',
        },
    }

    lines = (
        FORMAT[out_format][container_report.overall_status] % {
            'name': container_report.container_name,
            'msg': container_report.current_msg,
            'changed': ' (changed)' if container_report.changed else '',
        } for container_report in status_report_list
    )

    if out_format == 'html':
        return '<ul style="list-style:none;">\n%s\n</ul>' % '\n'.join(lines)
    elif out_format == 'ascii':
        return '\n'.join(lines)


def update_html_page(content_html, stderr, title):
    """Update the HTML status file."""
    page = PAGE_TEMPLATE % {
        'title': title,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'content_html': content_html,
        'stderr': stderr,
    }
    open(os.path.join(STATUS_DIR, STATUS_HTML), 'w').write(page.strip())


def detect_flapping_and_changes(status_history_list):
    """Return current status and detect flapping and changes we want report."""
    ExtendedStatusReport = namedtuple('ExtendedStatusReport', [
        'container_name',
        'current_status',
        'overall_status',
        'current_msg',
        'changed',
    ])
    current_status = []
    changes_to_report = False
    for container_name, report in status_history_list[0].items():
        overall_status = ContainerStatus.UNKNOWN
        for entry in status_history_list[:-1]:
            entry_status = entry.get(container_name, (ContainerStatus.UNKNOWN))[0]
            if overall_status == ContainerStatus.UNKNOWN:
                overall_status = entry_status
            elif overall_status != entry_status:
                overall_status = ContainerStatus.FLAPPING

        # we want report a change for this container if the status is failed or
        # okay (not unknown, flapping, starting) and when it is different to the
        # state we detected FLAPPING_HYSTERESIS times before
        changed = (
            overall_status in (ContainerStatus.FAILED, ContainerStatus.OKAY) and
            overall_status != status_history_list[-1].get(container_name, (overall_status))[0]
        )
        changes_to_report = max(changes_to_report, changed)

        current_status.append(ExtendedStatusReport(
            container_name, report[0], overall_status, report[1], changed
        ))

    return changes_to_report, current_status


def main():
    """Update HTML page and send emails on status changes."""
    os.makedirs(STATUS_DIR, exist_ok=True)
    # get old and new status json
    status_report_list_new, stderr, returncode = get_new_status()
    status_history_list = get_old_status()
    status_history_list.insert(0, status_report_list_new)
    # update status history json file and drop oldest states we don't want to
    # inspect next time
    json.dump(
        status_history_list[:FLAPPING_HYSTERESIS],
        open(os.path.join(STATUS_DIR, STATUS_JSON), 'w'),
        indent=2,
    )
    # detect flapping
    changes_to_report, current_status_list = detect_flapping_and_changes(status_history_list)
    current_status_list = sorted(current_status_list)
    # convert json to text/html and update html page
    title = '%s kastenwesen status' % socket.getfqdn()
    content_html = format_status(current_status_list, out_format='html')
    content_text = format_status(current_status_list, out_format='ascii')
    update_html_page(content_html, stderr, title)
    # send mail if needed
    if returncode == 42:
        # another instance is running
        exit()
    if (len(status_history_list) == 1 and returncode) or changes_to_report:
        # send mail if
        # - there is a failure and no history is available
        # - there are changes to report (see detect_flapping_and_changes)
        send_mail(content_text, content_html, title, MAIL_SRC, MAIL_DST)


if __name__ == '__main__':
    main()
