import csv
from itertools import permutations

with open('names.csv', 'r', newline='', encoding='utf-8') as csvfile:
    reader = csv.reader(csvfile)
    next(reader) 
    names = [' '.join(row) for row in reader]  

pairs = list(permutations(names, 2))

with open('output.csv', 'w', newline='', encoding='utf-8') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(['Armwrestler1', 'Armwrestler2', 'Score1', 'Score2'])
    for pair in pairs:
        writer.writerow([pair[0], pair[1], '', ''])

print(f'{len(pairs)} matches kurva.')
