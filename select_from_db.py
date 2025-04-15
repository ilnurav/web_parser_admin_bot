import sqlite3

conn = sqlite3.connect('sites.db')
cursor = conn.cursor()

cursor.execute("SELECT * FROM sites")

print(cursor.fetchall())