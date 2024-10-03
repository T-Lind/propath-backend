from flask import Flask, jsonify, request
from psycopg2 import pool
from dotenv import load_dotenv
from flask_cors import CORS
import os

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
    cur.execute('SELECT id, industry, career_stage, title, content FROM career_advice WHERE status = %s',
                ('published',))
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


@app.route('/api/skills/search', methods=['GET'])
def search_skills():
    query = request.args.get('q', '')
    limit = min(int(request.args.get('limit', 10)), 50)  # Set max limit to 50
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Search query for skills by name or description
        cur.execute('''
            SELECT id, name, description, category
            FROM skills
            WHERE name ILIKE %s OR description ILIKE %s
            LIMIT %s
        ''', (f'%{query}%', f'%{query}%', limit))

        skills = cur.fetchall()

        # Map results to JSON format
        res = [{
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'category': row[3]
        } for row in skills]

        # Fetch resources for each skill
        skill_ids = [row[0] for row in skills]
        resources = {}
        if skill_ids:
            cur.execute('''
                SELECT skill_id, id, title, description, type, url, is_paid
                FROM resources
                WHERE skill_id = ANY(%s) AND status = %s
            ''', (skill_ids, 'approved'))
            resources_data = cur.fetchall()

            # Organize resources by skill_id
            for resource in resources_data:
                skill_id = resource[0]
                if skill_id not in resources:
                    resources[skill_id] = []
                resources[skill_id].append({
                    'id': resource[1],
                    'title': resource[2],
                    'description': resource[3],
                    'type': resource[4],
                    'url': resource[5],
                    'is_paid': resource[6],
                })

        return jsonify({'skills': res, 'resources': resources})
    finally:
        cur.close()
        return_db_connection(conn)


# Add Search Endpoint for Career Advice
@app.route('/api/career-advice/search', methods=['GET'])
def search_career_advice():
    query = request.args.get('q', '')
    limit = min(int(request.args.get('limit', 10)), 50)  # Set max limit to 50
    conn = get_db_connection()
    cur = conn.cursor()

    # Search query for career advice by title, industry, or career stage
    cur.execute('''
        SELECT id, industry, career_stage, title, content
        FROM career_advice
        WHERE (title ILIKE %s OR industry ILIKE %s OR career_stage ILIKE %s)
        AND status = %s
        LIMIT %s
    ''', (f'%{query}%', f'%{query}%', f'%{query}%', 'published', limit))

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


if __name__ == '__main__':
    app.run(debug=True)
