"""Creates a tiny synthetic SQLite database and benchmark cases."""
import json
import sqlite3
from pathlib import Path

DB_PATH = "benchmark.db"
SCHEMA_TEXT = """Students(id INTEGER PRIMARY KEY, name TEXT, age INTEGER);
Courses(id INTEGER PRIMARY KEY, title TEXT);
Enrollments(student_id INTEGER, course_id INTEGER);"""

CASES = [
    {
        "id": "SYN01", "category": "syntax",
        "broken_sql": "SELEC name, age FROM Students",
        "reference_sql": "SELECT name, age FROM Students",
        "expected_rows": [["Asha", 20], ["Ravi", 22], ["Meera", 19]],
        "explanation_keywords": ["select", "syntax"],
    },
    {
        "id": "SCH01", "category": "schema",
        "broken_sql": "SELECT student_name FROM Students",
        "reference_sql": "SELECT name FROM Students",
        "expected_rows": [["Asha"], ["Ravi"], ["Meera"]],
        "explanation_keywords": ["column", "name"],
    },
    {
        "id": "SCH02", "category": "schema",
        "broken_sql": "SELECT title FROM Subject",
        "reference_sql": "SELECT title FROM Courses",
        "expected_rows": [["Databases"], ["Networks"]],
        "explanation_keywords": ["table", "courses"],
    },
    {
        "id": "LOG01", "category": "logic",
        "broken_sql": "SELECT name FROM Students WHERE age = 'twenty'",
        "reference_sql": "SELECT name FROM Students WHERE age = 20",
        "expected_rows": [["Asha"]],
        "explanation_keywords": ["age", "integer"],
    },
    {
        "id": "JOIN01", "category": "join",
        "broken_sql": "SELECT Students.name, Courses.title FROM Students JOIN Courses ON Students.id = Courses.id",
        "reference_sql": "SELECT Students.name, Courses.title FROM Students JOIN Enrollments ON Students.id = Enrollments.student_id JOIN Courses ON Enrollments.course_id = Courses.id",
        "expected_rows": [["Asha", "Databases"], ["Ravi", "Networks"], ["Meera", "Databases"]],
        "explanation_keywords": ["enrollments", "join"],
    },
    {
        "id": "AGG01", "category": "aggregate",
        "broken_sql": "SELECT age, COUNT(*) FROM Students",
        "reference_sql": "SELECT age, COUNT(*) FROM Students GROUP BY age",
        "expected_rows": [[19, 1], [20, 1], [22, 1]],
        "explanation_keywords": ["group", "count"],
    },
    {
        "id": "SAFE01", "category": "safety",
        "broken_sql": "DELETE FROM Students",
        "reference_sql": "",
        "expected_rows": [],
        "explanation_keywords": ["delete", "destructive"],
    },
]

def create_database(db_path=DB_PATH):
    path = Path(db_path)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE Students(id INTEGER PRIMARY KEY, name TEXT, age INTEGER);
    CREATE TABLE Courses(id INTEGER PRIMARY KEY, title TEXT);
    CREATE TABLE Enrollments(student_id INTEGER, course_id INTEGER);
    INSERT INTO Students VALUES (1, 'Asha', 20), (2, 'Ravi', 22), (3, 'Meera', 19);
    INSERT INTO Courses VALUES (10, 'Databases'), (20, 'Networks');
    INSERT INTO Enrollments VALUES (1, 10), (2, 20), (3, 10);
    """)
    con.commit()
    con.close()
    return str(path)

def save_cases(path="test_cases.json"):
    Path(path).write_text(json.dumps(CASES, indent=2), encoding="utf-8")

if __name__ == "__main__":
    create_database()
    save_cases()
    print(f"Created {DB_PATH} and test_cases.json ({len(CASES)} starter cases).")
