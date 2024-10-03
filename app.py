from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from psycopg2 import pool
from werkzeug.security import generate_password_hash, check_password_hash
from nsfw_detector import scan_text
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


def is_nsfw(content):
    return scan_text(content)


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


@app.route('/api/propose-change', methods=['POST'])
@jwt_required()
def propose_change():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        if is_nsfw(data['proposed_value']):
            return jsonify({"error": "Proposed content contains inappropriate material"}), 400

        is_new_entity = data.get('is_new_entity', False)
        entity_id = data['entity_id'] if not is_new_entity else None

        cur.execute("""
            INSERT INTO proposed_changes
            (entity_type, entity_id, field_name, current_value, proposed_value, proposer_id, is_new_entity)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (data['entity_type'], entity_id, data['field_name'],
              data.get('current_value'), data['proposed_value'], data['proposer_id'], is_new_entity))

        new_id = cur.fetchone()['id']
        conn.commit()

        return jsonify({"message": "Change proposed successfully", "id": new_id}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)


@app.route('/api/proposed-changes', methods=['GET'])
@jwt_required()
def get_proposed_changes():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    entity_type = request.args.get('entity_type')
    entity_id = request.args.get('entity_id')
    include_new = request.args.get('include_new', 'false').lower() == 'true'

    try:
        query = "SELECT * FROM proposed_changes WHERE 1=1"
        params = []

        if entity_type:
            query += " AND entity_type = %s"
            params.append(entity_type)

        if entity_id:
            query += " AND entity_id = %s"
            params.append(entity_id)
        elif include_new:
            query += " AND (entity_id IS NOT NULL OR is_new_entity = TRUE)"
        else:
            query += " AND entity_id IS NOT NULL"

        cur.execute(query, tuple(params))

        changes = cur.fetchall()
        return jsonify(changes)
    except Exception as e:
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

    try:
        if any(is_nsfw(data[field]) for field in ['title', 'industry', 'career_stage', 'content'] if field in data):
            return jsonify({"error": "Proposed content contains inappropriate material"}), 400

        # Insert the main career advice proposal
        cur.execute("""
            INSERT INTO proposed_changes
            (entity_type, field_name, proposed_value, proposer_id, is_new_entity)
            VALUES ('career_advice', 'title', %s, %s, TRUE)
            RETURNING id
        """, (data['title'], get_jwt_identity()))
        main_proposal_id = cur.fetchone()['id']

        # Insert additional fields as separate proposals
        additional_fields = ['industry', 'career_stage', 'content']
        for field in additional_fields:
            if field in data:
                cur.execute("""
                    INSERT INTO proposed_changes
                    (entity_type, field_name, proposed_value, proposer_id, is_new_entity)
                    VALUES ('career_advice', %s, %s, %s, TRUE)
                """, (field, data[field], get_jwt_identity()))

        # Handle tags
        if 'tags' in data:
            for tag in data['tags']:
                cur.execute("""
                    INSERT INTO proposed_changes
                    (entity_type, field_name, proposed_value, proposer_id, is_new_entity)
                    VALUES ('career_advice', 'tag', %s, %s, TRUE)
                """, (tag, get_jwt_identity()))

        conn.commit()
        return jsonify({"message": "New career advice proposed successfully", "id": main_proposal_id}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)


@app.route('/api/approve-change/<int:change_id>', methods=['POST'])
@jwt_required()
def approve_change(change_id):
    current_user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Check if the current user is an admin
        cur.execute("SELECT role FROM users WHERE id = %s", (current_user_id,))
        user_role = cur.fetchone()['role']

        if user_role != 'admin':
            return jsonify({"error": "Only admin users can approve changes"}), 403

        # Get the change details
        cur.execute("SELECT * FROM proposed_changes WHERE id = %s", (change_id,))
        change = cur.fetchone()

        if not change:
            return jsonify({"error": "Change not found"}), 404

        if change['is_new_entity']:
            # Handle new entity creation
            if change['entity_type'] == 'skill':
                cur.execute("""
                    INSERT INTO skills (name, description, category)
                    VALUES (%s, %s, %s)
                    RETURNING id
                """, (change['proposed_value'], '', ''))  # You might want to adjust this based on your needs
            elif change['entity_type'] == 'career_advice':
                cur.execute("""
                     INSERT INTO career_advice (title, industry, career_stage, content, author_id, status)
                     VALUES (%s, %s, %s, %s, %s, 'published')
                     RETURNING id
                 """, (change['proposed_value'], '', '', '', change['proposer_id']))
                new_career_advice_id = cur.fetchone()['id']

                # Fetch and apply all related changes
                cur.execute("""
                     SELECT * FROM proposed_changes
                     WHERE entity_type = 'career_advice' AND is_new_entity = TRUE AND status = 'pending'
                 """)
                related_changes = cur.fetchall()

                for related_change in related_changes:
                    if related_change['field_name'] == 'tag':
                        # Handle tags
                        cur.execute("INSERT INTO tags (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id",
                                    (related_change['proposed_value'],))
                        tag_id = cur.fetchone()['id']
                        cur.execute("INSERT INTO career_advice_tags (career_advice_id, tag_id) VALUES (%s, %s)",
                                    (new_career_advice_id, tag_id))
                    else:
                        # Update other fields
                        cur.execute(f"""
                             UPDATE career_advice
                             SET {related_change['field_name']} = %s
                             WHERE id = %s
                         """, (related_change['proposed_value'], new_career_advice_id))

                    # Mark related change as approved
                    cur.execute("UPDATE proposed_changes SET status = 'approved' WHERE id = %s",
                                (related_change['id'],))
            else:
                return jsonify({"error": "Invalid entity type"}), 400

            new_entity_id = cur.fetchone()['id']
        else:
            # Update the original entity
            if change['entity_type'] == 'skill':
                table = 'skills'
            elif change['entity_type'] == 'career_advice':
                table = 'career_advice'
            else:
                return jsonify({"error": "Invalid entity type"}), 400

            cur.execute(f"""
                UPDATE {table}
                SET {change['field_name']} = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (change['proposed_value'], change['entity_id']))

        # Update the change status
        cur.execute("""
            UPDATE proposed_changes
            SET status = 'approved', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (change_id,))

        conn.commit()
        return jsonify({"message": "Change approved and applied successfully",
                        "new_entity_id": new_entity_id if change['is_new_entity'] else None})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)


@app.route('/api/propose-new-skill', methods=['POST'])
@jwt_required()
def propose_new_skill():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        if any(is_nsfw(data[field]) for field in ['name', 'description', 'category', 'difficulty_level'] if
               field in data):
            return jsonify({"error": "Proposed content contains inappropriate material"}), 400

        # Insert the main skill proposal
        cur.execute("""
            INSERT INTO proposed_changes
            (entity_type, field_name, proposed_value, proposer_id, is_new_entity)
            VALUES ('skill', 'name', %s, %s, TRUE)
            RETURNING id
        """, (data['name'], get_jwt_identity()))
        main_proposal_id = cur.fetchone()['id']

        # Insert additional fields as separate proposals
        additional_fields = ['description', 'category', 'difficulty_level']
        for field in additional_fields:
            if field in data:
                cur.execute("""
                    INSERT INTO proposed_changes
                    (entity_type, field_name, proposed_value, proposer_id, is_new_entity)
                    VALUES ('skill', %s, %s, %s, TRUE)
                """, (field, data[field], get_jwt_identity()))

        # Handle tags
        if 'tags' in data:
            for tag in data['tags']:
                cur.execute("""
                    INSERT INTO proposed_changes
                    (entity_type, field_name, proposed_value, proposer_id, is_new_entity)
                    VALUES ('skill', 'tag', %s, %s, TRUE)
                """, (tag, get_jwt_identity()))

        # Handle resources
        if 'resources' in data:
            for resource in data['resources']:
                cur.execute("""
                    INSERT INTO proposed_changes
                    (entity_type, field_name, proposed_value, proposer_id, is_new_entity)
                    VALUES ('skill', 'resource', %s, %s, TRUE)
                """, (str(resource), get_jwt_identity()))

        conn.commit()
        return jsonify({"message": "New skill proposed successfully", "id": main_proposal_id}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)


@app.route('/api/reject-change/<int:change_id>', methods=['POST'])
@jwt_required()
def reject_change(change_id):
    current_user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Check if the current user is an admin
        cur.execute("SELECT role FROM users WHERE id = %s", (current_user_id,))
        user_role = cur.fetchone()['role']

        if user_role != 'admin':
            return jsonify({"error": "Only admin users can reject changes"}), 403

        # Get the change details
        cur.execute("SELECT * FROM proposed_changes WHERE id = %s", (change_id,))
        change = cur.fetchone()

        if not change:
            return jsonify({"error": "Change not found"}), 404

        # Update the change status to rejected
        cur.execute("""
            UPDATE proposed_changes
            SET status = 'rejected', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (change_id,))

        conn.commit()
        return jsonify({"message": "Change rejected successfully"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        return_db_connection(conn)


if __name__ == '__main__':
    app.run(debug=True)
