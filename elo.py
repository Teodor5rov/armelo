import math
from scipy.stats import binom

CONTRAST = 400
K = 128


def expected_score(armwrestler_a_elo, armwrestler_b_elo, c=CONTRAST):
    expected_a = 1 / (1 + math.pow(10, ((armwrestler_b_elo - armwrestler_a_elo) / c)))
    expected_b = 1 - expected_a

    return expected_a, expected_b


def calculate_elo(armwrestler_a_elo, armwrestler_b_elo, actual_score, k=K):
    total_rounds = sum(actual_score)
    actual_a = actual_score[0] / total_rounds
    actual_b = actual_score[1] / total_rounds

    expected_a, expected_b = expected_score(armwrestler_a_elo, armwrestler_b_elo)

    updated_a_elo = round(armwrestler_a_elo + k * (actual_a - expected_a))
    updated_b_elo = round(armwrestler_b_elo + k * (actual_b - expected_b))

    return updated_a_elo, updated_b_elo


def expected_elo_from_score(armwrestler_b_elo, actual_score):
    total_rounds = sum(actual_score)
    actual_a = actual_score[0] / total_rounds
    if actual_a == 1 or actual_a == 0:
        return None
    else:
        armwrestler_a_elo = -CONTRAST * math.log10((1 - actual_a) / actual_a) + armwrestler_b_elo
        armwrestler_a_elo = round(armwrestler_a_elo)

    return armwrestler_a_elo


def add_bonus(armwrestler_a_elo, armwrestler_b_elo, actual_score):
    total_rounds = sum(actual_score)
    expected_a, expected_b = expected_score(armwrestler_a_elo, armwrestler_b_elo)
    armwrestler_a_score, armwrestler_b_score = actual_score[0], actual_score[1]
    actual_a = actual_score[0] / total_rounds
    actual_b = actual_score[1] / total_rounds

    armwrestler_a_score *= math.exp((actual_a / expected_a - 1) / 3) if actual_a > expected_a else 1
    armwrestler_b_score *= math.exp((actual_b / expected_b - 1) / 3) if actual_b > expected_b else 1

    with_bonus_score = (armwrestler_a_score, armwrestler_b_score)

    return with_bonus_score


def diff_supermatch(armwrestler_a_elo, armwrestler_b_elo, actual_score):
    with_bonus_score = add_bonus(armwrestler_a_elo, armwrestler_b_elo, actual_score)
    updated_a_elo, updated_b_elo = calculate_elo(armwrestler_a_elo, armwrestler_b_elo, with_bonus_score)

    diff_a_elo = updated_a_elo - armwrestler_a_elo
    diff_b_elo = updated_b_elo - armwrestler_b_elo

    return diff_a_elo, diff_b_elo


def calculate_elo_with_bonus(armwrestler_a_elo, armwrestler_b_elo, actual_score):
    with_bonus_score = add_bonus(armwrestler_a_elo, armwrestler_b_elo, actual_score)
    updated_a_elo, updated_b_elo = calculate_elo(armwrestler_a_elo, armwrestler_b_elo, with_bonus_score)

    return updated_a_elo, updated_b_elo


def expected_score_rounds(armwrestler_a_elo, armwrestler_b_elo, rounds=5):
    expected_a, expected_b = expected_score(armwrestler_a_elo, armwrestler_b_elo, CONTRAST)
    expected_a = round(expected_a * rounds) if expected_a != 0.5 else math.ceil(rounds / 2)
    expected_b = round(expected_b * rounds) if expected_b != 0.5 else math.ceil(rounds / 2)

    return expected_a, expected_b


def binom_prediction(armwrestler_a_elo, armwrestler_b_elo, rounds=5):
    expected_a, expected_b = expected_score(armwrestler_a_elo, armwrestler_b_elo, CONTRAST)
    win_rounds_needed = rounds // 2 + 1

    cumulative_prob_not_winning = binom.cdf(win_rounds_needed - 1, rounds, expected_a)
    
    predicted_a = 1 - cumulative_prob_not_winning
    predicted_b = 1 - predicted_a
    
    predicted_a = round(predicted_a * 100, 1)
    predicted_b = round(predicted_b * 100, 1)

    return predicted_a, predicted_b
