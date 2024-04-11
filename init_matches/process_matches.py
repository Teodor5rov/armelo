import csv
import sqlite3
import random
import sys
import os
from collections import defaultdict

parent_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(parent_dir))

from elo import calculate_elo

DATABASE = '../database.db'
db_connection = None  

def get_db():
    global db_connection
    if db_connection is None:
        db_connection = sqlite3.connect(DATABASE)
    return db_connection

def db_execute(query, *args, commit=False):
    db = get_db()
    cur = db.cursor()
    cur.execute(query, args)
    if query.strip().upper().startswith("SELECT"):
        rv = cur.fetchall()
        cur.close()
        return rv
    else:
        if commit:
            db.commit()
        cur.close()

def read_csv(file_path):
    """Read matches from the CSV file."""
    matches = []
    with open(file_path, mode='r', encoding='utf-8') as file:
        csv_reader = csv.reader(file)
        next(csv_reader) 
        for row in csv_reader:
            matches.append(row)
    return matches

def process_matches(matches):

    match_dict = defaultdict(list)
    for match in matches:
        armwrestler1, armwrestler2, score1, score2 = match
        key = tuple(sorted([armwrestler1, armwrestler2]))
        match_dict[key].append((armwrestler1, armwrestler2, score1, score2))

    processed_matches = []
    for key, records in match_dict.items():
        
        if all(record[2].isdigit() and record[3].isdigit() for record in records):
            total_score1, total_score2 = 0, 0
            for record in records:
                armwrestler1, armwrestler2, score1, score2 = record
                if armwrestler1 == key[0]:
                    total_score1 += float(score1)
                    total_score2 += float(score2)
                    check_consensus1 = float(score1)
                else:
                    total_score1 += float(score2)
                    total_score2 += float(score1)
                    check_consensus2 = float(score2)
            avg_score1 = total_score1 / 2
            avg_score2 = total_score2 / 2

            if abs(check_consensus1 - check_consensus2) > 1:
                print(records, "DIFF:", abs(check_consensus1 - check_consensus2))

            processed_matches.append([key[0], key[1], f"{avg_score1:.1f}", f"{avg_score2:.1f}"])
        else:
            for record in records:
                armwrestler1, armwrestler2, score1, score2 = record
                if score1.isdigit() and score2.isdigit():
                    processed_matches.append([armwrestler1, armwrestler2, float(score1), float(score2)])

    return processed_matches

def write_csv(file_path, matches):
    """Write processed matches to a new CSV file."""
    with open(file_path, mode='w', encoding='utf-8', newline='') as file:
        csv_writer = csv.writer(file)
        csv_writer.writerow(["Armwrestler1", "Armwrestler2", "Score1", "Score2"])
        csv_writer.writerows(matches)

def supermatch(armwrestler_1, armwrestler_2, armwrestler_1_score, armwrestler_2_score, k, arm='right'):

    dbarm = 'right_elo' if arm == 'right' else 'left_elo'
    try:
        db_execute("BEGIN;")
        
        armwrestler_1_elo = db_execute(f'SELECT {dbarm} FROM armwrestlers WHERE name = ?', armwrestler_1)[0][0]
        armwrestler_2_elo = db_execute(f'SELECT {dbarm} FROM armwrestlers WHERE name = ?', armwrestler_2)[0][0]

        updated_1, updated_2 = calculate_elo(armwrestler_1_elo, armwrestler_2_elo, (float(armwrestler_1_score), float(armwrestler_2_score)), k)

        db_execute(f"UPDATE armwrestlers SET {dbarm} = ? WHERE name = ?", updated_1, armwrestler_1)
        db_execute(f"UPDATE armwrestlers SET {dbarm} = ? WHERE name = ?", updated_2, armwrestler_2)

        db_execute("COMMIT;", commit=True)
    except sqlite3.DatabaseError as error:
        print(error)
        db_execute("ROLLBACK;", commit=True) 

def close_db():
    global db_connection
    if db_connection is not None:
        db_connection.close()
        db_connection = None

if __name__ == '__main__':
    try:
        input_file_path = 'input_matches_main.csv'
        matches = read_csv(input_file_path)
        processed_matches = process_matches(matches)
        # write_csv('output_matches_main.csv', processed_matches)

        k = 64
        for i in range(256):
            print(k)
            if (i + 1) % 4 == 0:
                k -= 1
            random.shuffle(processed_matches)
            for match in processed_matches:
                supermatch(match[0], match[1], match[2], match[3], k)
    finally:
        close_db() 