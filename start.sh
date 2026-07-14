#!/usr/bin/env bash
# Startet DayZ-Bot + Web-Dashboard in einem Prozess.
# Der Web-Port wird über SERVER_PORT/PORT oder config.json (dashboard_port) bestimmt.
cd "$(dirname "$0")"
exec python bot.py
