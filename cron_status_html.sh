#!/bin/bash
mkdir -p /var/run/kastenwesen_status/

# check status, store output
OKAY=true
( date; kastenwesen status 2>&1 ) > /var/run/kastenwesen_status/colored || OKAY=false

# generate HTML
{
	cat /var/run/kastenwesen_status/colored | aha --title "`hostname --fqdn`" || echo "Error -- 'aha' not installed?"
} > /var/run/kastenwesen_status/status.html

# generate text output
cat /var/run/kastenwesen_status/colored | sed -r 's/\x1b[\[0-9;]+m//g' > /var/run/kastenwesen_status/text

MAIL_USER=root
# send mail to $MAIL_USER if last mail is more than $MAIL_MAX_MIN ago
MAIL_MAX_MIN=30
# be quiet for $MAIL_SKIP_AFTER_RUN_MIN after starting kastenwesen operations
# since we currently only compare to the time kastenwesen was started,
# this needs to be a little larger to also work for huge operations like `kastenwesen rebuild --no-cache`
MAIL_SKIP_AFTER_RUN_MIN=10

SKIP_MAIL=false
test -e  /var/run/kastenwesen_status/last_mail && [[ $(stat -L --format %Y /var/run/kastenwesen_status/last_mail) -gt $(date -d "$MAIL_MAX_MIN minutes ago" +%s) ]] && SKIP_MAIL=true
test -e  /var/lock/kastenwesen.lock && [[ $(stat -L --format %Y /var/lock/kastenwesen.lock) -gt $(date -d "$MAIL_SKIP_AFTER_RUN_MIN minutes ago" +%s) ]] && SKIP_MAIL=true
! $OKAY && ! $SKIP_MAIL && { touch /var/run/kastenwesen_status/last_mail && cat /var/run/kastenwesen_status/text | mail -s "`hostname --fqdn` kastenwesen status" $MAIL_USER; }
