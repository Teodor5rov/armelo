CREATE TABLE sqlite_sequence(name,seq);
CREATE TABLE users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS "armwrestlers" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    right_elo INTEGER NOT NULL,
    left_elo INTEGER NOT NULL,
    right_rank INTEGER,
    left_rank INTEGER,
    added_by TEXT NOT NULL,
    active_until DATE NOT NULL,
    last_edited_by TEXT,
    FOREIGN KEY (added_by) REFERENCES users(username)
);
CREATE TABLE IF NOT EXISTS "history" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    armwrestler1_id INTEGER NOT NULL,
    armwrestler2_id INTEGER NOT NULL,
    arm TEXT NOT NULL CHECK (arm IN ('right', 'left')),
    armwrestler1_rank INTEGER NOT NULL,
    armwrestler2_rank INTEGER NOT NULL,
    armwrestler1_elo INTEGER NOT NULL,
    armwrestler2_elo INTEGER NOT NULL,
    armwrestler1_score INTEGER NOT NULL,
    armwrestler2_score INTEGER NOT NULL,
    armwrestler1_elo_diff INTEGER NOT NULL,
    armwrestler2_elo_diff INTEGER NOT NULL,
    selected_format TEXT NOT NULL,
    date DATETIME DEFAULT CURRENT_TIMESTAMP,
    added_by TEXT NOT NULL,
    FOREIGN KEY (armwrestler1_id) REFERENCES armwrestlers(id),
    FOREIGN KEY (armwrestler2_id) REFERENCES armwrestlers(id),
    FOREIGN KEY (added_by) REFERENCES users(username)
);
CREATE TABLE IF NOT EXISTS "unconfirmed_matches" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    armwrestler1_id INTEGER NOT NULL,
    armwrestler2_id INTEGER NOT NULL,
    arm TEXT NOT NULL CHECK (arm IN ('right', 'left')),
    armwrestler1_score INTEGER NOT NULL,
    armwrestler2_score INTEGER NOT NULL,
    selected_format TEXT NOT NULL,
    date DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (armwrestler1_id) REFERENCES armwrestlers(id),
    FOREIGN KEY (armwrestler2_id) REFERENCES armwrestlers(id)
);