from flask import Flask, render_template, request, redirect, url_for, session, g, send_from_directory
from werkzeug.security import check_password_hash
import sqlite3

from elo import diff_supermatch, calculate_elo_with_bonus

DATABASE = 'database.db'

app = Flask(__name__)
app.secret_key = '%%8hF$7ALEy8Msw2'


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db


def db_execute(query, *args):
    db = get_db()
    cur = db.cursor()
    cur.execute(query, args)
    if query.strip().upper().startswith("SELECT"):
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


@app.route('/robots.txt')
def serve_robots_txt():
    return send_from_directory(app.static_folder, 'robots.txt')


@app.route("/")
@app.route("/<arm>")
def ranking(arm='right'):
    order_by = 'right_elo' if arm == 'right' else 'left_elo'
    armwrestlers = db_execute(f'SELECT RANK() OVER (ORDER BY {order_by} DESC) AS rank, name, {order_by} FROM armwrestlers')
    username = session.get('username')
    return render_template('ranking.html', armwrestlers=armwrestlers, username=username, arm=arm)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
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


@app.route("/add_new_member", methods=["GET", "POST"])
def add_new_member():
    if not session.get('username'):
        return redirect(url_for('login'))

    if request.method == "POST":
        name = request.form['name']
        right_elo = int(request.form['right_elo'])
        left_elo = int(request.form['left_elo'])

        armwrestlers = db_execute('SELECT name FROM armwrestlers')
        armwrestler_names = [aw[0] for aw in armwrestlers]

        if 0 < right_elo < 10000 and 0 < left_elo < 10000 and name not in armwrestler_names:
            try:
                db_execute("INSERT INTO armwrestlers (name, right_elo, left_elo) VALUES (?, ?, ?)", name, right_elo, left_elo)
                return redirect(url_for('ranking', arm='right'))
            except sqlite3.DatabaseError as error:
                print(error)
        else:
            return render_template('add_new_member.html', error="Name already taken or invalid data")
    return render_template('add_new_member.html')


@app.route("/remove_member", methods=["POST"])
def remove_member():
    if not session.get('username'):
        return redirect(url_for('login'))

    name = request.form['name']
    try:
        db_execute("DELETE FROM armwrestlers WHERE name = ?", name)
    except sqlite3.DatabaseError as error:
        print(error)
    return redirect(url_for('ranking'))


@app.route("/history")
def history():
    history = db_execute('SELECT * FROM history ORDER BY id DESC LIMIT 20')
    colors = []
    for record in history:
        armwrestler_1_diff, armwrestler_2_diff = record[10], record[11]
        armwrestler_1_diff, armwrestler_1_color = (f"+{armwrestler_1_diff}", "text-success") if armwrestler_1_diff > 0 else ((str(armwrestler_1_diff), "text-danger") if armwrestler_1_diff < 0 else ("0", "text-secondary"))
        armwrestler_2_diff, armwrestler_2_color = (f"+{armwrestler_2_diff}", "text-success") if armwrestler_2_diff > 0 else ((str(armwrestler_2_diff), "text-danger") if armwrestler_2_diff < 0 else ("0", "text-secondary"))
        colors.append((armwrestler_1_color, armwrestler_2_color, armwrestler_1_diff, armwrestler_2_diff))

    return render_template('history.html', history=history, colors=colors)


@app.route("/supermatch", methods=["GET", "POST"])
def supermatch():
    if not session.get('username'):
        return redirect(url_for('login'))

    # Initialize default values
    arm = 'right'
    selected_armwrestler_1 = 'none'

    # Fetch all armwrestlers from the database
    armwrestlers = db_execute('SELECT name FROM armwrestlers ORDER BY LOWER(name)')

    if request.method == "POST":

        # Initialize default values
        supermatch_ready = False
        armwrestler_1_diff = None
        armwrestler_2_diff = None
        armwrestler_1_color = None
        armwrestler_2_color = None

        # Get the values from the form 
        arm = request.form.get('arm', arm)
        selected_armwrestler_1 = request.form.get('armwrestler1', 'none')
        selected_armwrestler_2 = request.form.get('armwrestler2', 'none')
        if selected_armwrestler_1 == selected_armwrestler_2:
            selected_armwrestler_2 = 'none'
        armwrestlers_2 = [aw for aw in armwrestlers if aw[0] != selected_armwrestler_1] if selected_armwrestler_1 != 'none' else None
        armwrestler_1_score = int(request.form.get('score', 3))
        armwrestler_2_score = 5 - armwrestler_1_score

        # Checks if all conditions are met for supermatch ready
        armwrestler_names = [aw[0] for aw in armwrestlers]
        if arm in ['left', 'right'] and \
                selected_armwrestler_1 != selected_armwrestler_2 and \
                selected_armwrestler_1 in armwrestler_names and \
                selected_armwrestler_2 in armwrestler_names and \
                armwrestler_1_score + armwrestler_2_score == 5:
            armwrestler_1_elo, armwrestler_2_elo = get_current_elo(arm, [selected_armwrestler_1, selected_armwrestler_2])
            armwrestler_1_diff, armwrestler_2_diff = diff_supermatch(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score))
            armwrestler_1_diff, armwrestler_1_color = (f"+{armwrestler_1_diff}", "text-success") if armwrestler_1_diff > 0 else ((str(armwrestler_1_diff), "text-danger") if armwrestler_1_diff < 0 else ("0", "text-secondary"))
            armwrestler_2_diff, armwrestler_2_color = (f"+{armwrestler_2_diff}", "text-success") if armwrestler_2_diff > 0 else ((str(armwrestler_2_diff), "text-danger") if armwrestler_2_diff < 0 else ("0", "text-secondary"))
            supermatch_ready = True

        submit_pressed = 'submit_match' in request.form
        if submit_pressed and supermatch_ready:
            submit_supermatch(arm, selected_armwrestler_1, selected_armwrestler_2, armwrestler_1_score, armwrestler_2_score, armwrestler_1_elo, armwrestler_2_elo)
            return redirect(url_for('ranking'))

        return render_template('supermatch_partial.html',
                               arm=arm,
                               armwrestlers=armwrestlers, armwrestlers_2=armwrestlers_2,
                               selected_armwrestler_1=selected_armwrestler_1, selected_armwrestler_2=selected_armwrestler_2,
                               supermatch_ready=supermatch_ready,
                               armwrestler_1_score=armwrestler_1_score, armwrestler_2_score=armwrestler_2_score,
                               armwrestler_1_diff=armwrestler_1_diff, armwrestler_2_diff=armwrestler_2_diff,
                               armwrestler_1_color=armwrestler_1_color,
                               armwrestler_2_color=armwrestler_2_color
                               )

    return render_template('supermatch.html',
                           arm=arm,
                           armwrestlers=armwrestlers,
                           selected_armwrestler_1=selected_armwrestler_1
                           )


def get_current_elo(arm, armwrestlers):
    dbarm = 'right_elo' if arm == 'right' else 'left_elo'
    elos = []

    for armwrestler in armwrestlers:
        result = db_execute(f'SELECT {dbarm} FROM armwrestlers WHERE name = ?', armwrestler)
        elo = result[0][0]
        elos.append(elo)

    return elos


def submit_supermatch(arm, armwrestler_1, armwrestler_2, armwrestler_1_score, armwrestler_2_score, armwrestler_1_elo, armwrestler_2_elo):

    dbarm = 'right_elo' if arm == 'right' else 'left_elo'
    updated_1, updated_2 = calculate_elo_with_bonus(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score))

    armwrestler_1_rank = db_execute(f'SELECT rank FROM ( SELECT RANK() OVER (ORDER BY {dbarm} DESC) AS rank, name FROM armwrestlers ) AS RankedArmwrestlers WHERE name = ?', armwrestler_1)[0][0]
    armwrestler_2_rank = db_execute(f'SELECT rank FROM ( SELECT RANK() OVER (ORDER BY {dbarm} DESC) AS rank, name FROM armwrestlers ) AS RankedArmwrestlers WHERE name = ?', armwrestler_2)[0][0]
    armwrestler_1_diff, armwrestler_2_diff = diff_supermatch(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score))

    try:
        query = '''
        INSERT INTO history ( 
        armwrestler1_name, armwrestler2_name, 
        arm, 
        armwrestler1_rank, armwrestler2_rank, 
        armwrestler1_elo, armwrestler2_elo, 
        armwrestler1_score, armwrestler2_score, 
        armwrestler1_elo_diff, armwrestler2_elo_diff ) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        db_execute(query, armwrestler_1 ,armwrestler_2, arm, 
                   armwrestler_1_rank, armwrestler_2_rank, 
                   armwrestler_1_elo, armwrestler_2_elo, 
                   armwrestler_1_score, armwrestler_2_score,
                   armwrestler_1_diff, armwrestler_2_diff)
        
        db_execute(f"UPDATE armwrestlers SET {dbarm} = ? WHERE name = ?", updated_1, armwrestler_1)
        db_execute(f"UPDATE armwrestlers SET {dbarm} = ? WHERE name = ?", updated_2, armwrestler_2)
    except sqlite3.DatabaseError as error:
        print(error)


if __name__ == "__main__":
    app.run(host='0.0.0.0')
