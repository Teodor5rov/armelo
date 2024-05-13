import math
from scipy.stats import beta

CONTRAST = 400
K = 100


def expected_score(armwrestler_a_elo, armwrestler_b_elo, c=CONTRAST):
    expected_a_elo = 1 / (1 + math.pow(10, ((armwrestler_b_elo - armwrestler_a_elo) / c)))
    expected_b_elo = 1 - expected_a_elo

    return expected_a_elo, expected_b_elo


def calculate_elo(armwrestler_a_elo, armwrestler_b_elo, actual_score, k=K):
    total_rounds = sum(actual_score)
    actual_a_elo = actual_score[0] / total_rounds
    actual_b_elo = actual_score[1] / total_rounds

    expected_a_elo, expected_b_elo = expected_score(armwrestler_a_elo, armwrestler_b_elo)

    updated_a_elo = round(armwrestler_a_elo + k * (actual_a_elo - expected_a_elo))
    updated_b_elo = round(armwrestler_b_elo + k * (actual_b_elo - expected_b_elo))

    return updated_a_elo, updated_b_elo


def expected_elo_from_score(armwrestler_b_elo, actual_score):
    total_rounds = sum(actual_score)
    actual_a_elo = actual_score[0] / total_rounds
    if actual_a_elo == 1 or actual_a_elo == 0:
        return None
    else:
        armwrestler_a_elo = -CONTRAST * math.log10((1 - actual_a_elo) / actual_a_elo) + armwrestler_b_elo
        armwrestler_a_elo = round(armwrestler_a_elo)

    return armwrestler_a_elo


def add_bonus(armwrestler_a_elo, armwrestler_b_elo, actual_score):
    total_rounds = sum(actual_score)
    expected_a_elo, expected_b_elo = expected_score(armwrestler_a_elo, armwrestler_b_elo)
    armwrestler_a_score, armwrestler_b_score = actual_score[0], actual_score[1]
    actual_a_elo = actual_score[0] / total_rounds
    actual_b_elo = actual_score[1] / total_rounds

    armwrestler_a_score *= math.exp((actual_a_elo / expected_a_elo - 1) / 2) if actual_a_elo > expected_a_elo else 1
    armwrestler_b_score *= math.exp((actual_b_elo / expected_b_elo - 1) / 2) if actual_b_elo > expected_b_elo else 1

    with_bonus_score = (armwrestler_a_score, armwrestler_b_score)

    return with_bonus_score


def diff_supermatch(armwrestler_a_elo, armwrestler_b_elo, actual_score):
    with_bonus_score = add_bonus(armwrestler_a_elo, armwrestler_b_elo, actual_score)
    updated_a_elo, updated_b_elo = calculate_elo(armwrestler_a_elo, armwrestler_b_elo, with_bonus_score)

    diff_a = updated_a_elo - armwrestler_a_elo
    diff_b = updated_b_elo - armwrestler_b_elo

    return diff_a, diff_b


def calculate_elo_with_bonus(armwrestler_a_elo, armwrestler_b_elo, actual_score):
    with_bonus_score = add_bonus(armwrestler_a_elo, armwrestler_b_elo, actual_score)
    updated_a_elo, updated_b_elo = calculate_elo(armwrestler_a_elo, armwrestler_b_elo, with_bonus_score)

    return updated_a_elo, updated_b_elo


def expected_score_hundered(armwrestler_a_elo, armwrestler_b_elo):
    expected_a, expected_b = expected_score(armwrestler_a_elo, armwrestler_b_elo, CONTRAST)
    expected_a = round(expected_a * 100, 1)
    expected_b = round(expected_b * 100, 1)

    return expected_a, expected_b


def expected_score_five(armwrestler_a_elo, armwrestler_b_elo):
    expected_a, expected_b = expected_score(armwrestler_a_elo, armwrestler_b_elo, CONTRAST)
    expected_five_a = round(expected_a * 5) if expected_a != 0.5 else 3
    expected_five_b = round(expected_b * 5) if expected_b != 0.5 else 3

    return expected_five_a, expected_five_b


def beta_prediction(armwrestler_a_elo, armwrestler_b_elo, confidence=5):
    expected_a, expected_b = expected_score(armwrestler_a_elo, armwrestler_b_elo, CONTRAST)
    alpha1 = confidence * expected_a
    beta1 = confidence - alpha1

    predicted_b = beta.cdf(0.5, alpha1, beta1)
    predicted_a = 1 - predicted_b

    predicted_a = round(predicted_a * 100, 1)
    predicted_b = round(predicted_b * 100, 1)

    return predicted_a, predicted_b
