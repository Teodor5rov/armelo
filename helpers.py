from config import *
from elo import *


def is_htmx():
    return bool(request.headers.get('HX-Request')) and not request.headers.get('HX-History-Restore-Request')


def get_arm():
    arm = request.values.get('arm', 'right')
    return arm if arm in ('right', 'left') else 'right'


def submit_unconfirmed_supermatch(arm, armwrestler1_id, armwrestler2_id, armwrestler_1_score, armwrestler_2_score, selected_format):
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


def submit_new_member_match(arm, new_member_id, armwrestler2_id, armwrestler_1_score, armwrestler_2_score, selected_format):
    armwrestler_2_elo = get_current_elo(arm, [armwrestler2_id])[0]
    elo_from_match = expected_elo_from_score(armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score))

    query = '''
    INSERT INTO new_member_matches (
    new_member_id, armwrestler2_id,
    arm,
    selected_format,
    armwrestler1_score, armwrestler2_score,
    elo_from_match )
    VALUES (?, ?, ?, ?, ?, ?, ?)
    '''
    db_execute(query,
               new_member_id, armwrestler2_id,
               arm,
               selected_format,
               armwrestler_1_score, armwrestler_2_score,
               elo_from_match)


def submit_match(arm, armwrestler1_id, armwrestler2_id, armwrestler_1_score, armwrestler_2_score, armwrestler_1_elo, armwrestler_2_elo, selected_format, current_user):
    dbarm = 'right_elo' if arm == 'right' else 'left_elo'
    updated_1, updated_2 = calculate_elo_with_bonus(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score), SUPERMATCH_FORMATS[selected_format][1])

    rank_query = "SELECT rank FROM (SELECT RANK() OVER (ORDER BY {} DESC) AS rank, id FROM armwrestlers WHERE (active_until >= DATE('now') AND NOT hidden) OR id = ?) AS RankedArmwrestlers WHERE id = ?"
    armwrestler_1_rank = db_execute(rank_query.format(dbarm), armwrestler1_id, armwrestler1_id)[0]['rank']
    armwrestler_2_rank = db_execute(rank_query.format(dbarm), armwrestler2_id, armwrestler2_id)[0]['rank']

    armwrestler_1_diff, armwrestler_2_diff = elo_diff_from_match(armwrestler_1_elo, armwrestler_2_elo, (armwrestler_1_score, armwrestler_2_score), SUPERMATCH_FORMATS[selected_format][1])

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

    update_badges()
    update_ranks()


def get_current_elo(arm, armwrestler_ids):
    if arm not in ['right', 'left']:
        raise ValueError("Invalid arm. Must be 'right' or 'left'.")

    dbarm = 'right_elo' if arm == 'right' else 'left_elo'
    return [db_execute('SELECT {} FROM armwrestlers WHERE id = ?'.format(dbarm), id)[0][dbarm] for id in armwrestler_ids]


def get_matches_formatted_data(matches):
    formatted_data = []
    for match in matches:
        score1, score2 = match['armwrestler1_score'], match['armwrestler2_score']
        diff1, diff2 = match['armwrestler1_elo_diff'], match['armwrestler2_elo_diff']
        score1_color, score2_color = ('bg-success', 'bg-danger') if score1 > score2 else (
            ('bg-danger', 'bg-success') if score1 < score2 else ('bg-secondary', 'bg-secondary'))
        diff1_text, diff1_color = (f"+{diff1}", 'text-success') if diff1 > 0 else (
            (str(diff1), 'text-danger') if diff1 < 0 else ('0', 'text-secondary'))
        diff2_text, diff2_color = (f"+{diff2}", 'text-success') if diff2 > 0 else (
            (str(diff2), 'text-danger') if diff2 < 0 else ('0', 'text-secondary'))
        formatted_data.append({
            'score1_color': score1_color, 'score2_color': score2_color,
            'diff1_color': diff1_color, 'diff2_color': diff2_color,
            'diff1_text': diff1_text, 'diff2_text': diff2_text,
            'date': datetime.strptime(match['date'], '%Y-%m-%d %H:%M:%S').strftime('%d %B %Y')
        })

    return formatted_data


def update_ranks():
    query_update_ranks = '''
    WITH
        ranked_right AS (
            SELECT id, RANK() OVER (ORDER BY right_elo DESC) AS new_right_rank
            FROM armwrestlers
            WHERE active_until >= DATE('now') AND NOT hidden
        ),
        ranked_left AS (
            SELECT id, RANK() OVER (ORDER BY left_elo DESC) AS new_left_rank
            FROM armwrestlers
            WHERE active_until >= DATE('now') AND NOT hidden
        )
    UPDATE armwrestlers
    SET
        right_rank = (SELECT new_right_rank FROM ranked_right WHERE ranked_right.id = armwrestlers.id),
        left_rank = (SELECT new_left_rank FROM ranked_left WHERE ranked_left.id = armwrestlers.id)
    WHERE active_until >= DATE('now') AND NOT hidden;
    '''

    query_nullify_ranks = '''
    UPDATE armwrestlers SET right_rank = NULL, left_rank = NULL
    WHERE active_until < DATE('now') OR hidden;
    '''

    db_execute(query_update_ranks)
    db_execute(query_nullify_ranks)


def update_badges():
    result = db_execute("SELECT id FROM badges WHERE name = 'Provisional';")
    if not result:
        return

    provisional_badge_id = result[0]['id']

    db_execute('DELETE FROM armwrestler_badges WHERE badge_id = ?;', provisional_badge_id)

    db_execute('''
        INSERT INTO armwrestler_badges (armwrestler_id, badge_id, arm)
        SELECT id, ?, 'right'
        FROM armwrestlers
        WHERE id NOT IN (
            SELECT armwrestler1_id FROM history WHERE arm='right'
            UNION
            SELECT armwrestler2_id FROM history WHERE arm='right'
        );
    ''', provisional_badge_id)

    db_execute('''
        INSERT INTO armwrestler_badges (armwrestler_id, badge_id, arm)
        SELECT id, ?, 'left'
        FROM armwrestlers
        WHERE id NOT IN (
            SELECT armwrestler1_id FROM history WHERE arm='left'
            UNION
            SELECT armwrestler2_id FROM history WHERE arm='left'
        );
    ''', provisional_badge_id)


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
