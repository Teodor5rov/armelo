K = 30


def expected_score(armwrestler_a_elo, armwrestler_b_elo):
    expected_a_elo = 1 / (1 + pow(10, ((armwrestler_b_elo - armwrestler_a_elo) / 400)))
    expected_b_elo = 1 - expected_a_elo

    return expected_a_elo, expected_b_elo


def calculate_elo(armwrestler_a_elo, armwrestler_b_elo, actual_score):
    total_rounds = sum(actual_score)

    actual_a_elo = actual_score[0] / total_rounds
    actual_b_elo = actual_score[1] / total_rounds

    expected_a_elo, expected_b_elo = expected_score(armwrestler_a_elo, armwrestler_b_elo)

    updated_a_elo = round(armwrestler_a_elo + K * (actual_a_elo - expected_a_elo))
    updated_b_elo = round(armwrestler_b_elo + K * (actual_b_elo - expected_b_elo))

    return updated_a_elo, updated_b_elo
