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
import sys
from collections import namedtuple
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

import kastenwesen

STATUS_DIR = '/var/run/kastenwesen_status/'
STATUS_HTML = 'status.html'
STATUS_JSON = 'status.json'
MAIL_SRC = MAIL_DST = 'root'
STATUS_HISTORY_LENGTH = 20

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

def is_shutting_down():
    """Return True if the system is currently shutting down"""
    try:
        # query systemd, ignore returncode
        proc = subprocess.run("systemctl is-system-running".split(), stdout=subprocess.PIPE)
        stdout = proc.stdout.decode('utf8').strip()
        return (stdout == "stopping")
    except FileNotFoundError:
        # systemctl not found
        return False

def get_new_status():
    """Return the current status of kastenwesen."""
    proc = subprocess.run(
        [os.path.dirname(os.path.realpath(__file__)) + "/kastenwesen.py",
            "status", "--cron"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout = proc.stdout.decode('utf8')
    if proc.returncode == 42:
        # another instance of kastenwesen is currently running -> no output
        status_report_dict = {}
    else:
        try:
            json_data = json.loads(stdout)
        except json.decoder.JSONDecodeError:
            raise Exception("Failed to get kastenwesen status. returncode {}, stderr:\n{}"
                            .format(proc.returncode, proc.stderr.decode('utf8')));
        status_report_dict = {
            container_name: (status, msg)
            for container_name, status, msg in json_data
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
            ContainerStatus.MISSING: '[miss] %(name)s: %(msg)s%(changed)s',
            ContainerStatus.STARTING: '[wait] %(name)s: %(msg)s%(changed)s',
            ContainerStatus.FLAPPING: '[flap] %(name)s: %(msg)s (flapping)%(changed)s',
        },
        'html': {
            ContainerStatus.OKAY: '<li style="color:green;">[ ok ] %(name)s: %(msg)s%(changed)s</li>',
            ContainerStatus.FAILED:'<li style="color:red;">[fail] %(name)s: %(msg)s%(changed)s</li>',
            ContainerStatus.MISSING:'<li style="color:red;">[miss] %(name)s: %(msg)s%(changed)s</li>',
            ContainerStatus.STARTING: '<li style="color:orange;">[wait] %(name)s: %(msg)s%(changed)s</li>',
            ContainerStatus.FLAPPING: '<li style="color:red;">[flap] %(name)s: %(msg)s (flapping)%(changed)s</li>',
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
    """Return current status and detect changes we want report."""
    ExtendedStatusReport = namedtuple('ExtendedStatusReport', [
        'container_name',
        'current_status',
        'overall_status',
        'current_msg',
        'changed',
    ])
    current_status_list = []
    changes_to_report = False
    for container_name, report in status_history_list[0].items():
        # get known history of this container
        container_status_history = []
        container_status_history_filtered = []
        for entry in status_history_list:
            if container_name in entry:
                status = entry[container_name][0]
                # strip out STARTING (starting is as good as its result)
                container_status_history.append(status)
                if status == ContainerStatus.STARTING:
                    continue
                container_status_history_filtered.append(status)

        overall_status = container_status_history[0]
        # TODO: if the status changes too often, stop reporting changes
        # and switch to FLAPPING state
        # if flapping:
        #     overall_status = ContainerStatus.FLAPPING

        if len(container_status_history_filtered) > 2:
            # enough history data is available.
            # we want report a change for this container if the current status
            # different to the oldest status we know
            changed = container_status_history_filtered[0] != container_status_history_filtered[1]
        else:
            # not enough history is available. always report failure.
            changed = container_status_history[0] in (ContainerStatus.FAILED, ContainerStatus.MISSING)

        # if there is at least one change, we want to report changes
        changes_to_report = changes_to_report or changed

        current_status_list.append(ExtendedStatusReport(
            container_name, report[0], overall_status, report[1], changed
        ))

    return changes_to_report, current_status_list


def get_bad_containers(status_report_list):
    """Return a list of container names with problems."""
    return [
        container_report.container_name
        for container_report in status_report_list
        if container_report.overall_status != ContainerStatus.OKAY
    ]


def main():
    """Update HTML page and send emails on status changes."""
    os.makedirs(STATUS_DIR, exist_ok=True)
    # get old and new status json
    status_report_list_new, stderr, returncode = get_new_status()
    status_history_list = get_old_status()
    status_history_list.insert(0, status_report_list_new)
    # detect flapping
    changes_to_report, current_status_list = detect_flapping_and_changes(status_history_list)
    current_status_list = sorted(current_status_list)
    bad_containers = get_bad_containers(current_status_list)
    # create meaningful title
    icon = '❌' if bad_containers else '✅'
    title = '{icon}{fdqn} kastenwesen status'.format(icon=icon, fdqn=socket.getfqdn())
    if bad_containers:
        title += ' (broken: {lst})'.format(
            lst=', '.join(
                bad_containers[:2] + ['and {} more'.format(len(bad_containers) - 2)]
                if len(bad_containers) > 3
                else bad_containers
            )
        )

    # convert json to text/html and update html page
    content_html = format_status(current_status_list, out_format='html')
    content_text = format_status(current_status_list, out_format='ascii')
    update_html_page(content_html, stderr, title)
    # send mail if needed
    if returncode == 42 or is_shutting_down():
        # another kastenwesen instance is running, or the system is shutting down
        # Never send mails during that.
        # Also do not save the status history to make sure that no relevant change mails are suppressed.
        exit()

    # update status history json file and drop oldest states we don't want to
    # inspect next time
    json.dump(
        status_history_list[:STATUS_HISTORY_LENGTH],
        open(os.path.join(STATUS_DIR, STATUS_JSON), 'w'),
        indent=2,
    )

    if changes_to_report:
        if "--debug" in sys.argv:
            print("report changes:")
            print(content_text)
        send_mail(content_text, content_html, title, MAIL_SRC, MAIL_DST)


if __name__ == '__main__':
    main()
