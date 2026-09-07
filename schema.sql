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
    hidden INTEGER NOT NULL DEFAULT 0,
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
CREATE TABLE IF NOT EXISTS "badges" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS "armwrestler_badges" (
    armwrestler_id INTEGER NOT NULL,
    badge_id INTEGER NOT NULL,
    arm TEXT NOT NULL CHECK (arm IN ('right', 'left')),
    assigned_date DATE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by TEXT,
    PRIMARY KEY (armwrestler_id, badge_id, arm),
    FOREIGN KEY (armwrestler_id) REFERENCES armwrestlers(id) ON DELETE CASCADE,
    FOREIGN KEY (badge_id) REFERENCES badges(id) ON DELETE CASCADE
); 
INSERT INTO badges (name, color)
VALUES ('Provisional', 'text-bg-success');


CREATE TABLE IF NOT EXISTS "new_member" (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    new_member_name TEXT
);

INSERT INTO new_member (id, new_member_name) VALUES (1, NULL);

CREATE TABLE IF NOT EXISTS "new_member_matches" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    new_member_id INTEGER NOT NULL,
    armwrestler2_id INTEGER NOT NULL,
    arm TEXT NOT NULL CHECK (arm IN ('right', 'left')),
    armwrestler1_score INTEGER NOT NULL,
    armwrestler2_score INTEGER NOT NULL,
    selected_format TEXT NOT NULL,
    elo_from_match INTEGER NOT NULL,
    FOREIGN KEY (new_member_id) REFERENCES new_member (id),
    FOREIGN KEY (armwrestler2_id) REFERENCES armwrestlers(id)
);