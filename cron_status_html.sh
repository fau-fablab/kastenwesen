#!/bin/sh
{
	which aha > /dev/null ||  { date; echo "aha not installed"; exit 0; }
	( date; kastenwesen status 2>&1 || echo "Error."; ) | aha --title "`hostname --fqdn`"
} > /var/run/kastenwesen_status.html

