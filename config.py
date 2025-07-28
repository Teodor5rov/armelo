from flask import Flask, render_template, request, redirect, url_for, session, g, send_from_directory, make_response
from flask_talisman import Talisman
from werkzeug.security import check_password_hash
from werkzeug.exceptions import NotFound
from datetime import datetime, timedelta
from calendar import month_name
import logging
import requests
from logging.handlers import RotatingFileHandler
import sqlite3
import os
import math
from scipy.stats import binom
from dotenv import load_dotenv

load_dotenv()

DATABASE = 'database.db'

SUPERMATCH_FORMATS = {
    "Single round": [1, 64, "Best of"],
    "Best of 3": [3, 96, "Best of"],
    "Best of 5": [5, 128, "Best of"],
    "5 round match": [5, 144, "All rounds"],
    "6 round Vendetta": [6 + 1, 144, "Vendetta"],
    "Best of 7": [7, 144, "Best of"],
    "10 round Speculative": [10, 128, "All rounds"],
}

CONTRAST = 400
K = 128
I = 20

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', '%%8hF$7ALEy8Msw2')
CLOUDFLARE_SECRET_KEY = os.getenv('CLOUDFLARE_SECRET_KEY', '1x0000000000000000000000000000000AA')

handler = RotatingFileHandler('armelo_app.log', maxBytes=100000, backupCount=3)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
handler.setFormatter(formatter)
app.logger.addHandler(handler)
app.logger.setLevel(logging.DEBUG)

csp = {
    'default-src': [
        '\'self\'',
        'https://cdn.jsdelivr.net',
        'https://fonts.googleapis.com',
        'https://unpkg.com'
    ],
    'base-uri': [
        '\'self\''
    ],
    'img-src': [
        '\'self\'',
        'data:'
    ],
    'script-src': [
        '\'self\'',
        'https://cdn.jsdelivr.net',
        'https://unpkg.com',
        'https://challenges.cloudflare.com'
    ],
    'script-src-elem': [
        "'self'",
        'https://cdn.jsdelivr.net',
        'https://unpkg.com',
        'https://challenges.cloudflare.com'
    ],
    'style-src': [
        '\'self\'',
        'https://cdn.jsdelivr.net',
        'https://fonts.googleapis.com',
        '\'unsafe-inline\''
    ],
    'font-src': [
        '\'self\'',
        'https://fonts.gstatic.com',
        'https://cdn.jsdelivr.net'
    ],
    'connect-src': [
        '\'self\''
    ],
    'frame-src': [
        "'self'",
        'https://challenges.cloudflare.com'
    ]
}

# talisman = Talisman(app, content_security_policy=csp, content_security_policy_nonce_in=['script-src', 'script-src-elem'])


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db


def db_execute(query, *args):
    db = get_db()
    cur = db.cursor()
    cur.execute(query, args)
    if query.strip().upper().startswith(("SELECT", "WITH")):
        rv = cur.fetchall()
        cur.close()
        return rv
    else:
        db.commit()
        cur.close()
