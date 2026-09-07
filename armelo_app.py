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
        if user and check_password_hash(user[0]['password_hash'], password):
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
    active_armwrestlers = db_execute('''
        SELECT {0} AS rank, id, name, {1} AS elo FROM armwrestlers
        WHERE active_until >= DATE('now') AND NOT hidden ORDER BY rank ASC
    '''.format(rank_column, elo_column))

    inactive_armwrestlers = db_execute('''
        SELECT id, name, {0} AS elo FROM armwrestlers
        WHERE active_until < DATE('now') AND NOT hidden ORDER BY elo DESC
    '''.format(elo_column))

    badge_data = db_execute('''
        SELECT armwrestler_badges.armwrestler_id, badges.name, badges.color
        FROM armwrestler_badges
        JOIN badges ON armwrestler_badges.badge_id = badges.id
        WHERE armwrestler_badges.arm = ?
    ''', arm)

    armwrestler_badges_dict = {}
    for badge in badge_data:
        armwrestler_badges_dict.setdefault(badge['armwrestler_id'], []).append((badge['name'], badge['color']))

    template_data = {
        'active_armwrestlers': active_armwrestlers,
        'inactive_armwrestlers': inactive_armwrestlers,
        'current_user': current_user,
        'arm': arm,
        'armwrestler_badges_dict': armwrestler_badges_dict
    }

    if is_htmx():
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
    current_name = name_result[0]['name']
    name = request.form.get('name', current_name)
    current_status = db_execute('''SELECT CASE WHEN active_until >= DATE('now') THEN 'active' ELSE 'inactive' END AS current_status FROM armwrestlers WHERE id = ?''', id)[0]['current_status']
    armwrestlers = db_execute('SELECT name FROM armwrestlers ORDER BY LOWER(name)')
    right_elo = request.form.get('right_elo', str(get_current_elo("right", [id])[0]))
    left_elo = request.form.get('left_elo', str(get_current_elo("left", [id])[0]))
    selected_status = request.form.get('selected_status', current_status)
    member_ready = False
    error = None

    if not name and request.method == "POST":
        error = "No name entered"

    armwrestler_names = [aw['name'] for aw in armwrestlers]
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
                    active_until_date = today + timedelta(days=30)
                    active_until_str = active_until_date.strftime('%Y-%m-%d')
                elif selected_status == status_options[1]:
                    today = datetime.today()
                    active_until_date = today - timedelta(days=1)
                    active_until_str = active_until_date.strftime('%Y-%m-%d')
                db_execute("UPDATE armwrestlers SET name = ?, right_elo = ?, left_elo = ?, active_until = ?, last_edited_by = ? WHERE id = ?", name, right_elo, left_elo, active_until_str, current_user, id)
            else:
                db_execute("UPDATE armwrestlers SET name = ?, right_elo = ?, left_elo = ? WHERE id = ?", name, right_elo, left_elo, id)
            update_ranks()
        except sqlite3.DatabaseError as db_error:
            app.logger.error(f"Database error occurred: {db_error}", exc_info=True)
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

    if is_htmx():
        return render_template('edit_member_partial.html', **template_data)
    else:
        return render_template('edit_member.html', **template_data)


@app.route("/view_member", methods=["GET"])
def view_member():

    try:
        id = int(request.args.get('id'))
    except (ValueError, IndexError):
        raise NotFound()
    
    if 'arm' not in request.args:
        return redirect(url_for('view_member', id=id, arm='right'))
    
    arm = get_arm()

    name_result = db_execute('SELECT name FROM armwrestlers WHERE id = ?', id)
    if not name_result:
        raise NotFound()
    name = name_result[0]['name']

    query = '''
        SELECT 
            CASE WHEN a.hidden THEN 'hidden' WHEN a.active_until >= DATE('now') THEN 'active' ELSE 'inactive' END AS current_status,
            a.right_elo, a.left_elo, a.right_rank, a.left_rank,
            a.active_until
        FROM armwrestlers a
        WHERE a.id = ?
    '''

    current_status, current_right_elo, current_left_elo, current_right_rank, current_left_rank, active_until = db_execute(query, id)[0]
    wins, losses = 0, 0

    active_until_date = datetime.strptime(active_until, '%Y-%m-%d')
    days_left = (active_until_date - datetime.today()).days + 1
    days_left = days_left if days_left >= 0 else "inactive"

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

    selected_arm_history = []

    if history:
        best_right_elo = current_right_elo
        best_left_elo = current_left_elo
        best_right_rank = current_right_rank
        best_left_rank = current_left_rank
        wins_losses = []
        for record in history:
            is_armwrestler1 = record['armwrestler1_id'] == id

            match_arm = record['arm']
            elo = record['armwrestler1_elo'] if is_armwrestler1 else record['armwrestler2_elo']
            rank = record['armwrestler1_rank'] if is_armwrestler1 else record['armwrestler2_rank']
            my_score, opponent_score = (record['armwrestler1_score'], record['armwrestler2_score']) if is_armwrestler1 else (record['armwrestler2_score'], record['armwrestler1_score'])

            if my_score > opponent_score:
                wins += 1
                if match_arm == arm:
                    wins_losses.append("win")
            elif my_score < opponent_score:
                losses += 1
                if match_arm == arm:
                    wins_losses.append("loss")
            elif match_arm == arm:
                wins_losses.append("draw")

            if match_arm == 'right':
                best_right_elo = max(best_right_elo, elo)
                best_right_rank = min(best_right_rank, rank) if best_right_rank is not None else rank
                if arm == 'right':
                    selected_arm_history.append(record)
            elif match_arm == 'left':
                best_left_elo = max(best_left_elo, elo)
                best_left_rank = min(best_left_rank, rank) if best_left_rank is not None else rank
                if arm == 'left':
                    selected_arm_history.append(record)

        formatted_data = get_matches_formatted_data(selected_arm_history)
        total_matches = len(history)

    else:
        best_right_elo = current_right_elo
        best_left_elo = current_left_elo
        best_right_rank = current_right_rank
        best_left_rank = current_left_rank
        formatted_data = None
        wins_losses = None
        total_matches = 0

    badges_for_arm = db_execute('''
        SELECT badges.name, badges.color
        FROM armwrestler_badges
        JOIN badges ON armwrestler_badges.badge_id = badges.id
        WHERE armwrestler_badges.armwrestler_id = ? AND armwrestler_badges.arm = ?
    ''', id, arm)

    template_data = {
        'id': id,
        'name': name,
        'current_right_elo': current_right_elo, 'current_left_elo': current_left_elo,
        'current_right_rank': current_right_rank, 'current_left_rank': current_left_rank,
        'best_right_elo': best_right_elo, 'best_left_elo': best_left_elo,
        'best_right_rank': best_right_rank, 'best_left_rank': best_left_rank,
        'current_status': current_status,
        'matches': selected_arm_history, 'formatted_data': formatted_data,
        'wins': wins, 'losses': losses, 'total_matches': total_matches,
        'days_left': days_left, 'wins_losses': wins_losses,
        'arm': arm,
        'badges_for_arm': badges_for_arm
    }

    if is_htmx():
        return render_template('view_member_partial.html', **template_data)

    return render_template('view_member.html', **template_data)


@app.route("/add_new_member", methods=["GET", "POST"])
def add_new_member():
    if not session.get('username'):
        return redirect(url_for('login'))

    current_user = session.get('username')
    if request.method == "GET":
        name = db_execute('SELECT new_member_name FROM new_member WHERE id = 1')[0][0]
    else:
        name = request.form.get('name', '').strip()
        try:
            db_execute("INSERT OR REPLACE INTO new_member (id, new_member_name) VALUES (?, ?)", 1, name)
        except sqlite3.DatabaseError as db_error:
            app.logger.error(f"Database error occurred: {db_error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
    arm = get_arm()
    armwrestlers = db_execute('SELECT id, name FROM armwrestlers ORDER BY LOWER(name)')
    try:
        selected_armwrestler_2_id = int(request.form.get('armwrestler2')) if request.form.get('armwrestler2') else None
        selected_armwrestler_2_name = db_execute('SELECT name FROM armwrestlers WHERE id = ?', selected_armwrestler_2_id)[0][0] if selected_armwrestler_2_id else 'none'
    except (ValueError, IndexError):
        selected_armwrestler_2_id = None
        selected_armwrestler_2_name = 'none'
    supermatch_formats = list(SUPERMATCH_FORMATS.keys())
    value_for_score = None
    custom_score = request.form.get('custom_score', False)
    armwrestler_1_score, armwrestler_2_score = None, None
    calculation_ready = False
    member_ready = False
    elo_from_match = None
    error = None

    if (not name or name == '') and request.method == "POST":
        error = "No name entered"

    armwrestler_names = [aw['name'] for aw in armwrestlers]
    if name in armwrestler_names:
        error = "Name already taken"

    selected_format = request.form.get('supermatch_format', 'none')
    if selected_format not in supermatch_formats:
        selected_format = '10 round Speculative'

    max_rounds = SUPERMATCH_FORMATS[selected_format][0]

    if arm in ['left', 'right'] and selected_armwrestler_2_name in armwrestler_names:
        calculation_ready = True

    if calculation_ready:
        if custom_score:
            try:
                armwrestler_1_score = int(request.form.get('custom_score_1', (max_rounds // 2) + 1))
                armwrestler_2_score = int(request.form.get('custom_score_2', (max_rounds - ((max_rounds // 2) + 1))))
                if not (0 <= armwrestler_1_score <= max_rounds and 0 <= armwrestler_2_score <= max_rounds):
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
            submit_new_member_match(arm, 1, selected_armwrestler_2_id, armwrestler_1_score, armwrestler_2_score, selected_format)

    if 'reset' in request.form:
        selected_armwrestler_2_id, selected_armwrestler_2_name = None, 'none'
        name = None
        try:
            db_execute("INSERT OR REPLACE INTO new_member (id, new_member_name) VALUES (?, ?)", 1, None)
            db_execute("DELETE FROM new_member_matches")
        except sqlite3.DatabaseError as db_error:
            app.logger.error(f"Database error occurred: {db_error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        calculation_ready = False
    
    matches_query = '''
    SELECT
        m.id,
        nm.new_member_name       AS armwrestler1_name,
        m.armwrestler2_id        AS armwrestler2_id,
        aw2.name                 AS armwrestler2_name,
        m.arm,
        m.armwrestler1_score,
        m.armwrestler2_score,
        m.selected_format,
        m.elo_from_match,
    CASE
        WHEN m.arm = 'right' THEN aw2.right_elo
        ELSE aw2.left_elo
    END                       AS armwrestler2_elo,
    CASE
        WHEN m.arm = 'right' THEN aw2.right_rank
        ELSE aw2.left_rank
    END                       AS armwrestler2_rank
    FROM new_member_matches AS m
    JOIN new_member         AS nm  ON m.new_member_id   = nm.id
    JOIN armwrestlers       AS aw2 ON m.armwrestler2_id = aw2.id
    WHERE arm = ?
    ORDER BY m.id DESC;
    '''

    calculated_elo_query = """
    SELECT
        COALESCE(AVG(CASE WHEN arm = 'right' THEN elo_from_match END), 0) AS right_elo,
        COALESCE(AVG(CASE WHEN arm = 'left'  THEN elo_from_match END), 0) AS left_elo
    FROM new_member_matches;
    """

    new_member_matches = db_execute(matches_query, arm)
    right_elo, left_elo = map(round, db_execute(calculated_elo_query)[0])

    if name and name != '' and name not in armwrestler_names and \
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
            db_execute("INSERT OR REPLACE INTO new_member (id, new_member_name) VALUES (?, ?)", 1, None)
            db_execute("DELETE FROM new_member_matches")

            update_badges()
            update_ranks()
        except sqlite3.DatabaseError as db_error:
            app.logger.error(f"Database error occurred: {db_error}", exc_info=True)
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
        'new_member_matches': new_member_matches,
        'elo_from_match': elo_from_match,
        'member_ready': member_ready,
        'custom_score': custom_score, 'custom_score_1': armwrestler_1_score, 'custom_score_2': armwrestler_2_score,
        'error': error
    }

    if is_htmx():
        return render_template('add_new_member_partial.html', **template_data)
    else:
        return render_template('add_new_member.html', **template_data)


@app.route("/remove_new_member_match", methods=["POST"])
def remove_new_member_match():
    if not session.get('username'):
        return redirect(url_for('login'))

    match_id = request.form.get('match_id') or request.args.get('match_id')

    match_query = '''
    SELECT
        m.id,
        nm.new_member_name       AS armwrestler1_name,
        m.armwrestler2_id        AS armwrestler2_id,
        aw2.name                 AS armwrestler2_name,
        m.arm,
        m.armwrestler1_score,
        m.armwrestler2_score,
        m.selected_format,
        m.elo_from_match,
    CASE
        WHEN m.arm = 'right' THEN aw2.right_elo
        ELSE aw2.left_elo
    END                       AS armwrestler2_elo,
    CASE
        WHEN m.arm = 'right' THEN aw2.right_rank
        ELSE aw2.left_rank
    END                       AS armwrestler2_rank
    FROM new_member_matches AS m
    JOIN new_member         AS nm  ON m.new_member_id   = nm.id
    JOIN armwrestlers       AS aw2 ON m.armwrestler2_id = aw2.id
    WHERE m.id = ?;
    '''

    match = db_execute(match_query, match_id)

    if 'remove_match' in request.form:
        try:
            db_execute("DELETE FROM new_member_matches WHERE id = ?", match_id)
        except sqlite3.DatabaseError as db_error:
            app.logger.error(f"Database error occurred: {db_error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        return redirect(url_for('add_new_member'))

    return render_template('remove_new_member_match.html', match_id=match_id, new_member_matches=match)


@app.route("/confirm_remove", methods=["POST"])
def confirm_remove():
    if not session.get('username'):
        return redirect(url_for('login'))

    try:
        id = int(request.form.get('id')) or int(request.args.get('id'))
    except (ValueError, IndexError):
        raise NotFound()
    current_name = request.form.get('current_name') or request.args.get('current_name')

    has_history = bool(db_execute('SELECT 1 FROM history WHERE armwrestler1_id = ? OR armwrestler2_id = ? LIMIT 1', id, id))

    if 'confirm_remove' in request.form:
        try:
            if has_history:
                db_execute("UPDATE armwrestlers SET hidden = 1 WHERE id = ?", id)
                message = "Member hidden from rankings"
            else:
                db_execute("DELETE FROM unconfirmed_matches WHERE armwrestler1_id = ? OR armwrestler2_id = ?", id, id)
                db_execute("DELETE FROM new_member_matches WHERE armwrestler2_id = ?", id)
                db_execute("DELETE FROM armwrestler_badges WHERE armwrestler_id = ?", id)
                db_execute("DELETE FROM armwrestlers WHERE id = ?", id)
                message = "Member deleted"
            update_ranks()
        except sqlite3.DatabaseError as db_error:
            app.logger.error(f"Database error occurred: {db_error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        return render_template('confirmation_screen.html', message=message, redirect="ranking")

    return render_template('confirm_remove.html', id=id, current_name=current_name, has_history=has_history)


@app.route("/closest_matches")
def closest_matches():
    arm = get_arm()
    rank_column = 'right_rank' if arm == 'right' else 'left_rank'
    elo_column = 'right_elo' if arm == 'right' else 'left_elo'

    supermatch_add = False
    if session.get('username'):
        supermatch_add = True

    query = """
        SELECT
            a.{0} AS rank1, a.id AS armwrestler1_id, a.name AS armwrestler1_name, a.{1} AS elo1,
            b.{0} AS rank2, b.id AS armwrestler2_id, b.name AS armwrestler2_name, b.{1} AS elo2,
            ABS(a.{1} - b.{1}) AS elo_difference
        FROM armwrestlers a, armwrestlers b
        WHERE a.name < b.name
        ORDER BY elo_difference ASC
        LIMIT 15;
    """.format(rank_column, elo_column)

    closest_matches = db_execute(query)
    closest_matches_with_predictions = []
    for match in closest_matches:
        win1, win2 = binom_prediction(match['elo1'], match['elo2'])
        color1, color2 = ('success', 'danger') if win1 > win2 else (('danger', 'success') if win1 < win2 else ('secondary', 'secondary'))
        closest_matches_with_predictions.append({**match, 'win1': round(win1 * 100, 1), 'win2': round(win2 * 100, 1), 'color1': color1, 'color2': color2})

    template_data = {
        'closest_matches_with_predictions': closest_matches_with_predictions,
        'arm': arm,
        'supermatch_add': supermatch_add
    }

    if is_htmx():
        return render_template('closest_matches_partial.html', **template_data)

    return render_template('closest_matches.html', **template_data)


@app.route("/history")
def history():
    selected_year = request.args.get('year', 'last_12_months')
    selected_month = m if (m := request.args.get('month', type=int)) in range(1, 13) else None
    today = datetime.now()
    current_year = today.year

    if selected_year == "last_12_months":
        selected_month = None
        start_date = today - timedelta(days=365)
        end_date = today + timedelta(days=1)
    else:
        try:
            selected_year = int(selected_year)
        except ValueError:
            selected_year = current_year

        if selected_month:
            start_date = datetime(selected_year, selected_month, 1)
            if selected_month == 12:
                end_date = datetime(selected_year + 1, 1, 1)
            else:
                end_date = datetime(selected_year, selected_month + 1, 1)
        else:
            start_date = datetime(selected_year, 1, 1)
            end_date = datetime(selected_year + 1, 1, 1)

    year_rows = db_execute("SELECT DISTINCT STRFTIME('%Y', date) FROM history ORDER BY 1 DESC")
    years = [int(r[0]) for r in year_rows]
    if current_year not in years:
        years.insert(0, current_year)
    months = list(enumerate(month_name))[1:]

    query = '''
        SELECT a1.id AS armwrestler1_id, a1.name AS armwrestler1_name,
               a2.id AS armwrestler2_id, a2.name AS armwrestler2_name,
               h.arm, h.armwrestler1_rank, h.armwrestler2_rank,
               h.armwrestler1_elo, h.armwrestler2_elo,
               h.armwrestler1_score, h.armwrestler2_score,
               h.armwrestler1_elo_diff, h.armwrestler2_elo_diff,
               h.selected_format, h.date
        FROM history h
        JOIN armwrestlers a1 ON h.armwrestler1_id = a1.id
        JOIN armwrestlers a2 ON h.armwrestler2_id = a2.id
        WHERE h.date >= ? AND h.date < ?
        ORDER BY h.id DESC
    '''
    params = [start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')]
    matches = db_execute(query, *params)
    total_matches = db_execute('SELECT COUNT(*) FROM history')[0][0]
    formatted_data = get_matches_formatted_data(matches)

    template_data = {
        'matches': matches, 'formatted_data': formatted_data,
        'total_matches': total_matches,
        'months': months, 'years': years,
        'selected_month': selected_month, 'selected_year': selected_year
    }

    return render_template('history.html', **template_data)

@app.route("/undo_last_match", methods=["POST"])
def undo_last_match():
    if not session.get('username'):
        return redirect(url_for('login'))

    if 'undo_match' in request.form:
        try:
            match_id, armwrestler1_id, armwrestler2_id, arm, armwrestler1_elo, armwrestler2_elo, match_date = db_execute(
                'SELECT id, armwrestler1_id, armwrestler2_id, arm, armwrestler1_elo, armwrestler2_elo, date FROM history ORDER BY id DESC LIMIT 1')[0]
            dbarm = 'right_elo' if arm == 'right' else 'left_elo'
            for armwrestler_id, elo in ((armwrestler1_id, armwrestler1_elo), (armwrestler2_id, armwrestler2_elo)):
                previous = db_execute('SELECT MAX(date) FROM history WHERE id < ? AND (armwrestler1_id = ? OR armwrestler2_id = ?)', match_id, armwrestler_id, armwrestler_id)[0][0]
                active_until = (datetime.strptime(previous or match_date, '%Y-%m-%d %H:%M:%S') + timedelta(days=180)).strftime('%Y-%m-%d')
                db_execute(f"UPDATE armwrestlers SET {dbarm} = ?, active_until = ? WHERE id = ?", elo, active_until, armwrestler_id)
            db_execute('DELETE FROM history WHERE id = (SELECT MAX(id) FROM history)')
            update_badges()
            update_ranks()
        except (sqlite3.DatabaseError, IndexError) as db_error:
            app.logger.error(f"Database error occurred: {db_error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        return render_template('confirmation_screen.html', message="Last match deleted", redirect="history")

    match = db_execute('''
        SELECT a1.id AS armwrestler1_id, a1.name AS armwrestler1_name,
               a2.id AS armwrestler2_id, a2.name AS armwrestler2_name,
               h.arm, h.armwrestler1_rank, h.armwrestler2_rank,
               h.armwrestler1_elo, h.armwrestler2_elo,
               h.armwrestler1_score, h.armwrestler2_score,
               h.armwrestler1_elo_diff, h.armwrestler2_elo_diff,
               h.selected_format, h.date
        FROM history h
        JOIN armwrestlers a1 ON h.armwrestler1_id = a1.id
        JOIN armwrestlers a2 ON h.armwrestler2_id = a2.id
        WHERE h.id = (SELECT MAX(id) FROM history)
    ''')
    formatted_data = get_matches_formatted_data(match)
    return render_template('confirm_undo_last_match.html', matches=match, formatted_data=formatted_data)


@app.route("/supermatch", methods=["GET", "POST"])
def supermatch():
    current_user = session.get('username', None)
    can_confirm_matches = True if current_user else None

    arm = get_arm()
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

    unconfirmed_matches = []
    for match in db_unconfirmed_matches:
        diff1, diff2 = elo_diff_from_match(match['armwrestler1_elo'], match['armwrestler2_elo'], (match['armwrestler1_score'], match['armwrestler2_score']), SUPERMATCH_FORMATS[match['selected_format']][1])
        unconfirmed_matches.append({**match, 'armwrestler1_elo_diff': diff1, 'armwrestler2_elo_diff': diff2})

    formatted_data = get_matches_formatted_data(unconfirmed_matches)

    selected_format = request.form.get('supermatch_format', 'none')
    if selected_format not in supermatch_formats:
        selected_format = 'Best of 5'

    max_rounds = SUPERMATCH_FORMATS[selected_format][0]

    if selected_armwrestler_1_id:
        armwrestlers_2 = [aw for aw in armwrestlers if aw['id'] != selected_armwrestler_1_id]

    if selected_armwrestler_1_id == selected_armwrestler_2_id:
        selected_armwrestler_2_id = None

    # Checks if all conditions are met for supermatch ready
    armwrestler_ids = [aw['id'] for aw in armwrestlers]
    if arm in ['left', 'right'] and \
            selected_armwrestler_1_id != selected_armwrestler_2_id and \
            selected_armwrestler_1_id in armwrestler_ids and \
            selected_armwrestler_2_id in armwrestler_ids and \
            selected_format in supermatch_formats:
        if custom_score:
            try:
                armwrestler_1_score = int(request.form.get('custom_score_1', (max_rounds // 2) + 1))
                armwrestler_2_score = int(request.form.get('custom_score_2', (max_rounds - ((max_rounds // 2) + 1))))
                if not (0 <= armwrestler_1_score <= max_rounds and 0 <= armwrestler_2_score <= max_rounds):
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
        armwrestler_1_diff, armwrestler_2_diff = elo_diff_from_match(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score), SUPERMATCH_FORMATS[selected_format][1])
        armwrestler_1_diff, armwrestler_1_color = (f"+{armwrestler_1_diff}", "text-success") if armwrestler_1_diff > 0 else ((str(armwrestler_1_diff),
                                                                                                                              "text-danger") if armwrestler_1_diff < 0 else ("0", "text-secondary"))
        armwrestler_2_diff, armwrestler_2_color = (f"+{armwrestler_2_diff}", "text-success") if armwrestler_2_diff > 0 else ((str(armwrestler_2_diff),
                                                                                                                              "text-danger") if armwrestler_2_diff < 0 else ("0", "text-secondary"))
        supermatch_ready = True

    submit_pressed = 'submit_match' in request.form
    if submit_pressed and supermatch_ready:
        if current_user:
            submit_match(arm, selected_armwrestler_1_id, selected_armwrestler_2_id, armwrestler_1_score, armwrestler_2_score, armwrestler_1_elo, armwrestler_2_elo, selected_format, current_user)
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
        'matches': unconfirmed_matches, 'formatted_data': formatted_data, 'can_confirm_matches': can_confirm_matches
    }

    if is_htmx():
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

    match = []
    for db_match_row in db_match:
        diff1, diff2 = elo_diff_from_match(db_match_row['armwrestler1_elo'], db_match_row['armwrestler2_elo'], (db_match_row['armwrestler1_score'], db_match_row['armwrestler2_score']), SUPERMATCH_FORMATS[db_match_row['selected_format']][1])
        match.append({**db_match_row, 'armwrestler1_elo_diff': diff1, 'armwrestler2_elo_diff': diff2})

    formatted_data = get_matches_formatted_data(match)

    if 'confirm_match' in request.form:
        try:
            match = match[0]
            armwrestler_1_elo, armwrestler_2_elo = get_current_elo(match['arm'], (match['armwrestler1_id'], match['armwrestler2_id']))
            submit_match(match['arm'], match['armwrestler1_id'], match['armwrestler2_id'], match['armwrestler1_score'], match['armwrestler2_score'], armwrestler_1_elo, armwrestler_2_elo, match['selected_format'], current_user)
            db_execute("DELETE FROM unconfirmed_matches WHERE id = ?", match['id'])
            update_ranks()
        except sqlite3.DatabaseError as db_error:
            app.logger.error(f"Database error occurred: {db_error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        return render_template('confirmation_screen.html', message="Match confirmed", redirect="supermatch")
    elif 'remove_match' in request.form:
        try:
            db_execute("DELETE FROM unconfirmed_matches WHERE id = ?", match_id)
        except sqlite3.DatabaseError as db_error:
            app.logger.error(f"Database error occurred: {db_error}", exc_info=True)
            app.logger.error(f"Operation context: {request.path} - {request.method}")
        return render_template('confirmation_screen.html', message="Match removed", redirect="supermatch")

    return render_template('confirm_match.html', match_id=match_id, matches=match, formatted_data=formatted_data)


@app.route("/prediction")
def prediction():

    arm = get_arm()
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
        armwrestlers_2 = [aw for aw in armwrestlers if aw['id'] != selected_armwrestler_1_id]

    if selected_armwrestler_1_id == selected_armwrestler_2_id:
        selected_armwrestler_2_id = None

    armwrestler_ids = [aw['id'] for aw in armwrestlers]
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

    if is_htmx():
        return render_template('prediction_partial.html', **template_data)
    else:
        return render_template('prediction.html', **template_data)


@app.route("/elo_from_match")
def elo_from_match():

    ranked = request.args.get('ranked', 'ranked')
    arm = get_arm()
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
            armwrestlers_2 = [aw for aw in armwrestlers if aw['id'] != selected_armwrestler_1_id]

        if selected_armwrestler_1_id == selected_armwrestler_2_id:
            selected_armwrestler_2_id = None

    armwrestler_ids = [aw['id'] for aw in armwrestlers]
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
                if not (0 <= armwrestler_1_score <= max_rounds and 0 <= armwrestler_2_score <= max_rounds):
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
            armwrestler_1_diff, armwrestler_2_diff = elo_diff_from_match(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score), SUPERMATCH_FORMATS[selected_format][1])
            armwrestler_1_diff, armwrestler_1_color = (f"+{armwrestler_1_diff}", "text-success") if armwrestler_1_diff > 0 else ((str(armwrestler_1_diff),
                                                                                                                                  "text-danger") if armwrestler_1_diff < 0 else ("0", "text-secondary"))
            armwrestler_2_diff, armwrestler_2_color = (f"+{armwrestler_2_diff}", "text-success") if armwrestler_2_diff > 0 else ((str(armwrestler_2_diff),
                                                                                                                                  "text-danger") if armwrestler_2_diff < 0 else ("0", "text-secondary"))

        elif ranked == 'unranked':
            armwrestler_1_elo = get_current_elo(arm, [selected_armwrestler_1_id])[0]
            elo_from_match = expected_elo_from_score(armwrestler_1_elo, (armwrestler_2_score, armwrestler_1_score))

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

    if is_htmx():
        return render_template('elo_from_match_partial.html', **template_data)
    else:
        return render_template('elo_from_match.html', **template_data)


@app.errorhandler(404)
def page_not_found(e):
    app.logger.error(f"404 Error: {e}, path: {request.path}")
    return render_template('error.html', error_code="404", error_message=f"Page not found - {request.path}"), 404


@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"Server Error: {e}, path: {request.path}", exc_info=True)
    return render_template('error.html', error_code="500", error_message=f"Internal server error - {request.path}"), 500


@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled Exception: {e}, path: {request.path}", exc_info=True)
    return render_template('error.html', error_code="500", error_message=f"Unhandled exception - {request.path}"), 500


if __name__ == "__main__":
    app.run(host='0.0.0.0')
