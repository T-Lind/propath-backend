import os
from flask import Flask, jsonify
from psycopg2 import pool
from dotenv import load_dotenv
from flask_cors import CORS

# Load .env file
print("Loaded environment: ", load_dotenv(".env", override=True))

# Get the connection string from the environment variable
connection_string = os.getenv('DATABASE_URL')

# Create a connection pool
connection_pool = pool.SimpleConnectionPool(1, 10, connection_string)

app = Flask(__name__)
CORS(app)

def get_db_connection():
    return connection_pool.getconn()

def return_db_connection(conn):
    connection_pool.putconn(conn)

@app.route('/api/career-advice', methods=['GET'])
def get_career_advice():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, industry, career_stage, title, content FROM career_advice WHERE status = %s', ('published',))
    career_advice = cur.fetchall()
    cur.close()
    return_db_connection(conn)

    return jsonify([{
        'id': row[0],
        'industry': row[1],
        'career_stage': row[2],
        'title': row[3],
        'content': row[4]
    } for row in career_advice])

@app.route('/api/skills', methods=['GET'])
def get_skills():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, name, description, category FROM skills')
    skills = cur.fetchall()
    cur.close()
    return_db_connection(conn)
    res = [{
        'id': row[0],
        'name': row[1],
        'description': row[2],
        'category': row[3]
    } for row in skills]

    return jsonify(res)

@app.route('/api/skills/<int:skill_id>/resources', methods=['GET'])
def get_skill_resources(skill_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT id, title, description, type, url, is_paid 
        FROM resources 
        WHERE skill_id = %s AND status = %s
    ''', (skill_id, 'approved'))
    resources = cur.fetchall()
    cur.close()
    return_db_connection(conn)

    return jsonify([{
        'id': row[0],
        'title': row[1],
        'description': row[2],
        'type': row[3],
        'url': row[4],
        'is_paid': row[5]
    } for row in resources])

# @app.teardown_appcontext
# def close_db_connection_pool(exception):
#     if connection_pool:
#         connection_pool.closeall()

if __name__ == '__main__':
    app.run(debug=True)