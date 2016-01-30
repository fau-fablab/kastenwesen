#!/bin/sh
{
	date
	which aha > /dev/null ||  { echo "aha not installed"; exit 0; }
	( kastenwesen status 2>&1 || echo "Error."; ) | aha
} > /var/run/kastenwesen_status.html

