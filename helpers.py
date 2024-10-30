from config import *
from elo import *


def submit_unconfirmed_supermatch(arm, armwrestler1_id, armwrestler2_id, armwrestler_1_score, armwrestler_2_score, selected_format):
    try:
        query = '''
        INSERT INTO unconfirmed_matches ( 
        armwrestler1_id, armwrestler2_id, 
        arm, 
        selected_format,
        armwrestler1_score, armwrestler2_score ) 
        VALUES (?, ?, ?, ?, ?, ?)
        '''
        db_execute(query,
                   armwrestler1_id, armwrestler2_id,
                   arm,
                   selected_format,
                   armwrestler_1_score, armwrestler_2_score)

    except sqlite3.DatabaseError as error:
        app.logger.error(f"Database error occurred: {error}", exc_info=True)
        app.logger.error(f"Operation context: {request.path} - {request.method}")


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
        update_ranks()
    except sqlite3.DatabaseError as error:
        app.logger.error(f"Database error occurred: {error}", exc_info=True)
        app.logger.error(f"Operation context: {request.path} - {request.method}")


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


def get_matches_formatted_data(matches):
    formatted_data = []
    for match in matches:
        armwrestler_1_diff_format, armwrestler_2_diff_format = match[11], match[12]
        armwrestler_1_score_color, armwrestler_2_score_color = match[9], match[10]

        armwrestler_1_diff_format, armwrestler_1_diff_color = (f"+{armwrestler_1_diff_format}", "text-success") if armwrestler_1_diff_format > 0 else (
            (str(armwrestler_1_diff_format), "text-danger") if armwrestler_1_diff_format < 0 else ("0", "text-secondary"))
        armwrestler_2_diff_format, armwrestler_2_diff_color = (f"+{armwrestler_2_diff_format}", "text-success") if armwrestler_2_diff_format > 0 else (
            (str(armwrestler_2_diff_format), "text-danger") if armwrestler_2_diff_format < 0 else ("0", "text-secondary"))
        armwrestler_1_score_color, armwrestler_2_score_color = ("bg-success", "bg-danger") if armwrestler_1_score_color > armwrestler_2_score_color else (
            ("bg-danger", "bg-success") if armwrestler_1_score_color < armwrestler_2_score_color else ("bg-secondary", "bg-secondary"))

        date = datetime.strptime(match[14], "%Y-%m-%d %H:%M:%S").strftime("%d %B %Y")

        formatted_data.append((armwrestler_1_score_color, armwrestler_2_score_color, armwrestler_1_diff_color, armwrestler_2_diff_color, armwrestler_1_diff_format, armwrestler_2_diff_format, date))

    return formatted_data


def update_ranks():
    query_update_ranks = '''
    WITH
        ranked_right AS (
            SELECT id, DENSE_RANK() OVER (ORDER BY right_elo DESC) AS right_rank
            FROM armwrestlers
            WHERE active_until >= DATE('now')
        ),
        ranked_left AS (
            SELECT id, DENSE_RANK() OVER (ORDER BY left_elo DESC) AS left_rank
            FROM armwrestlers
            WHERE active_until >= DATE('now')
        )
    UPDATE armwrestlers
    SET
        right_rank = (SELECT right_rank FROM ranked_right WHERE ranked_right.id = armwrestlers.id),
        left_rank = (SELECT left_rank FROM ranked_left WHERE ranked_left.id = armwrestlers.id);
    '''

    query_nullify_ranks = '''
    UPDATE armwrestlers SET right_rank = NULL, left_rank = NULL
    WHERE active_until < DATE('now');
    '''

    db_execute(query_update_ranks)
    db_execute(query_nullify_ranks)


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