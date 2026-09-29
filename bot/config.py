# -*- coding: utf-8 -*-
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Comma-separated Telegram numeric user IDs allowed to use the bot
# (baristas / promoters / admins). Example: "111111111,222222222"
_raw_staff = os.environ.get("STAFF_IDS", "")
STAFF_IDS = {
    int(x.strip()) for x in _raw_staff.split(",") if x.strip().isdigit()
}

# Comma-separated Telegram numeric user IDs with admin rights
# (can see full reports across all staff, not just their own shift).
_raw_admin = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {
    int(x.strip()) for x in _raw_admin.split(",") if x.strip().isdigit()
}

# Locations — single location by default (see README to add more).
# First one is used automatically when only one is configured.
_raw_locations = os.environ.get("LOCATIONS", "Taganka")
LOCATIONS = [x.strip() for x in _raw_locations.split(",") if x.strip()]

DB_PATH = os.environ.get("DB_PATH", "wheel.db")
