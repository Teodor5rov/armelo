from config import *
from elo import *
from helpers import *


@app.route('/robots.txt')
def serve_robots_txt():
    return send_from_directory(app.static_folder, 'robots.txt')


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


@app.route("/confirmation_redirect")
def confirmation_redirect():
    redirect = request.args.get('redirect')
    response = make_response("")
    response.headers["HX-Redirect"] = url_for(redirect)
    return response


@app.route("/")
@app.route("/<any(right, left):arm>")
def ranking(arm='right'):
    rank_column = 'right_rank' if arm == 'right' else 'left_rank'
    elo_column = 'right_elo' if arm == 'right' else 'left_elo'
    current_user = session.get('username', None)
    update_ranks()
    active_armwrestlers = db_execute('''
        SELECT {0}, id, name, {1} FROM armwrestlers
        WHERE active_until >= DATE('now') ORDER BY {0} ASC
    '''.format(rank_column, elo_column))

    inactive_armwrestlers = db_execute('''
        SELECT id, name, {0} FROM armwrestlers
        WHERE active_until < DATE('now') ORDER BY {1} DESC
    '''.format(elo_column, elo_column))

    template_data = {
        'active_armwrestlers': active_armwrestlers,
        'inactive_armwrestlers': inactive_armwrestlers,
        'current_user': current_user,
        'arm': arm
    }

    if request.headers.get('HX-Request'):
        return render_template('ranking_partial.html', **template_data)

    return render_template('ranking.html', **template_data)


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
            update_ranks()
        except sqlite3.DatabaseError as error:
            app.logger.error(f"Database error occurred: {error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        return render_template('confirmation_screen.html', message="Member saved", redirect="ranking")

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
        SELECT 
            CASE WHEN a.active_until >= DATE('now') THEN 'active' ELSE 'inactive' END AS current_status,
            a.right_elo, a.left_elo, a.right_rank, a.left_rank,
            a.active_until
        FROM armwrestlers a
        WHERE a.id = ?
    '''

    current_status, current_right_elo, current_left_elo, current_right_rank, current_left_rank, active_until = db_execute(query, id)[0]
    wins, losses = 0, 0

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
        wins_losses = []
        for record in history:
            is_armwrestler1 = record[0] == id

            arm = record[4]
            elo = record[7] if is_armwrestler1 else record[8]
            rank = record[5] if is_armwrestler1 else record[6]

            if (is_armwrestler1 and record[9] > record[10]) or (not is_armwrestler1 and record[9] < record[10]):
                wins += 1
                wins_losses.append("win")
            elif (is_armwrestler1 and record[9] < record[10]) or (not is_armwrestler1 and record[9] > record[10]):
                losses += 1
                wins_losses.append("loss")
            else:
                wins_losses.append("draw")

            if arm == 'right':
                best_right_elo = max(best_right_elo, elo)
                best_right_rank = min(best_right_rank, rank) if best_right_rank is not None else rank
            elif arm == 'left':
                best_left_elo = max(best_left_elo, elo)
                best_left_rank = min(best_left_rank, rank) if best_left_rank is not None else rank

        formatted_data = get_matches_formatted_data(history)
        total_matches = len(history)

    else:
        best_right_elo = current_right_elo
        best_left_elo = current_left_elo
        best_right_rank = current_right_rank
        best_left_rank = current_left_rank
        formatted_data = None
        wins_losses = None
        total_matches = 0

    template_data = {
        'id': id,
        'name': name,
        'current_right_elo': current_right_elo, 'current_left_elo': current_left_elo,
        'current_right_rank': current_right_rank, 'current_left_rank': current_left_rank,
        'best_right_elo': best_right_elo, 'best_left_elo': best_left_elo,
        'best_right_rank': best_right_rank, 'best_left_rank': best_left_rank,
        'current_status': current_status,
        'matches': history, 'formatted_data': formatted_data,
        'wins': wins, 'losses': losses, 'total_matches': total_matches,
        'days_left': days_left, 'wins_losses': wins_losses
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
            update_ranks()
        except sqlite3.DatabaseError as error:
            app.logger.error(f"Database error occurred: {error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        return render_template('confirmation_screen.html', message="New member added", redirect="ranking")

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
            update_ranks()
        except sqlite3.DatabaseError as error:
            app.logger.error(f"Database error occurred: {error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        return render_template('confirmation_screen.html', message="Member deleted", redirect="ranking")

    return render_template('confirm_remove.html', id=id, current_name=current_name)


@app.route("/closest_matches")
def closest_matches():
    arm = request.args.get('arm', 'right')
    rank_column = 'right_rank' if arm == 'right' else 'left_rank'
    elo_column = 'right_elo' if arm == 'right' else 'left_elo'

    supermatch_add = False
    if session.get('username'):
        supermatch_add = True

    query = """
        SELECT 
            a.{0} AS rank1, a.id AS armwrestler1_id, a.name AS armwrestler1, a.{1} AS elo1, 
            b.{0} AS rank2, b.id AS armwrestler2_id, b.name AS armwrestler2, b.{1} AS elo2, 
            ABS(a.{1} - b.{1}) AS elo_difference
        FROM armwrestlers a, armwrestlers b
        WHERE a.name < b.name
        ORDER BY elo_difference ASC
        LIMIT 15;
    """.format(rank_column, elo_column)

    closest_matches = db_execute(query)
    closest_matches_with_predictions = []
    for match in closest_matches:
        binom_predicted_1, binom_predicted_2 = binom_prediction(match[3], match[7])
        binom_predicted_1, binom_predicted_2 = round(binom_predicted_1 * 100, 1), round(binom_predicted_2 * 100, 1)
        color_1, color_2 = (f"success", "danger") if binom_predicted_1 > binom_predicted_2 else ((f"danger", "success") if binom_predicted_1 < binom_predicted_2 else ("secondary", "secondary"))
        match_with_prediction = match + (binom_predicted_1, binom_predicted_2, color_1, color_2)
        closest_matches_with_predictions.append(match_with_prediction)

    template_data = {
        'closest_matches_with_predictions': closest_matches_with_predictions,
        'arm': arm,
        'supermatch_add': supermatch_add
    }

    if request.headers.get('HX-Request'):
        return render_template('closest_matches_partial.html', **template_data)

    return render_template('closest_matches.html', **template_data)


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

    formatted_data = get_matches_formatted_data(history)

    return render_template('history.html', matches=history, formatted_data=formatted_data)


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
        update_ranks()
    except (sqlite3.DatabaseError, IndexError) as error:
        app.logger.error(f"Database error occurred: {error}", exc_info=True)
        app.logger.error(f"Operation context: {request.path} - {request.method}")
    return render_template('confirmation_screen.html', message="Last match deleted", redirect="history")


@app.route("/supermatch", methods=["GET", "POST"])
def supermatch():
    current_user = session.get('username', None)
    unconfirmed = True if current_user else None

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
    error = None

    query = '''
        SELECT
            u.armwrestler1_id, a1.name AS armwrestler1_name,
            u.armwrestler2_id, a2.name AS armwrestler2_name,
            u.arm,
            CASE u.arm WHEN 'right' THEN a1.right_rank WHEN 'left' THEN a1.left_rank END AS armwrestler1_rank,
            CASE u.arm WHEN 'right' THEN a2.right_rank WHEN 'left' THEN a2.left_rank END AS armwrestler2_rank,
            CASE u.arm WHEN 'right' THEN a1.right_elo WHEN 'left' THEN a1.left_elo END AS armwrestler1_elo,
            CASE u.arm WHEN 'right' THEN a2.right_elo WHEN 'left' THEN a2.left_elo END AS armwrestler2_elo,
            u.armwrestler1_score, u.armwrestler2_score,
            u.selected_format,
            u.date,
            u.id
        FROM
            unconfirmed_matches u
        JOIN armwrestlers a1 ON u.armwrestler1_id = a1.id
        JOIN armwrestlers a2 ON u.armwrestler2_id = a2.id
        ORDER BY u.id ASC;
    '''

    db_unconfirmed_matches = db_execute(query)

    unconfirmed_matches = [
        match[:11] + diff_supermatch(match[7], match[8], (match[9], match[10]), SUPERMATCH_FORMATS[match[11]][1]) + match[11:]
        for match in db_unconfirmed_matches
    ]

    formatted_data = get_matches_formatted_data(unconfirmed_matches)

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
        if current_user:
            submit_supermatch(arm, selected_armwrestler_1_id, selected_armwrestler_2_id, armwrestler_1_score, armwrestler_2_score, armwrestler_1_elo, armwrestler_2_elo, selected_format, current_user)
            return render_template('confirmation_screen.html', message="Supermatch added", redirect="supermatch")
        else:
            token = request.form.get("cf-turnstile-response")
            if not token:
                error = 'CAPTCHA error'

            response = requests.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": CLOUDFLARE_SECRET_KEY, "response": token, "remoteip": request.remote_addr}
            )
            result = response.json()

            if result.get("success"):
                submit_unconfirmed_supermatch(arm, selected_armwrestler_1_id, selected_armwrestler_2_id, armwrestler_1_score, armwrestler_2_score, selected_format)
                return render_template('confirmation_screen.html', message="Supermatch added", redirect="supermatch")
            else:
                error = "CAPTCHA verification failed"

    template_data = {
        'current_user': current_user, 'error': error, 'arm': arm,
        'armwrestlers': armwrestlers, 'armwrestlers_2': armwrestlers_2,
        'selected_armwrestler_1_id': selected_armwrestler_1_id, 'selected_armwrestler_2_id': selected_armwrestler_2_id,
        'supermatch_formats': supermatch_formats, 'selected_format': selected_format, 'supermatch_ready': supermatch_ready,
        'value_for_score': value_for_score, 'max_rounds': max_rounds,
        'armwrestler_1_score': armwrestler_1_score, 'armwrestler_2_score': armwrestler_2_score,
        'armwrestler_1_diff': armwrestler_1_diff, 'armwrestler_2_diff': armwrestler_2_diff,
        'armwrestler_1_color': armwrestler_1_color, 'armwrestler_2_color': armwrestler_2_color,
        'armwrestler_1_elo': armwrestler_1_elo, 'armwrestler_2_elo': armwrestler_2_elo,
        'custom_score': custom_score, 'custom_score_1': armwrestler_1_score, 'custom_score_2': armwrestler_2_score,
        'matches': unconfirmed_matches, 'formatted_data': formatted_data, 'unconfirmed': unconfirmed
    }

    if request.headers.get('HX-Request'):
        return render_template('supermatch_partial.html', **template_data)
    else:
        return render_template('supermatch.html', **template_data)


@app.route("/confirm_match", methods=["POST"])
def confirm_match():
    if not session.get('username'):
        return redirect(url_for('login'))

    current_user = session.get('username', None)
    match_id = request.form.get('match_id') or request.args.get('match_id')

    query = '''
        SELECT
            u.armwrestler1_id, a1.name AS armwrestler1_name,
            u.armwrestler2_id, a2.name AS armwrestler2_name,
            u.arm,
            CASE u.arm WHEN 'right' THEN a1.right_rank WHEN 'left' THEN a1.left_rank END AS armwrestler1_rank,
            CASE u.arm WHEN 'right' THEN a2.right_rank WHEN 'left' THEN a2.left_rank END AS armwrestler2_rank,
            CASE u.arm WHEN 'right' THEN a1.right_elo WHEN 'left' THEN a1.left_elo END AS armwrestler1_elo,
            CASE u.arm WHEN 'right' THEN a2.right_elo WHEN 'left' THEN a2.left_elo END AS armwrestler2_elo,
            u.armwrestler1_score, u.armwrestler2_score,
            u.selected_format,
            u.date,
            u.id
        FROM
            unconfirmed_matches u
        JOIN armwrestlers a1 ON u.armwrestler1_id = a1.id
        JOIN armwrestlers a2 ON u.armwrestler2_id = a2.id
        WHERE u.id = ?;
    '''

    db_match = db_execute(query, match_id)

    match = [
        match[:11] + diff_supermatch(match[7], match[8], (match[9], match[10]), SUPERMATCH_FORMATS[match[11]][1]) + match[11:]
        for match in db_match
    ]

    formatted_data = get_matches_formatted_data(match)

    if 'confirm_match' in request.form:
        try:
            match = match[0]
            armwrestler_1_elo, armwrestler_2_elo = get_current_elo(match[4], (match[0], match[2]))
            submit_supermatch(match[4], match[0], match[2], match[9], match[10], armwrestler_1_elo, armwrestler_2_elo, match[13], current_user)
            db_execute("DELETE FROM unconfirmed_matches WHERE id = ?", match_id)
            update_ranks()
        except sqlite3.DatabaseError as error:
            app.logger.error(f"Database error occurred: {error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        return render_template('confirmation_screen.html', message="Match confirmed", redirect="supermatch")
    elif 'remove_match' in request.form:
        try:
            db_execute("DELETE FROM unconfirmed_matches WHERE id = ?", match_id)
        except sqlite3.DatabaseError as error:
            app.logger.error(f"Database error occurred: {error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        return render_template('confirmation_screen.html', message="Match removed", redirect="supermatch")

    return render_template('confirm_match.html', match_id=match_id, matches=match, formatted_data=formatted_data)


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


@app.errorhandler(404)
def page_not_found(e):
    app.logger.error(f"404 Error: {e}, path: {request.path}")
    return render_template('error.html', error_code = "404", error_message = f"Page not found - {request.path}"), 404


@app.errorhandler(500)
def page_not_found(e):
    app.logger.error('Server Error: %s', e, exc_info=True)
    return render_template('error.html', error_code = "500", error_message = f"Internal server error"), 500

@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error('Unhandled Exception: %s', e, exc_info=True)
    return render_template('error.html', error_code = "500", error_message = f"Unhandled exception"), 500


if __name__ == "__main__":
    app.run(host='0.0.0.0')
