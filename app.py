from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from psycopg2 import pool
from werkzeug.security import generate_password_hash, check_password_hash
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

# Load .env file
print("Loaded environment: ", load_dotenv(".env", override=True))

# Get the connection string from the environment variable
connection_string = os.getenv('DATABASE_URL')

# Create a connection pool
connection_pool = pool.SimpleConnectionPool(1, 10, connection_string)

app = Flask(__name__)
CORS(app)
jwt = JWTManager(app)

app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')


def get_db_connection():
    return connection_pool.getconn()


def return_db_connection(conn):
    connection_pool.putconn(conn)



def is_nsfw(content) -> bool:
    # TODO: Not implemented
    return False


@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Check if username or email already exists
        cur.execute("SELECT * FROM users WHERE username = %s OR email = %s",
                    (data['username'], data['email']))
        if cur.fetchone():
            return jsonify({"error": "Username or email already exists"}), 400

        # Hash the password
        hashed_password = generate_password_hash(data['password'])

        # Insert new user
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (data['username'], data['email'], hashed_password, 'user'))

        new_user_id = cur.fetchone()['id']
        conn.commit()

        # Create access token
        access_token = create_access_token(identity=new_user_id)

        return jsonify({
            "message": "User registered successfully",
            "id": new_user_id,
            "access_token": access_token
        }), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Find user by username or email
        cur.execute("SELECT * FROM users WHERE username = %s OR email = %s",
                    (data.get('username', ''), data.get('email', '')))
        user = cur.fetchone()

        if user and check_password_hash(user['password_hash'], data['password']):
            access_token = create_access_token(identity=user['id'])
            return jsonify({
                "message": "Logged in successfully",
                "access_token": access_token,
                "user_id": user['id'],
                "username": user['username'],
                "role": user['role']
            })
        else:
            return jsonify({"error": "Invalid username/email or password"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)




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
        # Fetch skills along with the username and background
        cur.execute('''
            SELECT s.id, s.name, s.description, s.category, s.background, u.username
            FROM skills s
            JOIN users u ON s.user_id = u.id
            WHERE s.name ILIKE %s OR s.description ILIKE %s
            LIMIT %s
        ''', (f'%{query}%', f'%{query}%', limit))

        skills = cur.fetchall()

        # Map results to JSON format
        res = [{
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'category': row[3],
            'background': row[4],
            'username': row[5]  # Return the username of the person who submitted it
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

        # Add resources to each skill
        for skill in res:
            skill_id = skill['id']
            skill['resources'] = resources.get(skill_id, [])

        return jsonify({'skills': res})
    finally:
        cur.close()
        return_db_connection(conn)



@app.route('/api/career-advice/search', methods=['GET'])
def search_career_advice():
    query = request.args.get('q', '')
    limit = min(int(request.args.get('limit', 10)), 50)  # Set max limit to 50
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Fetch career advice along with the username and background
        cur.execute('''
            SELECT ca.id, ca.industry, ca.career_stage, ca.title, ca.content, ca.background, u.username
            FROM career_advice ca
            JOIN users u ON ca.user_id = u.id
            WHERE (ca.title ILIKE %s OR ca.industry ILIKE %s OR ca.career_stage ILIKE %s)
            AND ca.status = %s
            LIMIT %s
        ''', (f'%{query}%', f'%{query}%', f'%{query}%', 'published', limit))

        career_advice = cur.fetchall()

        return jsonify([{
            'id': row[0],
            'industry': row[1],
            'career_stage': row[2],
            'title': row[3],
            'content': row[4],
            'background': row[5],  # Return background field
            'username': row[6]  # Return the username of the person who submitted it
        } for row in career_advice])
    finally:
        cur.close()
        return_db_connection(conn)



@app.route('/api/propose-new-skill', methods=['POST'])
@jwt_required()
def propose_new_skill():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    user_id = get_jwt_identity()  # Capture user ID from JWT

    try:
        # Validate required fields
        required_fields = ['name', 'description', 'category', 'difficulty_level', 'background']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"error": f"'{field}' is required"}), 400

        # Insert new skill proposal with user_id and background
        cur.execute("""
            INSERT INTO proposed_skills
            (name, description, category, difficulty_level, proposer_id, background, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            RETURNING id
        """, (data['name'], data['description'], data['category'], data['difficulty_level'], user_id, data['background']))
        proposal_id = cur.fetchone()['id']

        # Handle resources
        if 'resources' in data:
            for resource in data['resources']:
                cur.execute("""
                    INSERT INTO proposed_skill_resources
                    (proposed_skill_id, title, description, type, url, is_paid)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (proposal_id, resource['title'], resource.get('description', ''), resource['type'], resource['url'], resource['is_paid']))

        # Handle tags
        if 'tags' in data:
            for tag in data['tags']:
                cur.execute("""
                    INSERT INTO proposed_skill_tags (proposed_skill_id, tag)
                    VALUES (%s, %s)
                """, (proposal_id, tag))

        conn.commit()
        return jsonify({"message": "New skill proposed successfully", "id": proposal_id}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)



@app.route('/api/propose-new-career-advice', methods=['POST'])
@jwt_required()
def propose_new_career_advice():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    user_id = get_jwt_identity()  # Capture user ID from JWT

    try:
        if any(is_nsfw(data[field]) for field in ['title', 'industry', 'career_stage', 'content'] if field in data):
            return jsonify({"error": "Proposed content contains inappropriate material"}), 400

        # Insert new career advice proposal with user_id and background
        cur.execute("""
            INSERT INTO proposed_career_advice
            (title, industry, career_stage, content, proposer_id, background, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            RETURNING id
        """, (data['title'], data['industry'], data['career_stage'], data['content'], user_id, data.get('background')))
        proposal_id = cur.fetchone()['id']

        # Handle tags
        if 'tags' in data:
            for tag in data['tags']:
                cur.execute("""
                    INSERT INTO proposed_career_advice_tags (proposed_career_advice_id, tag)
                    VALUES (%s, %s)
                """, (proposal_id, tag))

        conn.commit()
        return jsonify({"message": "New career advice proposed successfully", "id": proposal_id}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)


@app.route('/api/proposed-skills', methods=['GET'])
@jwt_required()
def get_proposed_skills():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT ps.*, 
                   array_agg(DISTINCT json_build_object('id', psr.id, 'title', psr.title, 'description', psr.description, 'type', psr.type, 'url', psr.url, 'is_paid', psr.is_paid)) as resources,
                   array_agg(DISTINCT pst.tag) as tags
            FROM proposed_skills ps
            LEFT JOIN proposed_skill_resources psr ON ps.id = psr.proposed_skill_id
            LEFT JOIN proposed_skill_tags pst ON ps.id = pst.proposed_skill_id
            WHERE ps.status NOT IN ('approved', 'rejected')
            GROUP BY ps.id
        """)
        proposed_skills = cur.fetchall()
        return jsonify(proposed_skills)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)

@app.route('/api/proposed-career-advice', methods=['GET'])
@jwt_required()
def get_proposed_career_advice():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT pca.*,
                   array_agg(DISTINCT pcat.tag) as tags
            FROM proposed_career_advice pca
            LEFT JOIN proposed_career_advice_tags pcat ON pca.id = pcat.proposed_career_advice_id
            WHERE pca.status NOT IN ('approved', 'rejected')
            GROUP BY pca.id
        """)
        proposed_career_advice = cur.fetchall()
        return jsonify(proposed_career_advice)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)

@app.route('/api/approve-skills-change/<int:skill_id>', methods=['POST'])
@jwt_required()
def approve_skills_change(skill_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Fetch the proposed skill
        cur.execute("SELECT * FROM proposed_skills WHERE id = %s", (skill_id,))
        proposed_skill = cur.fetchone()

        if not proposed_skill:
            return jsonify({"error": "Proposed skill not found"}), 404

        # Validate difficulty_level
        allowed_difficulty_levels = ['beginner', 'intermediate', 'advanced']  # Example allowed values
        if proposed_skill['difficulty_level'] not in allowed_difficulty_levels:
            return jsonify({"error": "Invalid difficulty level"}), 400

        # Insert the proposed skill into the skills table
        cur.execute("""
            INSERT INTO skills (name, description, category, difficulty_level)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (proposed_skill['name'], proposed_skill['description'], proposed_skill['category'], proposed_skill['difficulty_level']))
        new_skill_id = cur.fetchone()['id']

        # Fetch the proposed resources
        cur.execute("SELECT * FROM proposed_skill_resources WHERE proposed_skill_id = %s", (skill_id,))
        proposed_resources = cur.fetchall()

        # Insert the proposed resources into the resources table with a default status
        for resource in proposed_resources:
            cur.execute("""
                INSERT INTO resources (skill_id, title, description, type, url, is_paid, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (new_skill_id, resource['title'], resource['description'], resource['type'], resource['url'], resource['is_paid'], 'approved'))

        # Update the status of the proposed skill to 'approved'
        cur.execute("UPDATE proposed_skills SET status = %s WHERE id = %s", ('approved', skill_id))

        # Commit the transaction
        conn.commit()

        return jsonify({"message": "Skill approved successfully", "id": new_skill_id}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)


@app.route('/api/reject-skills-change/<int:skill_id>', methods=['POST'])
@jwt_required()
def reject_skills_change(skill_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Update the status of the proposed skill to 'rejected'
        cur.execute("UPDATE proposed_skills SET status = %s WHERE id = %s", ('rejected', skill_id))

        # Commit the transaction
        conn.commit()

        return jsonify({"message": "Skill rejected successfully"}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)

@app.route('/api/approve-career-advice-change/<int:advice_id>', methods=['POST'])
@jwt_required()
def approve_career_advice_change(advice_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Fetch the proposed career advice
        cur.execute("SELECT * FROM proposed_career_advice WHERE id = %s", (advice_id,))
        proposed_advice = cur.fetchone()

        if not proposed_advice:
            return jsonify({"error": "Proposed career advice not found"}), 404

        # Insert the proposed career advice into the career_advice table
        cur.execute("""
            INSERT INTO career_advice (title, industry, career_stage, content, status, user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (proposed_advice['title'], proposed_advice['industry'], proposed_advice['career_stage'], proposed_advice['content'], 'published', proposed_advice['proposer_id']))
        new_advice_id = cur.fetchone()['id']

        # Fetch the proposed tags
        cur.execute("SELECT tag FROM proposed_career_advice_tags WHERE proposed_career_advice_id = %s", (advice_id,))
        proposed_tags = cur.fetchall()

        # Insert the proposed tags into the career_advice_tags table
        for tag in proposed_tags:
            cur.execute("""
                INSERT INTO career_advice_tags (career_advice_id, tag)
                VALUES (%s, %s)
            """, (new_advice_id, tag['tag']))

        # Update the status of the proposed career advice to 'approved'
        cur.execute("UPDATE proposed_career_advice SET status = %s WHERE id = %s", ('approved', advice_id))

        # Commit the transaction
        conn.commit()

        return jsonify({"message": "Career advice approved successfully", "id": new_advice_id}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)


@app.route('/api/reject-career-advice-change/<int:advice_id>', methods=['POST'])
@jwt_required()
def reject_career_advice_change(advice_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Update the status of the proposed career advice to 'rejected'
        cur.execute("UPDATE proposed_career_advice SET status = %s WHERE id = %s", ('rejected', advice_id))

        # Commit the transaction
        conn.commit()

        return jsonify({"message": "Career advice rejected successfully"}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)

if __name__ == '__main__':
    app.run(debug=True)
