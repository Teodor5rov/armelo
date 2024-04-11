def expected_score(armwrestler_a_elo, armwrestler_b_elo):
    expected_a_elo = 1 / (1 + pow(10, ((armwrestler_b_elo - armwrestler_a_elo) / 500)))
    expected_b_elo = 1 - expected_a_elo

    return expected_a_elo, expected_b_elo


def calculate_elo(armwrestler_a_elo, armwrestler_b_elo, actual_score, k = 100):
    total_rounds = sum(actual_score)
    actual_a_elo = actual_score[0] / total_rounds
    actual_b_elo = actual_score[1] / total_rounds
    
    expected_a_elo, expected_b_elo = expected_score(armwrestler_a_elo, armwrestler_b_elo)

    updated_a_elo = round(armwrestler_a_elo + k * (actual_a_elo - expected_a_elo))
    updated_b_elo = round(armwrestler_b_elo + k * (actual_b_elo - expected_b_elo))

    return updated_a_elo, updated_b_elo


def add_bonus(actual_score):
    armwrestler_a_score, armwrestler_b_score = actual_score[0], actual_score[1]
    armwrestler_a_score += 1 if armwrestler_a_score > armwrestler_b_score else 0
    armwrestler_b_score += 1 if armwrestler_b_score > armwrestler_a_score else 0
    with_bonus_score = (armwrestler_a_score, armwrestler_b_score)

    return with_bonus_score


def diff_supermatch(armwrestler_a_elo, armwrestler_b_elo, actual_score):
    with_bonus_score = add_bonus(actual_score)
    updated_a_elo, updated_b_elo = calculate_elo(armwrestler_a_elo, armwrestler_b_elo, with_bonus_score)

    diff_a = updated_a_elo - armwrestler_a_elo
    diff_b = updated_b_elo - armwrestler_b_elo

    return diff_a, diff_b


def calculate_elo_with_bonus(armwrestler_a_elo, armwrestler_b_elo, actual_score):
    with_bonus_score = add_bonus(actual_score)
    updated_a_elo, updated_b_elo = calculate_elo(armwrestler_a_elo, armwrestler_b_elo, with_bonus_score)

    return updated_a_elo, updated_b_elo