from flask import Flask, render_template, request, redirect, url_for, session, g, send_from_directory
from flask_talisman import Talisman
from werkzeug.security import check_password_hash
from werkzeug.exceptions import NotFound
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
import os

from elo import diff_supermatch, calculate_elo_with_bonus, expected_elo_from_score, expected_score, binom_prediction

DATABASE = 'database.db'

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '%%8hF$7ALEy8Msw2')

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
        'https://unpkg.com'
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
    ]
}

# talisman = Talisman(app, content_security_policy=csp, content_security_policy_nonce_in=['script-src'])


SUPERMATCH_FORMATS = {
    "Single round": [1, 64, "Best of"],
    "Best of 3": [3, 96, "Best of"],
    "Best of 5": [5, 128, "Best of"],
    "5 round match": [5, 144, "All rounds"],
    "6 round Vendetta": [6 + 1, 144, "Vendetta"],
    "Best of 7": [7, 144, "Best of"],
    "10 round Speculative": [10, 128, "All rounds"],
}


@app.route('/robots.txt')
def serve_robots_txt():
    return send_from_directory(app.static_folder, 'robots.txt')


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


@app.context_processor
def inject_user():
    username = session.get('username')
    return dict(username=username)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get('username'):
        return redirect(url_for('ranking'))

    if request.method == "POST":
        username = request.form.get('username')
        password = request.form.get('password')
        user = db_execute("SELECT * FROM users WHERE username = ?", username)
        if user and check_password_hash(user[0][1], password):
            session['username'] = username
            return redirect(url_for('ranking'))
        else:
            return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')


@app.route("/logout")
def logout():
    session.pop('username', None)
    return redirect(url_for('ranking'))


@app.route("/")
@app.route("/<any(right, left):arm>")
def ranking(arm='right'):
    order_by = 'right_elo' if arm == 'right' else 'left_elo'
    active_armwrestlers = db_execute('''SELECT DENSE_RANK() OVER (ORDER BY {0} DESC) AS rank, id, name, {0} FROM armwrestlers WHERE active_until >= DATE('now')'''.format(order_by))
    inactive_armwrestlers = db_execute('''SELECT id, name, {0} FROM armwrestlers WHERE active_until < DATE('now') ORDER BY {0} DESC'''.format(order_by))
    username = session.get('username')
    return render_template('ranking.html', active_armwrestlers=active_armwrestlers, inactive_armwrestlers=inactive_armwrestlers, username=username, arm=arm)


@app.route("/edit_member", methods=["GET", "POST"])
def edit_member():
    if not session.get('username'):
        return redirect(url_for('login'))

    status_options = ["active", "inactive"]

    current_user = session.get('username')
    try:
        id = int(request.form.get('id'))
    except (ValueError, IndexError):
        raise NotFound()
    name_result = db_execute('SELECT name FROM armwrestlers WHERE id = ?', id)
    if not name_result:
        raise NotFound()
    current_name = name_result[0][0]
    name = request.form.get('name', current_name)
    current_status = db_execute('''SELECT CASE WHEN active_until >= DATE('now') THEN 'active' ELSE 'inactive' END AS current_status FROM armwrestlers WHERE id = ?''', id)[0][0]
    armwrestlers = db_execute('SELECT name FROM armwrestlers ORDER BY LOWER(name)')
    right_elo = request.form.get('right_elo', str(get_current_elo("right", [id])[0]))
    left_elo = request.form.get('left_elo', str(get_current_elo("left", [id])[0]))
    selected_status = request.form.get('selected_status', current_status)
    member_ready = False
    error = None

    if not name and request.method == "POST":
        error = "No name entered"

    armwrestler_names = [aw[0] for aw in armwrestlers]
    if name in armwrestler_names and name != current_name:
        error = "Name already taken"

    if selected_status not in status_options:
        error = "Invalid status"

    try:
        if not right_elo.isdigit() or not left_elo.isdigit():
            raise ValueError
        right_elo, left_elo = int(right_elo), int(left_elo)
    except (ValueError):
        error = "Invalid ELO data"
        right_elo, left_elo = 0, 0

    if name and \
            error == None and \
            right_elo > 0 and \
            left_elo > 0 and \
            selected_status in status_options:
        member_ready = True

    if 'edit_member' in request.form and member_ready:
        try:
            if selected_status != current_status:
                if selected_status == status_options[0]:
                    today = datetime.today()
                    active_until_date = today + timedelta(days=180)
                    active_until_str = active_until_date.strftime('%Y-%m-%d')
                elif selected_status == status_options[1]:
                    today = datetime.today()
                    active_until_date = today - timedelta(days=2)
                    active_until_str = active_until_date.strftime('%Y-%m-%d')
                db_execute("UPDATE armwrestlers SET name = ?, right_elo = ?, left_elo = ?, active_until = ?, last_edited_by = ? WHERE id = ?", name, right_elo, left_elo, active_until_str, current_user, id)
            else:
                db_execute("UPDATE armwrestlers SET name = ?, right_elo = ?, left_elo = ? WHERE id = ?", name, right_elo, left_elo, id)
        except sqlite3.DatabaseError as error:
            print(error)
        return redirect(url_for('ranking'))

    template_data = {
        'id': id,
        'name': name,
        'current_name': current_name,
        'right_elo': right_elo, 'left_elo': left_elo,
        'status_options': status_options,
        'selected_status': selected_status,
        'member_ready': member_ready,
        'error': error
    }

    if request.headers.get('HX-Request'):
        return render_template('edit_member_partial.html', **template_data)
    else:
        return render_template('edit_member.html', **template_data)


@app.route("/confirm_remove", methods=["POST"])
def confirm_remove():
    if not session.get('username'):
        return redirect(url_for('login'))

    try:
        id = int(request.form.get('id')) or int(request.args.get('id'))
    except (ValueError, IndexError):
        raise NotFound()
    current_name = request.form.get('current_name') or request.args.get('current_name')

    if 'confirm_remove' in request.form:
        try:
            db_execute("DELETE FROM armwrestlers WHERE id = ?", id)
        except sqlite3.DatabaseError as error:
            print(error)
        return redirect(url_for('ranking'))

    return render_template('confirm_remove.html', id=id, current_name=current_name)


@app.route("/closest_matches")
def closest_matches():
    arm = request.args.get('arm', 'right')
    supermatch_add = False

    order_by = 'right_elo' if arm == 'right' else 'left_elo'
    if session.get('username'):
        supermatch_add = True

    query = """
    WITH rankedarmwrestlers AS (
        SELECT DENSE_RANK() OVER (ORDER BY {0} DESC) AS rank, 
               id, name, 
               {0} AS elo
        FROM armwrestlers
    )
    SELECT 
        a.rank AS rank1, 
        a.id AS armwrestler1_id,
        a.name AS armwrestler1,
        a.elo AS elo1, 
        b.rank AS rank2,
        b.id AS armwrestler2_id,
        b.name AS armwrestler2, 
        b.elo AS elo2, 
        ABS(a.elo - b.elo) AS elo_difference
    FROM rankedarmwrestlers a, rankedarmwrestlers b
    WHERE a.name < b.name
    ORDER BY elo_difference ASC
    LIMIT 15;
    """.format(order_by)

    closest_matches = db_execute(query)
    closest_matches_with_predictions = []
    for match in closest_matches:
        binom_predicted_1, binom_predicted_2 = binom_prediction(match[3], match[7])
        binom_predicted_1, binom_predicted_2 = round(binom_predicted_1 * 100, 1), round(binom_predicted_2 * 100, 1)
        color_1, color_2 = (f"success", "danger") if binom_predicted_1 > binom_predicted_2 else ((f"danger", "success") if binom_predicted_1 < binom_predicted_2 else ("secondary", "secondary"))
        match_with_prediction = match + (binom_predicted_1, binom_predicted_2, color_1, color_2)
        closest_matches_with_predictions.append(match_with_prediction)

    return render_template('closest_matches.html', closest_matches_with_predictions=closest_matches_with_predictions, arm=arm, supermatch_add=supermatch_add)


@app.route("/view_member", methods=["GET"])
def view_member():

    try:
        id = int(request.args.get('id'))
    except (ValueError, IndexError):
        raise NotFound()
    name_result = db_execute('SELECT name FROM armwrestlers WHERE id = ?', id)
    if not name_result:
        raise NotFound()
    name = name_result[0][0]

    query = '''
        WITH ranked_right AS (
            SELECT id, DENSE_RANK() OVER (ORDER BY right_elo DESC) AS right_rank
            FROM armwrestlers
            WHERE active_until >= DATE('now')
        ),
        ranked_left AS (
            SELECT id, DENSE_RANK() OVER (ORDER BY left_elo DESC) AS left_rank
            FROM armwrestlers
            WHERE active_until >= DATE('now')
        )
        SELECT 
            CASE WHEN a.active_until >= DATE('now') THEN 'active' ELSE 'inactive' END AS current_status,
            a.right_elo, 
            a.left_elo,
            rr.right_rank,
            rl.left_rank,
            a.active_until
        FROM armwrestlers a
        LEFT JOIN ranked_right rr ON a.id = rr.id
        LEFT JOIN ranked_left rl ON a.id = rl.id
        WHERE a.id = ?
    '''

    current_status, current_right_elo, current_left_elo, current_right_rank, current_left_rank, active_until = db_execute(query, id)[0]

    active_until_date = datetime.strptime(active_until, '%Y-%m-%d')
    days_left = (active_until_date - datetime.today()).days
    days_left = days_left if days_left > 0 else "inactive"

    history = db_execute('''
        SELECT a1.id AS armwrestler1_id, a1.name AS armwrestler1_name, a2.id AS armwrestler2_id, a2.name AS armwrestler2_name, h.arm, 
               h.armwrestler1_rank, h.armwrestler2_rank, h.armwrestler1_elo, h.armwrestler2_elo, 
               h.armwrestler1_score, h.armwrestler2_score, h.armwrestler1_elo_diff, h.armwrestler2_elo_diff, 
               h.selected_format, h.date
        FROM history h
        JOIN armwrestlers a1 ON h.armwrestler1_id = a1.id
        JOIN armwrestlers a2 ON h.armwrestler2_id = a2.id
        WHERE h.armwrestler1_id = ? OR h.armwrestler2_id = ?
        ORDER BY h.id DESC
    ''', id, id)

    if history:
        best_right_elo = current_right_elo
        best_left_elo = current_left_elo
        best_right_rank = current_right_rank
        best_left_rank = current_left_rank

        for record in history:
            is_armwrestler1 = record[0] == id

            arm = record[4]
            elo = record[7] if is_armwrestler1 else record[8]
            rank = record[5] if is_armwrestler1 else record[6]

            if arm == 'right':
                best_right_elo = max(best_right_elo, elo)
                best_right_rank = min(best_right_rank, rank) if best_right_rank is not None else rank
            elif arm == 'left':
                best_left_elo = max(best_left_elo, elo)
                best_left_rank = min(best_left_rank, rank) if best_left_rank is not None else rank

        formatted_data = get_history_formatted_data(history)
        total_matches = len(history)

    else:
        best_right_elo = current_right_elo
        best_left_elo = current_left_elo
        best_right_rank = current_right_rank
        best_left_rank = current_left_rank
        history = None
        formatted_data = None
        total_matches = None

    template_data = {
        'id': id,
        'name': name,
        'current_right_elo': current_right_elo, 'current_left_elo': current_left_elo,
        'current_right_rank': current_right_rank, 'current_left_rank': current_left_rank,
        'best_right_elo': best_right_elo, 'best_left_elo': best_left_elo,
        'best_right_rank': best_right_rank, 'best_left_rank': best_left_rank,
        'current_status': current_status,
        'history': history, 'formatted_data': formatted_data,
        'total_matches': total_matches,
        'days_left': days_left
    }

    return render_template('view_member.html', **template_data)


@app.route("/add_new_member", methods=["GET", "POST"])
def add_new_member():
    if not session.get('username'):
        return redirect(url_for('login'))

    current_user = session.get('username')

    name = request.form.get('name', '').strip()
    arm = request.form.get('arm', 'right')
    armwrestlers = db_execute('SELECT id, name FROM armwrestlers ORDER BY LOWER(name)')
    try:
        selected_armwrestler_2_id = int(request.form.get('armwrestler2')) if request.form.get('armwrestler2') else None
        selected_armwrestler_2_name = db_execute('SELECT name FROM armwrestlers WHERE id = ?', selected_armwrestler_2_id)[0][0] if selected_armwrestler_2_id else 'none'
    except (ValueError, IndexError):
        selected_armwrestler_2_id = None
        selected_armwrestler_2_name = 'none'
    supermatch_formats = list(SUPERMATCH_FORMATS.keys())
    value_for_score = None
    right_elo = request.form.get('right_elo', '0')
    left_elo = request.form.get('left_elo', '0')
    refs_right = request.form.get('refs_right', '0')
    refs_left = request.form.get('refs_left', '0')
    custom_score = request.form.get('custom_score', False)
    armwrestler_1_score, armwrestler_2_score = None, None
    calculation_ready = False
    member_ready = False
    elo_from_match = None
    error = None

    if not name and request.method == "POST":
        error = "No name entered"

    armwrestler_names = [aw[1] for aw in armwrestlers]
    if name in armwrestler_names:
        error = "Name already taken"

    selected_format = request.form.get('supermatch_format', 'none')
    if selected_format not in supermatch_formats:
        selected_format = '10 round Speculative'

    max_rounds = SUPERMATCH_FORMATS[selected_format][0]

    if arm in ['left', 'right'] and \
            name != selected_armwrestler_2_name and \
            selected_armwrestler_2_name in armwrestler_names:
        calculation_ready = True

    try:
        if not right_elo.isdigit() or not left_elo.isdigit():
            raise ValueError
        right_elo, left_elo = int(right_elo), int(left_elo)
        refs_right, refs_left = int(refs_right), int(refs_left)
    except (ValueError):
        error = "Invalid ELO data"
        right_elo, left_elo = 0, 0
        refs_right, refs_left = 0, 0

    if calculation_ready:
        if custom_score:
            try:
                armwrestler_1_score = int(request.form.get('custom_score_1', (max_rounds // 2) + 1))
                armwrestler_2_score = int(request.form.get('custom_score_2', (max_rounds - ((max_rounds // 2) + 1))))
                if not (0 <= armwrestler_1_score <= max_rounds and 0 <= armwrestler_2_score <= max_rounds and (0 < (armwrestler_1_score + armwrestler_2_score) <= max_rounds)):
                    raise ValueError
            except (ValueError, TypeError):
                armwrestler_1_score = (max_rounds // 2) + 1
                armwrestler_2_score = (max_rounds - ((max_rounds // 2) + 1))
        else:
            try:
                value_for_score = int(request.form.get('score', (max_rounds // 2) + 1))
            except (ValueError, TypeError):
                value_for_score = (max_rounds // 2) + 1
            armwrestler_1_score, armwrestler_2_score = match_result(max_rounds, value_for_score, SUPERMATCH_FORMATS[selected_format][2])

        armwrestler_2_elo = get_current_elo(arm, [selected_armwrestler_2_id])[0]
        elo_from_match = expected_elo_from_score(armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score))

        add_to_avg_pressed = request.form.get('add_to_avg', False)
        if add_to_avg_pressed:
            if arm == 'right' and elo_from_match:
                if refs_right == 0:
                    right_elo += expected_elo_from_score(armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score))
                else:
                    right_elo = ((right_elo * refs_right) + expected_elo_from_score(armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score))) / (refs_right + 1)
                refs_right += 1
            elif arm == 'left' and elo_from_match:
                if refs_left == 0:
                    left_elo += expected_elo_from_score(armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score))
                else:
                    left_elo = ((left_elo * refs_left) + expected_elo_from_score(armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score))) / (refs_left + 1)
                refs_left += 1

            right_elo, left_elo = round(right_elo), round(left_elo)

        reset_pressed = request.form.get('reset', False)
        if reset_pressed:
            selected_armwrestler_2_id, selected_armwrestler_2_name = None, 'none'
            right_elo, left_elo = 0, 0
            refs_right, refs_left = 0, 0
            calculation_ready = False

    if name and name not in armwrestler_names and \
            error == None and \
            right_elo > 0 and \
            left_elo > 0:
        member_ready = True

    if 'add_member' in request.form and member_ready:
        try:
            today = datetime.today()
            active_until_date = today + timedelta(days=180)
            active_until_str = active_until_date.strftime('%Y-%m-%d')

            db_execute("INSERT INTO armwrestlers (name, right_elo, left_elo, added_by, active_until) VALUES (?, ?, ?, ?, ?)", name, right_elo, left_elo, current_user, active_until_str)
        except sqlite3.DatabaseError as error:
            print(error)
        return redirect(url_for('ranking'))

    template_data = {
        'arm': arm,
        'armwrestlers': armwrestlers,
        'selected_armwrestler_2_id': selected_armwrestler_2_id,
        'supermatch_formats': supermatch_formats, 'selected_format': selected_format,
        'value_for_score': value_for_score, 'max_rounds': max_rounds,
        'name': name,
        'armwrestler_1_score': armwrestler_1_score, 'armwrestler_2_score': armwrestler_2_score,
        'calculation_ready': calculation_ready,
        'right_elo': right_elo, 'left_elo': left_elo,
        'refs_right': refs_right, 'refs_left': refs_left,
        'elo_from_match': elo_from_match,
        'member_ready': member_ready,
        'custom_score': custom_score, 'custom_score_1': armwrestler_1_score, 'custom_score_2': armwrestler_2_score,
        'error': error
    }

    if request.headers.get('HX-Request'):
        return render_template('add_new_member_partial.html', **template_data)
    else:
        return render_template('add_new_member.html', **template_data)


@app.route("/history")
def history():
    history = db_execute('''
        SELECT a1.id AS armwrestler1_id, a1.name AS armwrestler1_name, a2.id AS armwrestler2_id, a2.name AS armwrestler2_name, h.arm, 
               h.armwrestler1_rank, h.armwrestler2_rank, h.armwrestler1_elo, h.armwrestler2_elo, 
               h.armwrestler1_score, h.armwrestler2_score, h.armwrestler1_elo_diff, h.armwrestler2_elo_diff, 
               h.selected_format, h.date
        FROM history h
        JOIN armwrestlers a1 ON h.armwrestler1_id = a1.id
        JOIN armwrestlers a2 ON h.armwrestler2_id = a2.id
        ORDER BY h.id DESC
    ''')

    formatted_data = get_history_formatted_data(history)

    return render_template('history.html', history=history, formatted_data=formatted_data)


@app.route("/undo_last_match", methods=["POST"])
def undo_last_match():
    if not session.get('username'):
        return redirect(url_for('login'))

    try:
        armwrestler1_id, armwrestler2_id, arm, armwrestler1_elo, armwrestler2_elo = db_execute(
            'SELECT armwrestler1_id, armwrestler2_id, arm, armwrestler1_elo, armwrestler2_elo FROM history ORDER BY id DESC LIMIT 1')[0]
        dbarm = 'right_elo' if arm == 'right' else 'left_elo'
        db_execute("UPDATE armwrestlers SET {} = ? WHERE id = ?".format(dbarm), armwrestler1_elo, armwrestler1_id)
        db_execute("UPDATE armwrestlers SET {} = ? WHERE id = ?".format(dbarm), armwrestler2_elo, armwrestler2_id)
        db_execute('DELETE FROM history WHERE id = (SELECT MAX(id) FROM history)')
    except (sqlite3.DatabaseError, IndexError) as error:
        print(error)
    return redirect(url_for('history'))


@app.route("/supermatch", methods=["GET", "POST"])
def supermatch():
    if not session.get('username'):
        return redirect(url_for('login'))

    current_user = session.get('username')

    arm = request.form.get('arm', 'right')
    try:
        selected_armwrestler_1_id = int(request.form.get('armwrestler1')) if request.form.get('armwrestler1') else None
        selected_armwrestler_2_id = int(request.form.get('armwrestler2')) if request.form.get('armwrestler2') else None
    except (ValueError, IndexError):
        selected_armwrestler_1_id, selected_armwrestler_2_id = None, None
    supermatch_formats = list(SUPERMATCH_FORMATS.keys())
    supermatch_ready = False
    value_for_score = None
    armwrestler_1_score, armwrestler_2_score = None, None
    armwrestler_1_diff, armwrestler_2_diff = None, None
    armwrestler_1_color, armwrestler_2_color = None, None
    custom_score = request.form.get('custom_score', False)
    armwrestler_1_elo, armwrestler_2_elo = None, None
    armwrestlers = db_execute('SELECT id, name FROM armwrestlers ORDER BY LOWER(name)')
    armwrestlers_2 = None

    selected_format = request.form.get('supermatch_format', 'none')
    if selected_format not in supermatch_formats:
        selected_format = 'Best of 5'

    max_rounds = SUPERMATCH_FORMATS[selected_format][0]

    if selected_armwrestler_1_id:
        armwrestlers_2 = [aw for aw in armwrestlers if aw[0] != selected_armwrestler_1_id]

    if selected_armwrestler_1_id is selected_armwrestler_2_id:
        selected_armwrestler_2_id = None

    # Checks if all conditions are met for supermatch ready
    armwrestler_ids = [aw[0] for aw in armwrestlers]
    if arm in ['left', 'right'] and \
            selected_armwrestler_1_id != selected_armwrestler_2_id and \
            selected_armwrestler_1_id in armwrestler_ids and \
            selected_armwrestler_2_id in armwrestler_ids and \
            selected_format in supermatch_formats:
        if custom_score:
            try:
                armwrestler_1_score = int(request.form.get('custom_score_1', (max_rounds // 2) + 1))
                armwrestler_2_score = int(request.form.get('custom_score_2', (max_rounds - ((max_rounds // 2) + 1))))
                if not (0 <= armwrestler_1_score <= max_rounds and 0 <= armwrestler_2_score <= max_rounds and (0 < (armwrestler_1_score + armwrestler_2_score) <= max_rounds)):
                    raise ValueError
            except (ValueError, TypeError):
                armwrestler_1_score = (max_rounds // 2) + 1
                armwrestler_2_score = (max_rounds - ((max_rounds // 2) + 1))
        else:
            try:
                value_for_score = int(request.form.get('score', (max_rounds // 2) + 1))
            except (ValueError, TypeError):
                value_for_score = (max_rounds // 2) + 1
            armwrestler_1_score, armwrestler_2_score = match_result(max_rounds, value_for_score, SUPERMATCH_FORMATS[selected_format][2])

        armwrestler_1_elo, armwrestler_2_elo = get_current_elo(arm, [selected_armwrestler_1_id, selected_armwrestler_2_id])
        armwrestler_1_diff, armwrestler_2_diff = diff_supermatch(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score), SUPERMATCH_FORMATS[selected_format][1])
        armwrestler_1_diff, armwrestler_1_color = (f"+{armwrestler_1_diff}", "text-success") if armwrestler_1_diff > 0 else ((str(armwrestler_1_diff),
                                                                                                                              "text-danger") if armwrestler_1_diff < 0 else ("0", "text-secondary"))
        armwrestler_2_diff, armwrestler_2_color = (f"+{armwrestler_2_diff}", "text-success") if armwrestler_2_diff > 0 else ((str(armwrestler_2_diff),
                                                                                                                              "text-danger") if armwrestler_2_diff < 0 else ("0", "text-secondary"))
        supermatch_ready = True

    submit_pressed = 'submit_match' in request.form
    if submit_pressed and supermatch_ready:
        submit_supermatch(arm, selected_armwrestler_1_id, selected_armwrestler_2_id, armwrestler_1_score, armwrestler_2_score, armwrestler_1_elo, armwrestler_2_elo, selected_format, current_user)
        return redirect(url_for('ranking'))

    template_data = {
        'arm': arm,
        'armwrestlers': armwrestlers, 'armwrestlers_2': armwrestlers_2,
        'selected_armwrestler_1_id': selected_armwrestler_1_id, 'selected_armwrestler_2_id': selected_armwrestler_2_id,
        'supermatch_formats': supermatch_formats, 'selected_format': selected_format, 'supermatch_ready': supermatch_ready,
        'value_for_score': value_for_score, 'max_rounds': max_rounds,
        'armwrestler_1_score': armwrestler_1_score, 'armwrestler_2_score': armwrestler_2_score,
        'armwrestler_1_diff': armwrestler_1_diff, 'armwrestler_2_diff': armwrestler_2_diff,
        'armwrestler_1_color': armwrestler_1_color, 'armwrestler_2_color': armwrestler_2_color,
        'armwrestler_1_elo': armwrestler_1_elo, 'armwrestler_2_elo': armwrestler_2_elo,
        'custom_score': custom_score, 'custom_score_1': armwrestler_1_score, 'custom_score_2': armwrestler_2_score
    }

    if request.headers.get('HX-Request'):
        return render_template('supermatch_partial.html', **template_data)
    else:
        return render_template('supermatch.html', **template_data)


def submit_supermatch(arm, armwrestler1_id, armwrestler2_id, armwrestler_1_score, armwrestler_2_score, armwrestler_1_elo, armwrestler_2_elo, selected_format, current_user):

    dbarm = 'right_elo' if arm == 'right' else 'left_elo'
    updated_1, updated_2 = calculate_elo_with_bonus(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score), SUPERMATCH_FORMATS[selected_format][1])

    armwrestler_1_rank = db_execute('SELECT rank FROM (SELECT RANK() OVER (ORDER BY {} DESC) AS rank, id FROM armwrestlers) AS RankedArmwrestlers WHERE id = ?'.format(dbarm), armwrestler1_id)[0][0]
    armwrestler_2_rank = db_execute('SELECT rank FROM (SELECT RANK() OVER (ORDER BY {} DESC) AS rank, id FROM armwrestlers) AS RankedArmwrestlers WHERE id = ?'.format(dbarm), armwrestler2_id)[0][0]

    armwrestler_1_diff, armwrestler_2_diff = diff_supermatch(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score), SUPERMATCH_FORMATS[selected_format][1])

    try:
        query = '''
        INSERT INTO history ( 
        armwrestler1_id, armwrestler2_id, 
        arm, 
        selected_format,
        armwrestler1_rank, armwrestler2_rank, 
        armwrestler1_elo, armwrestler2_elo, 
        armwrestler1_score, armwrestler2_score, 
        armwrestler1_elo_diff, armwrestler2_elo_diff,
        added_by ) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        db_execute(query,
                   armwrestler1_id, armwrestler2_id,
                   arm,
                   selected_format,
                   armwrestler_1_rank, armwrestler_2_rank,
                   armwrestler_1_elo, armwrestler_2_elo,
                   armwrestler_1_score, armwrestler_2_score,
                   armwrestler_1_diff, armwrestler_2_diff,
                   current_user)

        today = datetime.today()
        active_until_date = today + timedelta(days=180)
        active_until_str = active_until_date.strftime('%Y-%m-%d')

        db_execute("UPDATE armwrestlers SET {} = ?, active_until = ? WHERE id = ?".format(dbarm), updated_1, active_until_str, armwrestler1_id)
        db_execute("UPDATE armwrestlers SET {} = ?, active_until = ? WHERE id = ?".format(dbarm), updated_2, active_until_str, armwrestler2_id)

    except sqlite3.DatabaseError as error:
        print(error)


@app.route("/prediction")
def prediction():

    arm = request.args.get('arm', 'right')
    try:
        selected_armwrestler_1_id = int(request.args.get('armwrestler1')) if request.args.get('armwrestler1') else None
        selected_armwrestler_2_id = int(request.args.get('armwrestler2')) if request.args.get('armwrestler2') else None
    except (ValueError, IndexError):
        selected_armwrestler_1_id, selected_armwrestler_2_id = None, None
    supermatch_formats = list(SUPERMATCH_FORMATS.keys())
    armwrestlers = db_execute('SELECT id, name FROM armwrestlers ORDER BY LOWER(name)')
    armwrestlers_2 = None
    prediction_ready = False
    armwrestler_1_elo, armwrestler_2_elo = None, None
    expected_1, expected_2 = None, None
    binom_predicted_1, binom_predicted_2, binom_draw = None, None, None
    win_chance_color, score_color = None, None

    selected_format = request.args.get('supermatch_format', 'none')
    if selected_format not in supermatch_formats:
        selected_format = 'Best of 5'

    max_rounds = SUPERMATCH_FORMATS[selected_format][0]

    if selected_armwrestler_1_id:
        armwrestlers_2 = [aw for aw in armwrestlers if aw[0] != selected_armwrestler_1_id]

    if selected_armwrestler_1_id is selected_armwrestler_2_id:
        selected_armwrestler_2_id = None

    armwrestler_ids = [aw[0] for aw in armwrestlers]
    if arm in ['left', 'right'] and \
            selected_armwrestler_1_id != selected_armwrestler_2_id and \
            selected_armwrestler_1_id in armwrestler_ids and \
            selected_armwrestler_2_id in armwrestler_ids and \
            selected_format in supermatch_formats:
        armwrestler_1_elo, armwrestler_2_elo = get_current_elo(arm, [selected_armwrestler_1_id, selected_armwrestler_2_id])
        expected_1, expected_2 = expected_score_rounds(armwrestler_1_elo, armwrestler_2_elo, SUPERMATCH_FORMATS[selected_format][2], max_rounds)
        binom_predicted_1, binom_predicted_2 = binom_prediction(armwrestler_1_elo, armwrestler_2_elo, max_rounds)
        binom_draw = 1 - (binom_predicted_1 + binom_predicted_2)
        binom_predicted_1, binom_predicted_2, binom_draw = round(binom_predicted_1 * 100, 1), round(binom_predicted_2 * 100, 1), round(binom_draw * 100, 1)
        win_chance_color = (f"success", "danger") if binom_predicted_1 > binom_predicted_2 else ((f"danger", "success") if binom_predicted_1 < binom_predicted_2 else ("secondary", "secondary"))
        score_color = win_chance_color
        if expected_1 == expected_2:
            score_color = (f"secondary", "secondary")
        prediction_ready = True

    template_data = {
        'arm': arm,
        'selected_armwrestler_1_id': selected_armwrestler_1_id, 'selected_armwrestler_2_id': selected_armwrestler_2_id,
        'armwrestlers': armwrestlers, 'armwrestlers_2': armwrestlers_2,
        'supermatch_formats': supermatch_formats, 'selected_format': selected_format,
        'prediction_ready': prediction_ready,
        'armwrestler_1_elo': armwrestler_1_elo, 'armwrestler_2_elo': armwrestler_2_elo,
        'expected_1': expected_1, 'expected_2': expected_2,
        'binom_predicted_1': binom_predicted_1, 'binom_predicted_2': binom_predicted_2, 'binom_draw': binom_draw,
        'win_chance_color': win_chance_color, 'score_color': score_color
    }

    if request.headers.get('HX-Request'):
        return render_template('prediction_partial.html', **template_data)
    else:
        return render_template('prediction.html', **template_data)


@app.route("/elo_from_match")
def elo_from_match():

    ranked = request.args.get('ranked', 'ranked')
    arm = request.args.get('arm', 'right')
    try:
        selected_armwrestler_1_id = int(request.args.get('armwrestler1')) if request.args.get('armwrestler1') else None
        selected_armwrestler_2_id = int(request.args.get('armwrestler2')) if request.args.get('armwrestler2') else None
    except (ValueError, IndexError):
        selected_armwrestler_1_id, selected_armwrestler_2_id = None, None
    supermatch_formats = list(SUPERMATCH_FORMATS.keys())
    value_for_score = None
    armwrestlers = db_execute('SELECT id, name FROM armwrestlers ORDER BY LOWER(name)')
    armwrestlers_2 = None
    armwrestler_1_score, armwrestler_2_score = None, None
    armwrestler_1_diff, armwrestler_2_diff = None, None
    armwrestler_1_color, armwrestler_2_color = None, None
    armwrestler_1_elo, armwrestler_2_elo = None, None
    custom_score = request.args.get('custom_score', False)
    calculation_ready = False
    elo_from_match = None

    selected_format = request.args.get('supermatch_format', 'none')
    if selected_format not in supermatch_formats:
        selected_format = 'Best of 5'

    max_rounds = SUPERMATCH_FORMATS[selected_format][0]

    if ranked == 'ranked':
        if selected_armwrestler_1_id:
            armwrestlers_2 = [aw for aw in armwrestlers if aw[0] != selected_armwrestler_1_id]

        if selected_armwrestler_1_id is selected_armwrestler_2_id:
            selected_armwrestler_2_id = None

    armwrestler_ids = [aw[0] for aw in armwrestlers]
    if arm in ['left', 'right'] and \
            ranked == 'ranked' and \
            selected_armwrestler_1_id != selected_armwrestler_2_id and \
            selected_armwrestler_1_id in armwrestler_ids and \
            selected_armwrestler_2_id in armwrestler_ids and \
            selected_format in supermatch_formats:
        calculation_ready = True

    elif arm in ['left', 'right'] and \
            ranked == 'unranked' and \
            selected_armwrestler_1_id in armwrestler_ids and \
            selected_format in supermatch_formats:
        calculation_ready = True

    if calculation_ready:
        if custom_score:
            try:
                armwrestler_1_score = int(request.args.get('custom_score_1', (max_rounds // 2) + 1))
                armwrestler_2_score = int(request.args.get('custom_score_2', (max_rounds - ((max_rounds // 2) + 1))))
                if not (0 <= armwrestler_1_score <= max_rounds and 0 <= armwrestler_2_score <= max_rounds and (0 < (armwrestler_1_score + armwrestler_2_score) <= max_rounds)):
                    raise ValueError
            except (ValueError, TypeError):
                armwrestler_1_score = (max_rounds // 2) + 1
                armwrestler_2_score = (max_rounds - ((max_rounds // 2) + 1))
        else:
            try:
                value_for_score = int(request.args.get('score', (max_rounds // 2) + 1))
            except (ValueError, TypeError):
                value_for_score = (max_rounds // 2) + 1
            armwrestler_1_score, armwrestler_2_score = match_result(max_rounds, value_for_score, SUPERMATCH_FORMATS[selected_format][2])

        if ranked == 'ranked':
            armwrestler_1_elo, armwrestler_2_elo = get_current_elo(arm, [selected_armwrestler_1_id, selected_armwrestler_2_id])
            armwrestler_1_diff, armwrestler_2_diff = diff_supermatch(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score), SUPERMATCH_FORMATS[selected_format][1])
            armwrestler_1_diff, armwrestler_1_color = (f"+{armwrestler_1_diff}", "text-success") if armwrestler_1_diff > 0 else ((str(armwrestler_1_diff),
                                                                                                                                  "text-danger") if armwrestler_1_diff < 0 else ("0", "text-secondary"))
            armwrestler_2_diff, armwrestler_2_color = (f"+{armwrestler_2_diff}", "text-success") if armwrestler_2_diff > 0 else ((str(armwrestler_2_diff),
                                                                                                                                  "text-danger") if armwrestler_2_diff < 0 else ("0", "text-secondary"))

        elif ranked == 'unranked':
            armwrestler_1_elo = get_current_elo(arm, [selected_armwrestler_1_id])[0]
            elo_from_match = expected_elo_from_score(armwrestler_1_elo, (armwrestler_1_score, armwrestler_2_score))

    template_data = {
        'ranked': ranked, 'arm': arm,
        'selected_armwrestler_1_id': selected_armwrestler_1_id, 'selected_armwrestler_2_id': selected_armwrestler_2_id,
        'armwrestlers': armwrestlers, 'armwrestlers_2': armwrestlers_2,
        'supermatch_formats': supermatch_formats, 'selected_format': selected_format,
        'value_for_score': value_for_score, 'max_rounds': max_rounds,
        'armwrestler_1_score': armwrestler_1_score, 'armwrestler_2_score': armwrestler_2_score,
        'armwrestler_1_diff': armwrestler_1_diff, 'armwrestler_2_diff': armwrestler_2_diff,
        'armwrestler_1_color': armwrestler_1_color, 'armwrestler_2_color': armwrestler_2_color,
        'armwrestler_1_elo': armwrestler_1_elo, 'armwrestler_2_elo': armwrestler_2_elo,
        'calculation_ready': calculation_ready, 'elo_from_match': elo_from_match,
        'custom_score': custom_score, 'custom_score_1': armwrestler_1_score, 'custom_score_2': armwrestler_2_score
    }

    if request.headers.get('HX-Request'):
        return render_template('elo_from_match_partial.html', **template_data)
    else:
        return render_template('elo_from_match.html', **template_data)


def get_current_elo(arm, armwrestler_ids):
    if arm not in ['right', 'left']:
        raise ValueError("Invalid arm. Must be 'right' or 'left'.")

    dbarm = 'right_elo' if arm == 'right' else 'left_elo'
    elos = []

    for id in armwrestler_ids:
        result = db_execute('SELECT {} FROM armwrestlers WHERE id = ?'.format(dbarm), id)
        elo = result[0][0]
        elos.append(elo)

    return elos


def get_history_formatted_data(history):
    formatted_data = []
    for record in history:
        armwrestler_1_diff_format, armwrestler_2_diff_format = record[11], record[12]
        armwrestler_1_score_color, armwrestler_2_score_color = record[9], record[10]

        armwrestler_1_diff_format, armwrestler_1_diff_color = (f"+{armwrestler_1_diff_format}", "text-success") if armwrestler_1_diff_format > 0 else (
            (str(armwrestler_1_diff_format), "text-danger") if armwrestler_1_diff_format < 0 else ("0", "text-secondary"))
        armwrestler_2_diff_format, armwrestler_2_diff_color = (f"+{armwrestler_2_diff_format}", "text-success") if armwrestler_2_diff_format > 0 else (
            (str(armwrestler_2_diff_format), "text-danger") if armwrestler_2_diff_format < 0 else ("0", "text-secondary"))
        armwrestler_1_score_color, armwrestler_2_score_color = ("bg-success", "bg-danger") if armwrestler_1_score_color > armwrestler_2_score_color else (
            ("bg-danger", "bg-success") if armwrestler_1_score_color < armwrestler_2_score_color else ("bg-secondary", "bg-secondary"))

        date = datetime.strptime(record[14], "%Y-%m-%d %H:%M:%S").strftime("%d %B %Y")

        formatted_data.append((armwrestler_1_score_color, armwrestler_2_score_color, armwrestler_1_diff_color, armwrestler_2_diff_color, armwrestler_1_diff_format, armwrestler_2_diff_format, date))

    return formatted_data


def match_result(max_rounds, value, format_type):
    if value < 0:
        value = 0
    elif value > max_rounds:
        value = max_rounds

    if format_type == "Best of":
        wins_required = (max_rounds // 2) + 1

        if value < wins_required:
            armwrestler1_score = value
            armwrestler2_score = wins_required
        else:
            armwrestler1_score = wins_required
            armwrestler2_score = max_rounds - value

        if max_rounds % 2 == 0 and value == max_rounds // 2:
            armwrestler1_score = value
            armwrestler2_score = value

    elif format_type == "All rounds":
        armwrestler1_score = value
        armwrestler2_score = max_rounds - value

    elif format_type == "Vendetta":
        wins_required = (max_rounds // 2) + 1

        if value < wins_required:
            armwrestler1_score = value
            armwrestler2_score = (max_rounds - 1) - value
            if value == (wins_required - 1):
                armwrestler2_score = wins_required
        else:
            armwrestler1_score = value - 1
            armwrestler2_score = (max_rounds - 1) - (value - 1)
            if value == wins_required:
                armwrestler1_score = wins_required
                armwrestler2_score = (wins_required - 1)

    return armwrestler1_score, armwrestler2_score


def expected_score_rounds(armwrestler_a_elo, armwrestler_b_elo, format_type, max_rounds=5):
    armwrestler1_score, armwrestler2_score = expected_score(armwrestler_a_elo, armwrestler_b_elo)

    if format_type == "All rounds":
        if armwrestler1_score != armwrestler2_score:
            armwrestler1_score = round(armwrestler1_score * max_rounds)
            armwrestler2_score = round(armwrestler2_score * max_rounds)
        else:
            armwrestler1_score = armwrestler2_score = "Equal"

    elif format_type == "Best of":
        wins_required = (max_rounds // 2) + 1
        if armwrestler1_score > armwrestler2_score:
            factor = wins_required / armwrestler1_score
            armwrestler1_score = wins_required
            armwrestler2_score = round(armwrestler2_score * factor)
            if armwrestler1_score == armwrestler2_score:
                armwrestler2_score -= 1
        elif armwrestler1_score < armwrestler2_score:
            factor = wins_required / armwrestler2_score
            armwrestler2_score = wins_required
            armwrestler1_score = round(armwrestler1_score * factor)
            if armwrestler1_score == armwrestler2_score:
                armwrestler1_score -= 1
        else:
            armwrestler1_score = armwrestler2_score = "Equal"

    elif format_type == "Vendetta":
        max_rounds = max_rounds - 1
        if armwrestler1_score != armwrestler2_score:
            prov1_score = round(armwrestler1_score * max_rounds)
            prov2_score = round(armwrestler2_score * max_rounds)
            if prov1_score != prov2_score:
                armwrestler1_score, armwrestler2_score = prov1_score, prov2_score
            elif armwrestler1_score > armwrestler2_score:
                armwrestler1_score, armwrestler2_score = prov1_score + 1, prov2_score
            else:
                armwrestler1_score, armwrestler2_score = prov1_score, prov2_score + 1
        else:
            armwrestler1_score = armwrestler2_score = "Equal"

    return armwrestler1_score, armwrestler2_score


@app.errorhandler(404)
def page_not_found(e):
    app.logger.error(f"404 Error: {e}, path: {request.path}")
    return render_template('404.html'), 404


@app.errorhandler(500)
def page_not_found(e):
    app.logger.error('Server Error: %s', e, exc_info=True)
    return render_template('500.html'), 500


@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error('Unhandled Exception: %s', e, exc_info=True)
    return render_template('500.html'), 500


if __name__ == "__main__":
    app.run(host='0.0.0.0')
