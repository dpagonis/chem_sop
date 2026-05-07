from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, send_file
import bcrypt
from .database import db, init_db
from .sop_utils import (generate_sop_id, create_sop_directory, 
                       get_sop_directory, save_sop_file, save_approved_version,
                       load_approved_procedure, format_diff_html, move_sop_directory,
                       parse_markdown_sections, build_markdown_from_sections, 
                       STANDARD_SOP_SECTIONS, sanitize_filename)
import os
from datetime import datetime
import io
import re

try:
    from chemical_safety.chemical import chemical
    CHEMICAL_SAFETY_AVAILABLE = True
except ImportError:
    CHEMICAL_SAFETY_AVAILABLE = False
    print("Warning: chemical_safety package not installed. Chemical lookup features will be disabled.")

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production-make-it-random'

# Initialize database
init_db()

def needs_setup():
    """Check if initial setup is required (no admin exists)"""
    cursor = db.execute('SELECT COUNT(*) FROM users WHERE role = ?', ('admin',))
    admin_count = cursor.fetchone()[0]
    return admin_count == 0

@app.before_request
def check_setup():
    """Redirect to setup if no admin exists, except for setup routes"""
    if needs_setup() and request.endpoint not in ('setup', 'create_admin', 'static'):
        return redirect(url_for('setup'))

def check_approval_permission(approver_role, requested_role):
    """Check if approver can approve requested role"""
    permissions = {
        'admin': ['admin', 'faculty', 'faculty_reviewer', 'lab_manager', 'general'],
        'faculty': ['faculty', 'general'],
        'faculty_reviewer': ['faculty_reviewer', 'faculty', 'general'],
        'lab_manager': ['lab_manager', 'faculty', 'faculty_reviewer', 'general']
    }
    return requested_role in permissions.get(approver_role, [])

def parse_reagent_list(reagent_text):
    """
    Parse reagent list text and extract first-level list items (chemical names)
    with their second-level details.
    Returns a list of dicts: [{'name': 'Chemical Name', 'details': ['detail1', 'detail2']}, ...]
    """
    if not reagent_text:
        return []
    
    reagents = []
    lines = reagent_text.split('\n')
    current_reagent = None
    
    for line in lines:
        # Match first-level list items (no leading whitespace before marker)
        first_level_match = re.match(r'^[-*+]\s+(.+)$', line)
        if first_level_match:
            # Save previous reagent if exists
            if current_reagent:
                reagents.append(current_reagent)
            # Start new reagent
            chem_name = first_level_match.group(1).strip()
            # Remove common patterns like amounts, concentrations from name
            chem_name = re.sub(r'\([^)]*\)$', '', chem_name).strip()
            chem_name = re.sub(r',\s*\d+.*$', '', chem_name).strip()
            if chem_name:
                current_reagent = {'name': chem_name, 'details': []}
        else:
            # Match second-level list items (leading whitespace before marker)
            second_level_match = re.match(r'^\s+[-*+]\s+(.+)$', line)
            if second_level_match and current_reagent:
                detail = second_level_match.group(1).strip()
                current_reagent['details'].append(detail)
    
    # Don't forget the last reagent
    if current_reagent:
        reagents.append(current_reagent)
    
    return reagents

def lookup_chemicals(reagents):
    """
    Perform chemical lookup for a list of reagent dicts.
    Each reagent dict has 'name' and 'details' keys.
    Returns a list of chemical objects with added 'details' attribute.
    """
    if not CHEMICAL_SAFETY_AVAILABLE or not reagents:
        return []
    
    chemicals = []
    for reagent in reagents:
        try:
            c = chemical(reagent['name'], spell_check=True)
            c.details = reagent['details']  # Add details to chemical object
            chemicals.append(c)
        except Exception as e:
            print(f"Error looking up chemical '{reagent['name']}': {e}")
            # Create a placeholder object for failed lookups
            class ErrorChemical:
                def __init__(self, name, details, error):
                    self.name = name
                    self.details = details
                    self.error = str(error)
                    self.is_error = True
            chemicals.append(ErrorChemical(reagent['name'], reagent['details'], e))
    
    return chemicals

# --- SETUP WIZARD ---
@app.route('/setup', methods=['GET'])
def setup():
    """Initial setup page - create first admin user"""
    # If admin already exists, redirect to homepage
    if not needs_setup():
        return redirect(url_for('index'))
    
    return render_template('setup.html')

@app.route('/setup/create-admin', methods=['POST'])
def create_admin():
    """Create the first admin user"""
    # Double check that no admin exists
    if not needs_setup():
        flash('Admin user already exists', 'error')
        return redirect(url_for('index'))
    
    name = request.form.get('name')
    pin = request.form.get('pin')
    confirm_pin = request.form.get('confirm_pin')
    
    # Validation
    if not name or not pin or not confirm_pin:
        flash('All fields are required', 'error')
        return redirect(url_for('setup'))
    
    if pin != confirm_pin:
        flash('PINs do not match', 'error')
        return redirect(url_for('setup'))
    
    if len(pin) < 6:
        flash('PIN must be at least 6 characters long', 'error')
        return redirect(url_for('setup'))
    
    if len(set(pin)) < 3:
        flash('PIN must contain at least 3 different characters', 'error')
        return redirect(url_for('setup'))
    
    # Create admin user
    pin_hash = bcrypt.hashpw(pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    try:
        db.execute(
            'INSERT INTO users (name, pin_hash, role) VALUES (?, ?, ?)',
            (name, pin_hash, 'admin')
        )
        db.commit()
        
        flash(f'Admin account created successfully! Welcome, {name}', 'success')
        return redirect(url_for('index'))
    except Exception as e:
        flash(f'Error creating admin account: {str(e)}', 'error')
        return redirect(url_for('setup'))

# --- HOMEPAGE ---
@app.route('/')
def index():
    cursor = db.execute('SELECT * FROM pending_approvals ORDER BY created_at ASC')
    pending_approvals = cursor.fetchall()
    return render_template('index.html', pending_approvals=pending_approvals)

# --- USER MANAGEMENT ---
@app.route('/manage-users', methods=['GET'])
def manage_users():
    # Get all users
    cursor = db.execute('SELECT id, name, role, created_at FROM users ORDER BY role ASC, name ASC')
    users = cursor.fetchall()
    
    # Get pending approvals
    cursor = db.execute('SELECT * FROM pending_approvals ORDER BY created_at DESC')
    pending_approvals = cursor.fetchall()
    
    # Get approval log
    cursor = db.execute('SELECT * FROM approval_log ORDER BY approval_timestamp DESC')
    approval_log = cursor.fetchall()
    
    return render_template('manage_users.html', 
                           users=users, 
                           pending_approvals=pending_approvals,
                           approval_log=approval_log)

@app.route('/request-user', methods=['POST'])
def request_user():
    name = request.form.get('name')
    pin = request.form.get('pin')
    role = request.form.get('role')
    
    if not name or not pin or not role:
        flash('Name, PIN, and role are required', 'error')
        return redirect(url_for('manage_users'))
    
    # Validate PIN
    if len(pin) < 6:
        flash('PIN must be at least 6 characters long', 'error')
        return redirect(url_for('manage_users'))
    
    if len(set(pin)) < 3:
        flash('PIN must contain at least 3 different characters', 'error')
        return redirect(url_for('manage_users'))
    
    # Hash the PIN
    pin_hash = bcrypt.hashpw(pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    # Insert into pending approvals
    cursor = db.execute(
        'INSERT INTO pending_approvals (name, pin_hash, requested_role) VALUES (?, ?, ?)',
        (name, pin_hash, role)
    )
    db.commit()
    
    flash('Request submitted for approval', 'success')
    return redirect(url_for('manage_users'))

@app.route('/approve-request/<int:id>', methods=['GET', 'POST'])
def approve_request(id):
    # Get pending request
    cursor = db.execute('SELECT * FROM pending_approvals WHERE id = ?', (id,))
    request_data = cursor.fetchone()
    
    if not request_data:
        flash('Request not found', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'GET':
        # Show approval form
        cursor = db.execute('SELECT * FROM pending_approvals')
        all_pending = cursor.fetchall()
        return render_template('approve_request.html', 
                               pending_request=request_data,
                               all_pending=all_pending)
    
    # POST - process approval
    approver_pin = request.form.get('approverPin')
    
    if not approver_pin:
        flash('Approver PIN is required', 'error')
        return redirect(url_for('approve_request', id=id))
    
    # Verify approver PIN
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()
    
    approver = None
    for user in users:
        user_id, name, pin_hash, role = user[0], user[1], user[2], user[3]
        if bcrypt.checkpw(approver_pin.encode('utf-8'), pin_hash.encode('utf-8')):
            approver = {'id': user_id, 'name': name, 'role': role}
            break
    
    if not approver:
        flash('Invalid approver PIN', 'error')
        return redirect(url_for('approve_request', id=id))
    
    req_id, req_name, req_pin_hash, req_role, req_created = request_data
    
    # Check permissions
    if not check_approval_permission(approver['role'], req_role):
        flash(f"{approver['role']} cannot approve {req_role} requests", 'error')
        return redirect(url_for('approve_request', id=id))
    
    # Create user
    cursor = db.execute(
        'INSERT INTO users (name, pin_hash, role, approved_by) VALUES (?, ?, ?, ?)',
        (req_name, req_pin_hash, req_role, approver['id'])
    )
    db.commit()
    
    # Log approval
    db.execute(
        'INSERT INTO approval_log (user_name, requested_role, approved_by_name, approved_by_role) VALUES (?, ?, ?, ?)',
        (req_name, req_role, approver['name'], approver['role'])
    )
    db.commit()
    
    # Delete pending request
    db.execute('DELETE FROM pending_approvals WHERE id = ?', (id,))
    db.commit()
    
    flash(f'User {req_name} approved successfully', 'success')
    return redirect(url_for('index'))

@app.route('/reject-request/<int:id>', methods=['POST'])
def reject_request(id):
    # Get pending request
    cursor = db.execute('SELECT * FROM pending_approvals WHERE id = ?', (id,))
    request_data = cursor.fetchone()
    
    if not request_data:
        flash('Request not found', 'error')
        return redirect(url_for('index'))
    
    # POST - process rejection
    approver_pin = request.form.get('approverPin')
    
    if not approver_pin:
        flash('Approver PIN is required', 'error')
        return redirect(url_for('approve_request', id=id))
    
    # Verify approver PIN
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()
    
    approver = None
    for user in users:
        user_id, name, pin_hash, role = user[0], user[1], user[2], user[3]
        if bcrypt.checkpw(approver_pin.encode('utf-8'), pin_hash.encode('utf-8')):
            approver = {'id': user_id, 'name': name, 'role': role}
            break
    
    if not approver:
        flash('Invalid approver PIN', 'error')
        return redirect(url_for('approve_request', id=id))
    
    req_id, req_name, req_pin_hash, req_role, req_created = request_data
    
    # Check permissions (same as approval)
    if not check_approval_permission(approver['role'], req_role):
        flash(f"{approver['role']} cannot reject {req_role} requests", 'error')
        return redirect(url_for('approve_request', id=id))
    
    # Log rejection to approval_log with "REJECTED" marker
    db.execute(
        'INSERT INTO approval_log (user_name, requested_role, approved_by_name, approved_by_role) VALUES (?, ?, ?, ?)',
        (req_name, f'REJECTED {req_role}', approver['name'], approver['role'])
    )
    db.commit()
    
    # Delete pending request
    db.execute('DELETE FROM pending_approvals WHERE id = ?', (id,))
    db.commit()
    
    flash(f'User request for {req_name} rejected', 'success')
    return redirect(url_for('index'))

@app.route('/change-user-role', methods=['POST'])
def change_user_role():
    """Change a user's role with lab manager or admin PIN verification"""
    data = request.get_json()
    target_user_id = data.get('user_id')
    new_role = data.get('new_role')
    pin = data.get('pin')

    valid_roles = ['admin', 'faculty', 'faculty_reviewer', 'lab_manager', 'general']
    if not target_user_id or not new_role or not pin:
        return jsonify({'success': False, 'error': 'Missing required fields'})
    if new_role not in valid_roles:
        return jsonify({'success': False, 'error': 'Invalid role'})

    # Verify PIN belongs to lab_manager or admin
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()

    approver = None
    for user in users:
        if bcrypt.checkpw(pin.encode('utf-8'), user[2].encode('utf-8')):
            if user[3] in ['lab_manager', 'admin']:
                approver = {'id': user[0], 'name': user[1], 'role': user[3]}
            break

    if not approver:
        return jsonify({'success': False, 'error': 'Invalid PIN or insufficient permissions. Only lab managers and admins can change user roles.'})

    # Get target user
    cursor = db.execute('SELECT id, name, role FROM users WHERE id = ?', (target_user_id,))
    target_user = cursor.fetchone()
    if not target_user:
        return jsonify({'success': False, 'error': 'User not found'})

    old_role = target_user[2]
    if old_role == new_role:
        return jsonify({'success': False, 'error': 'User already has that role'})

    # Update role
    db.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, target_user_id))
    db.commit()

    # Log to approval_log
    db.execute(
        'INSERT INTO approval_log (user_name, requested_role, approved_by_name, approved_by_role) VALUES (?, ?, ?, ?)',
        (target_user[1], f'role changed: {old_role} -> {new_role}', approver['name'], approver['role'])
    )
    db.commit()

    return jsonify({'success': True, 'message': f"Role changed to {new_role}"})

# --- SOPs ---
@app.route('/sops')
def sops():
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change, faculty_approved
        FROM sops ORDER BY status, course, title
    ''')
    all_sops = cursor.fetchall()
    
    # Organize by status
    drafts = [sop for sop in all_sops if sop[7] == 'draft']
    pending = [sop for sop in all_sops if sop[7] == 'submitted']
    approved = [sop for sop in all_sops if sop[7] == 'approved']
    
    # Organize approved by course
    courses = {}
    for sop in approved:
        course = sop[3]
        if course not in courses:
            courses[course] = []
        courses[course].append(sop)
    
    return render_template('sops.html', drafts=drafts, pending=pending, courses=courses)

@app.route('/courses')
def get_courses():
    """Helper endpoint to get list of courses for dropdown"""
    cursor = db.execute('SELECT DISTINCT course FROM sops WHERE status = "approved" AND course IS NOT NULL ORDER BY course')
    courses = [row[0] for row in cursor.fetchall()]
    return {'courses': courses}

@app.route('/verify-owner-pin', methods=['POST'])
def verify_owner_pin():
    """Verify that the provided PIN matches the SOP owner's PIN"""
    data = request.get_json()
    sop_id = data.get('sop_id')
    pin = data.get('pin')
    
    if not sop_id or not pin:
        return jsonify({'success': False, 'error': 'Missing sop_id or pin'})
    
    # Get SOP owner
    cursor = db.execute('SELECT owner_id FROM sops WHERE sop_id = ?', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        return jsonify({'success': False, 'error': 'SOP not found'})
    
    owner_id = sop[0]
    
    # Get owner's PIN hash
    cursor = db.execute('SELECT pin_hash FROM users WHERE id = ?', (owner_id,))
    user = cursor.fetchone()
    
    if not user:
        return jsonify({'success': False, 'error': 'Owner not found'})
    
    # Verify PIN
    if bcrypt.checkpw(pin.encode('utf-8'), user[0].encode('utf-8')):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Invalid PIN'})

@app.route('/submit-sop', methods=['POST'])
def submit_sop():
    """Submit SOP for approval with PIN verification"""
    data = request.get_json()
    sop_id = data.get('sop_id')
    pin = data.get('pin')
    title = data.get('title')
    course = data.get('course')
    owner_id = data.get('ownerId')
    procedure = data.get('procedure')
    version_type = data.get('versionType')
    faculty_reviewer_id = data.get('facultyReviewerId')
    
    if not sop_id or not pin:
        return jsonify({'success': False, 'error': 'Missing sop_id or pin'})
    
    if not version_type:
        return jsonify({'success': False, 'error': 'Please select whether this is a major or minor change'})
    
    # Get SOP data
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        return jsonify({'success': False, 'error': 'SOP not found'})
    
    sop_owner_id = sop[4]
    old_course = sop[3]
    old_status = sop[7]
    current_major = sop[8]
    current_minor = sop[9]
    
    if old_status != 'draft':
        return jsonify({'success': False, 'error': 'Only draft SOPs can be submitted'})
    
    # Verify owner PIN
    cursor = db.execute('SELECT * FROM users WHERE id = ?', (sop_owner_id,))
    owner = cursor.fetchone()
    
    if not owner or not bcrypt.checkpw(pin.encode('utf-8'), owner[2].encode('utf-8')):
        return jsonify({'success': False, 'error': 'Invalid PIN'})
    
    # Save changes first (DO NOT increment version - only on approval)
    is_major_change = 1 if version_type == 'major' else 0
    
    # Set next reviewer based on whether it's a major change
    next_reviewer_id = None
    next_reviewer_name = None
    faculty_approved = 0
    # Major changes go to any faculty_reviewer or admin for first-stage review;
    # no specific reviewer is designated.
    
    # Update SOP with new data, submitted status, and routing info (version unchanged)
    db.execute(
        '''UPDATE sops 
           SET title = ?, course = ?, owner_id = ?, 
               owner_name = (SELECT name FROM users WHERE id = ?),
               procedure = ?, updated_at = CURRENT_TIMESTAMP,
               is_major_change = ?,
               status = 'submitted', submitted_at = CURRENT_TIMESTAMP,
               next_reviewer_id = ?, next_reviewer_name = ?, faculty_approved = ?
           WHERE sop_id = ?''',
        (title, course, owner_id, owner_id, procedure, is_major_change, 
         next_reviewer_id, next_reviewer_name, faculty_approved, sop_id)
    )
    db.commit()
    
    # Save procedure to file
    save_sop_file(sop_id, 'submitted', course, procedure)
    
    # Move to submitted folder
    if old_course != course or old_status != 'submitted':
        move_sop_directory(sop_id, old_status, 'submitted', old_course, course)
    
    # Log action
    routing_msg = f'Submitted for approval (next: {next_reviewer_name})' if next_reviewer_name else 'Submitted for approval'
    db.execute(
        '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (sop_id, 'submitted', owner[0], owner[1], owner[3], routing_msg, current_major, current_minor)
    )
    db.commit()
    
    return jsonify({'success': True, 'message': 'SOP submitted for approval'})

@app.route('/delete-sop', methods=['POST'])
def delete_sop():
    """Delete SOP with PIN verification (owner or admin only)"""
    data = request.get_json()
    sop_id = data.get('sop_id')
    pin = data.get('pin')
    
    if not sop_id or not pin:
        return jsonify({'success': False, 'error': 'Missing sop_id or pin'})
    
    # Get SOP data
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        return jsonify({'success': False, 'error': 'SOP not found'})
    
    sop_owner_id = sop[4]
    sop_course = sop[3]
    sop_status = sop[7]
    
    # Verify PIN and check if user is owner or admin
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()
    
    authorized_user = None
    for user in users:
        user_id, name, pin_hash, role = user[0], user[1], user[2], user[3]
        if bcrypt.checkpw(pin.encode('utf-8'), pin_hash.encode('utf-8')):
            # User must be either the owner or an admin
            if user_id == sop_owner_id or role == 'admin':
                authorized_user = {'id': user_id, 'name': name, 'role': role}
            break
    
    if not authorized_user:
        return jsonify({'success': False, 'error': 'Invalid PIN or insufficient permissions. Only owner or admin can delete.'})
    
    # Delete SOP directory
    import shutil
    sop_dir = get_sop_directory(sop_id, sop_status, sop_course)
    if os.path.exists(sop_dir):
        shutil.rmtree(sop_dir)
    
    # Delete from database
    db.execute('DELETE FROM sops WHERE sop_id = ?', (sop_id,))
    db.execute('DELETE FROM sop_log WHERE sop_id = ?', (sop_id,))
    db.execute('DELETE FROM sop_comments WHERE sop_id = ?', (sop_id,))
    db.commit()
    
    return jsonify({'success': True, 'message': 'SOP deleted successfully'})

@app.route('/delete-sop-form/<sop_id>', methods=['POST'])
def delete_sop_form(sop_id):
    """Delete SOP with PIN verification via form submission"""
    pin = request.form.get('pin')
    
    if not pin:
        flash('PIN is required to delete SOP', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Get SOP data
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change,
               approved_by_id, approved_by_name
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        flash('SOP not found', 'error')
        return redirect(url_for('sops'))
    
    sop_owner_id = sop[4]
    sop_course = sop[3]
    sop_status = sop[7]
    
    # Verify PIN and check if user is owner or admin
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()
    
    authorized_user = None
    for user in users:
        user_id, name, pin_hash, role = user[0], user[1], user[2], user[3]
        if bcrypt.checkpw(pin.encode('utf-8'), pin_hash.encode('utf-8')):
            # User must be either the owner or an admin
            if user_id == sop_owner_id or role == 'admin':
                authorized_user = {'id': user_id, 'name': name, 'role': role}
            break
    
    if not authorized_user:
        flash('Invalid PIN or insufficient permissions. Only owner or admin can delete.', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Delete SOP directory
    import shutil
    sop_dir = get_sop_directory(sop_id, sop_status, sop_course)
    if os.path.exists(sop_dir):
        shutil.rmtree(sop_dir)
    
    # Delete from database
    db.execute('DELETE FROM sops WHERE sop_id = ?', (sop_id,))
    db.execute('DELETE FROM sop_log WHERE sop_id = ?', (sop_id,))
    db.execute('DELETE FROM sop_comments WHERE sop_id = ?', (sop_id,))
    db.commit()
    
    flash('SOP deleted successfully', 'success')
    return redirect(url_for('sops'))

@app.route('/discard-draft-sop', methods=['POST'])
def discard_draft_sop():
    """Discard draft SOP (already PIN verified to access edit page)"""
    data = request.get_json()
    sop_id = data.get('sop_id')
    
    if not sop_id:
        return jsonify({'success': False, 'error': 'Missing sop_id'})
    
    # Get SOP data
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        return jsonify({'success': False, 'error': 'SOP not found'})
    
    # Only drafts can be discarded
    if sop[7] != 'draft':
        return jsonify({'success': False, 'error': 'Only draft SOPs can be discarded'})
    
    sop_owner_id = sop[4]
    sop_owner_name = sop[5]
    sop_course = sop[3]
    sop_status = sop[7]
    
    # Delete SOP directory
    import shutil
    sop_dir = get_sop_directory(sop_id, sop_status, sop_course)
    if os.path.exists(sop_dir):
        shutil.rmtree(sop_dir)
    
    # Delete from database
    db.execute('DELETE FROM sops WHERE sop_id = ?', (sop_id,))
    db.execute('DELETE FROM sop_log WHERE sop_id = ?', (sop_id,))
    db.execute('DELETE FROM sop_comments WHERE sop_id = ?', (sop_id,))
    db.commit()
    
    return jsonify({'success': True, 'message': 'Draft SOP discarded successfully'})

@app.route('/transfer-sop-ownership', methods=['POST'])
def transfer_sop_ownership():
    """Transfer SOP ownership with PIN verification (current owner only)"""
    try:
        data = request.get_json()
        sop_id = data.get('sop_id')
        new_owner_id = data.get('new_owner_id')
        pin = data.get('pin')
        
        print(f"Transfer request: sop_id={sop_id}, new_owner_id={new_owner_id}")
        
        if not sop_id or not new_owner_id or not pin:
            return jsonify({'success': False, 'error': 'Missing required parameters'})
    
        # Get SOP data
        cursor = db.execute('''
            SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
                   version_major, version_minor, approved_procedure, approved_version_major,
                   approved_version_minor, created_by_id, created_by_name, created_at,
                   updated_at, submitted_at, approved_at, comments, is_major_change
            FROM sops WHERE sop_id = ?
        ''', (sop_id,))
        sop = cursor.fetchone()
        
        if not sop:
            return jsonify({'success': False, 'error': 'SOP not found'})
        
        # Only drafts can have ownership transferred
        if sop[7] != 'draft':
            return jsonify({'success': False, 'error': 'Only draft SOPs can have ownership transferred'})
        
        current_owner_id = sop[4]
        current_owner_name = sop[5]
        
        # Verify PIN belongs to current owner
        cursor = db.execute('SELECT id, name, role, pin_hash FROM users WHERE id = ?', (current_owner_id,))
        current_owner = cursor.fetchone()
        
        if not current_owner:
            return jsonify({'success': False, 'error': 'Current owner not found'})
        
        if not bcrypt.checkpw(pin.encode('utf-8'), current_owner[3].encode('utf-8')):
            return jsonify({'success': False, 'error': 'Invalid PIN. Only the current owner can transfer ownership.'})
        cursor = db.execute('SELECT id, name, role FROM users WHERE id = ?', (new_owner_id,))
        new_owner = cursor.fetchone()
        
        if not new_owner:
            return jsonify({'success': False, 'error': 'New owner not found'})
        
        # Check if there's an approved SOP with the same title and course
        # If yes, this draft was created from an approved SOP, so we should update the approved one
        cursor = db.execute('''
            SELECT sop_id, version_major, version_minor FROM sops 
            WHERE title = ? AND course = ? AND status = 'approved'
        ''', (sop[2], sop[3]))
        approved_sop = cursor.fetchone()
        
        if approved_sop:
            # This is a draft from an approved SOP
            # Update the approved SOP's owner and discard this draft
            approved_sop_id = approved_sop[0]
            approved_version_major = approved_sop[1]
            approved_version_minor = approved_sop[2]
            
            # Update approved SOP ownership
            db.execute(
                '''UPDATE sops 
                   SET owner_id = ?,
                       owner_name = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE sop_id = ?''',
                (new_owner[0], new_owner[1], approved_sop_id)
            )
            
            # Log ownership transfer for approved SOP
            db.execute(
                '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (approved_sop_id, 'ownership_transferred', current_owner[0], current_owner[1], current_owner[2], 
                 f'Ownership transferred from {current_owner[1]} to {new_owner[1]}', approved_version_major, approved_version_minor)
            )
            
            # Delete the draft SOP directory
            import shutil
            draft_dir = get_sop_directory(sop_id, 'draft', sop[3])
            if os.path.exists(draft_dir):
                shutil.rmtree(draft_dir)
            
            # Delete draft from database
            db.execute('DELETE FROM sops WHERE sop_id = ?', (sop_id,))
            db.execute('DELETE FROM sop_log WHERE sop_id = ?', (sop_id,))
            db.execute('DELETE FROM sop_comments WHERE sop_id = ?', (sop_id,))
            db.commit()
            
            return jsonify({'success': True, 'message': f'Ownership transferred to {new_owner[1]} and draft discarded'})
        
        else:
            # This is a brand new draft (no approved version exists)
            # Just update the draft's owner
            db.execute(
                '''UPDATE sops 
                   SET owner_id = ?,
                       owner_name = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE sop_id = ?''',
                (new_owner[0], new_owner[1], sop_id)
            )
            
            # Log ownership transfer
            db.execute(
                '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (sop_id, 'ownership_transferred', current_owner[0], current_owner[1], current_owner[2], 
                 f'Ownership transferred from {current_owner[1]} to {new_owner[1]}', sop[8], sop[9])
            )
            
            db.commit()
            
            return jsonify({'success': True, 'message': f'Ownership transferred to {new_owner[1]}'})
    
    except Exception as e:
        print(f"Error in transfer_sop_ownership: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Transfer failed: {str(e)}'})
@app.route('/approve-sop', methods=['POST'])
def approve_sop_api():
    """Approve SOP with PIN verification - handles two-step approval for major changes"""
    data = request.get_json()
    sop_id = data.get('sop_id')
    pin = data.get('pin')
    comment = data.get('comment', '')
    
    if not sop_id or not pin:
        return jsonify({'success': False, 'error': 'Missing sop_id or pin'})
    
    # Get SOP data including new approval fields
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change,
               next_reviewer_id, next_reviewer_name, faculty_approved,
               last_reviewed_at, last_reviewed_by_id, last_reviewed_by_name,
               last_reviewed_version_major, last_reviewed_version_minor
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        return jsonify({'success': False, 'error': 'SOP not found'})
    
    if sop[7] != 'submitted':
        return jsonify({'success': False, 'error': 'Only submitted SOPs can be approved'})
    
# Verify approver PIN — accept any recognized role then check stage permissions below
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()

    approver = None
    for user in users:
        if bcrypt.checkpw(pin.encode('utf-8'), user[2].encode('utf-8')):
            if user[3] in ['faculty_reviewer', 'lab_manager', 'admin']:
                approver = {'id': user[0], 'name': user[1], 'role': user[3]}
            break

    if not approver:
        return jsonify({'success': False, 'error': 'Invalid PIN or insufficient permissions. Only faculty reviewers, lab managers, and admins can approve SOPs.'})

    is_major_change = sop[20] or 0
    faculty_approved = sop[23] or 0

    # Route by stage:
    #   Stage 1 (faculty review): major change, faculty_approved=0
    #     → only faculty_reviewer or admin may act
    #   Stage 2 (final approval): minor change, OR major+faculty_approved=1
    #     → only lab_manager or admin may act
    needs_faculty_review = (is_major_change and faculty_approved == 0)

    if needs_faculty_review:
        if approver['role'] not in ['faculty_reviewer', 'admin']:
            return jsonify({'success': False, 'error': 'This SOP requires faculty review first. Only Faculty Reviewers and Admins can approve at this stage.'})
    else:
        if approver['role'] not in ['lab_manager', 'admin']:
            return jsonify({'success': False, 'error': 'This SOP is awaiting final lab manager approval. Only Lab Managers and Admins can approve at this stage.'})

    is_faculty_approval_step = needs_faculty_review
    
    if is_faculty_approval_step:
        # FACULTY APPROVAL: Mark faculty approval, record review metadata, and route to lab manager
        current_major = sop[8]
        current_minor = sop[9]
        
        # Calculate the version this will become after approval (major change: increment major, reset minor)
        new_major = current_major + 1
        new_minor = 0
        
        db.execute(
            '''UPDATE sops 
               SET faculty_approved = 1,
                   next_reviewer_id = NULL,
                   next_reviewer_name = NULL,
                   updated_at = CURRENT_TIMESTAMP,
                   last_reviewed_at = CURRENT_TIMESTAMP,
                   last_reviewed_by_id = ?,
                   last_reviewed_by_name = ?,
                   last_reviewed_version_major = ?,
                   last_reviewed_version_minor = ?
               WHERE sop_id = ?''',
            (approver['id'], approver['name'], new_major, new_minor, sop_id)
        )
        db.commit()
        
        # Log faculty approval with the new version number
        db.execute(
            '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (sop_id, 'faculty_approved', approver['id'], approver['name'], approver['role'], 
             f'Faculty review and approval by {approver["name"]} - routing to lab manager', new_major, new_minor)
        )
        db.commit()
        
        return jsonify({'success': True, 'message': 'Faculty approval complete. SOP now awaits lab manager approval.'})
    
    else:
        # FINAL APPROVAL: Increment version and mark as approved
        current_major = sop[8]
        current_minor = sop[9]
        
        if is_major_change:
            new_major = current_major + 1
            new_minor = 0
        else:
            new_major = current_major
            new_minor = current_minor + 1
        
        # Check if there's an existing approved version with same title/course (different SOP ID)
        cursor = db.execute('''
            SELECT sop_id, last_reviewed_at, last_reviewed_by_id, last_reviewed_by_name,
                   last_reviewed_version_major, last_reviewed_version_minor
            FROM sops 
            WHERE title = ? AND course = ? AND status = 'approved' AND sop_id != ?
        ''', (sop[2], sop[3], sop_id))
        old_approved = cursor.fetchone()
        
        # For minor changes, preserve review metadata from previous approved version
        # For major changes, use the review metadata just recorded during faculty approval
        if is_major_change:
            # Use faculty review data from this submission (already in sop fields)
            review_at = sop[24]
            review_by_id = sop[25]
            review_by_name = sop[26]
            review_major = sop[27]
            review_minor = sop[28]
        elif old_approved and old_approved[1]:
            # Preserve review metadata from previous approved version
            review_at = old_approved[1]
            review_by_id = old_approved[2]
            review_by_name = old_approved[3]
            review_major = old_approved[4]
            review_minor = old_approved[5]
        else:
            # No previous review data
            review_at = None
            review_by_id = None
            review_by_name = None
            review_major = None
            review_minor = None
        
        # Delete old approved version if it exists
        if old_approved:
            import shutil
            old_sop_id = old_approved[0]
            old_sop_dir = get_sop_directory(old_sop_id, 'approved', sop[3])
            if os.path.exists(old_sop_dir):
                shutil.rmtree(old_sop_dir)
            db.execute('DELETE FROM sops WHERE sop_id = ?', (old_sop_id,))
            db.execute('DELETE FROM sop_log WHERE sop_id = ?', (old_sop_id,))
            db.execute('DELETE FROM sop_comments WHERE sop_id = ?', (old_sop_id,))
            db.commit()
        
        # Approve with incremented version and CLEAR comments, store approver, clear routing fields, preserve review metadata
        db.execute(
            '''UPDATE sops 
               SET status = 'approved', approved_at = CURRENT_TIMESTAMP,
                   approved_procedure = procedure,
                   approved_version_major = ?,
                   approved_version_minor = ?,
                   version_major = ?,
                   version_minor = ?,
                   comments = NULL,
                   approved_by_id = ?,
                   approved_by_name = ?,
                   next_reviewer_id = NULL,
                   next_reviewer_name = NULL,
                   faculty_approved = 0,
                   last_reviewed_at = ?,
                   last_reviewed_by_id = ?,
                   last_reviewed_by_name = ?,
                   last_reviewed_version_major = ?,
                   last_reviewed_version_minor = ?
               WHERE sop_id = ?''',
            (new_major, new_minor, new_major, new_minor, approver['id'], approver['name'],
             review_at, review_by_id, review_by_name, review_major, review_minor, sop_id)
        )
        db.commit()
        
        # Clear comments from database on approval
        db.execute('DELETE FROM sop_comments WHERE sop_id = ?', (sop_id,))
        db.commit()
        
        # Move to approved folder first
        move_sop_directory(sop_id, 'submitted', 'approved', sop[3], sop[3])
        
        # Then save approved version (now that it's in the right place)
        save_approved_version(sop_id, sop[3], sop[6])
        
        # Log action with new version
        db.execute(
            '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (sop_id, 'approved', approver['id'], approver['name'], approver['role'], 
             f'Approved by {approver["name"]} - v{new_major}.{new_minor}', new_major, new_minor)
        )
        db.commit()
        
        return jsonify({'success': True, 'message': f'SOP approved successfully as v{new_major}.{new_minor}'})

@app.route('/send-back-sop', methods=['POST'])
def send_back_sop_api():
    """Send back SOP with PIN verification"""
    data = request.get_json()
    sop_id = data.get('sop_id')
    pin = data.get('pin')
    comment = data.get('comment', '')
    
    if not sop_id or not pin:
        return jsonify({'success': False, 'error': 'Missing sop_id or pin'})
    
    if not comment:
        return jsonify({'success': False, 'error': 'Comment is required when sending back'})
    
    # Get SOP data
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change,
               approved_by_id, approved_by_name, faculty_approved, next_reviewer_id, next_reviewer_name
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        return jsonify({'success': False, 'error': 'SOP not found'})
    
    if sop[7] != 'submitted':
        return jsonify({'success': False, 'error': 'Only submitted SOPs can be sent back'})
    
    # Extract relevant fields
    is_major_change = sop[20] or 0
    faculty_approved = sop[23] or 0
    next_reviewer_id = sop[24]
    
    # Verify approver PIN and role
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()
    
    approver = None
    matched_user = None
    
    # First, find the user with matching PIN
    for user in users:
        if bcrypt.checkpw(pin.encode('utf-8'), user[2].encode('utf-8')):
            matched_user = user
            break
    
    if not matched_user:
        return jsonify({'success': False, 'error': 'Invalid PIN'})
    
    # Check if user has permission to send back
    user_role = matched_user[3]
    user_id = matched_user[0]
    
    if user_role in ['lab_manager', 'admin']:
        # Lab managers/admins can send back at the final stage; admin can also send back at faculty stage
        if is_major_change and faculty_approved == 0 and user_role == 'lab_manager':
            return jsonify({'success': False, 'error': 'This SOP is still in faculty review. Only Faculty Reviewers or Admins can send it back at this stage.'})
        approver = {'id': matched_user[0], 'name': matched_user[1], 'role': matched_user[3]}
    elif user_role == 'faculty_reviewer':
        # Any faculty_reviewer can send back a major change that is still awaiting faculty review
        if is_major_change and faculty_approved == 0:
            approver = {'id': matched_user[0], 'name': matched_user[1], 'role': matched_user[3]}
        else:
            return jsonify({'success': False, 'error': 'You are not authorized to send back this SOP at its current stage.'})
    else:
        return jsonify({'success': False, 'error': 'Insufficient permissions. Only faculty reviewers, lab managers, and admins can send back SOPs.'})
    
    if not approver:
        return jsonify({'success': False, 'error': 'Authorization failed. Please contact an administrator.'})
    
    # Send back to draft and reset review routing
    db.execute(
        '''UPDATE sops 
           SET status = 'draft',
               faculty_approved = 0,
               next_reviewer_id = NULL,
               next_reviewer_name = NULL
           WHERE sop_id = ?''',
        (sop_id,)
    )
    db.commit()
    
    # Move back to draft folder
    move_sop_directory(sop_id, 'submitted', 'draft', sop[3], sop[3])
    
    # Add comment
    db.execute(
        '''INSERT INTO sop_comments (sop_id, user_id, user_name, user_role, comment) 
           VALUES (?, ?, ?, ?, ?)''',
        (sop_id, approver['id'], approver['name'], approver['role'], comment)
    )
    db.commit()
    
    # Log action
    db.execute(
        '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (sop_id, 'sent_back', approver['id'], approver['name'], approver['role'], 
         'Sent back to draft with comments', sop[8], sop[9])
    )
    db.commit()
    
    return jsonify({'success': True, 'message': 'SOP sent back to owner with comments'})

@app.route('/mark-sop-reviewed', methods=['POST'])
def mark_sop_reviewed():
    """Mark SOP as reviewed by faculty with PIN verification"""
    data = request.get_json()
    sop_id = data.get('sop_id')
    pin = data.get('pin')
    
    if not sop_id or not pin:
        return jsonify({'success': False, 'error': 'Missing sop_id or pin'})
    
    # Get SOP data
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        return jsonify({'success': False, 'error': 'SOP not found'})
    
    if sop[7] != 'approved':
        return jsonify({'success': False, 'error': 'Only approved SOPs can be marked as reviewed'})
    
    # Verify reviewer PIN and role (faculty or admin)
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()
    
    reviewer = None
    for user in users:
        if bcrypt.checkpw(pin.encode('utf-8'), user[2].encode('utf-8')):
            if user[3] in ['faculty_reviewer', 'admin']:
                reviewer = {'id': user[0], 'name': user[1], 'role': user[3]}
            break
    
    if not reviewer:
        return jsonify({'success': False, 'error': 'Invalid PIN or insufficient permissions. Only faculty reviewers and admins can mark SOPs as reviewed.'})
    
    # Update review information
    current_version_major = sop[11]  # approved_version_major
    current_version_minor = sop[12]  # approved_version_minor
    
    db.execute(
        '''UPDATE sops 
           SET last_reviewed_at = CURRENT_TIMESTAMP,
               last_reviewed_by_id = ?,
               last_reviewed_by_name = ?,
               last_reviewed_version_major = ?,
               last_reviewed_version_minor = ?
           WHERE sop_id = ?''',
        (reviewer['id'], reviewer['name'], current_version_major, current_version_minor, sop_id)
    )
    db.commit()
    
    # Log action
    db.execute(
        '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (sop_id, 'reviewed', reviewer['id'], reviewer['name'], reviewer['role'], 
         f'Reviewed by {reviewer["name"]} - v{current_version_major}.{current_version_minor}', 
         current_version_major, current_version_minor)
    )
    db.commit()
    
    return jsonify({'success': True, 'message': f'SOP marked as reviewed by {reviewer["name"]}'})

@app.route('/pull-back-sop', methods=['POST'])
def pull_back_sop_api():
    """Pull back SOP with PIN verification"""
    data = request.get_json()
    sop_id = data.get('sop_id')
    pin = data.get('pin')
    
    if not sop_id or not pin:
        return jsonify({'success': False, 'error': 'Missing sop_id or pin'})
    
    # Get SOP data
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        return jsonify({'success': False, 'error': 'SOP not found'})
    
    if sop[7] != 'submitted':
        return jsonify({'success': False, 'error': 'Only submitted SOPs can be pulled back'})
    
    # Verify owner PIN
    cursor = db.execute('SELECT * FROM users WHERE id = ?', (sop[4],))
    owner = cursor.fetchone()
    
    if not owner or not bcrypt.checkpw(pin.encode('utf-8'), owner[2].encode('utf-8')):
        return jsonify({'success': False, 'error': 'Invalid PIN'})
    
    # Update status
    db.execute(
        '''UPDATE sops 
           SET status = 'draft'
           WHERE sop_id = ?''',
        (sop_id,)
    )
    db.commit()
    
    # Move back to draft folder
    move_sop_directory(sop_id, 'submitted', 'draft', sop[3], sop[3])
    
    # Log action
    db.execute(
        '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (sop_id, 'pulled_back', owner[0], owner[1], owner[3], 'Pulled back to draft', sop[8], sop[9])
    )
    db.commit()
    
    return jsonify({'success': True, 'message': 'SOP pulled back to draft'})

@app.route('/new-sop', methods=['GET', 'POST'])
def new_sop():
    if request.method == 'GET':
        # Get list of courses
        cursor = db.execute('SELECT DISTINCT course FROM sops WHERE status = "approved" AND course IS NOT NULL ORDER BY course')
        courses = [row[0] for row in cursor.fetchall()]
        return render_template('new_sop.html', courses=courses)
    
    # POST - create SOP
    title = request.form.get('title')
    course_new = request.form.get('courseNew', '').strip()
    course_select = request.form.get('courseSelect', '').strip()
    course = request.form.get('course', '').strip()  # For when no courses exist yet
    
    # Determine which course value to use
    if course_new:
        course = course_new
    elif course_select:
        course = course_select
    
    creator_pin = request.form.get('creatorPin')
    
    if not title or not course or not creator_pin:
        flash('Title, course, and creator PIN are required', 'error')
        return redirect(url_for('new_sop'))
    
    # Verify creator PIN and check if faculty or admin
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()
    
    creator = None
    for user in users:
        user_id, name, pin_hash, role = user[0], user[1], user[2], user[3]
        if bcrypt.checkpw(creator_pin.encode('utf-8'), pin_hash.encode('utf-8')):
            if role in ['faculty', 'faculty_reviewer', 'admin']:
                creator = {'id': user_id, 'name': name, 'role': role}
            break
    
    if not creator:
        flash('Invalid PIN or insufficient permissions. Only faculty and admin can create SOPs.', 'error')
        return redirect(url_for('new_sop'))
    
    # Generate unique SOP ID
    sop_id = generate_sop_id()
    
    # Create SOP directory structure in Drafts
    create_sop_directory(sop_id, 'draft', course)
    
    # Create initial approved version (blank) for diff comparison in the draft directory
    save_approved_version(sop_id, course, '', status='draft')
    
    # Insert SOP into database
    cursor = db.execute(
        '''INSERT INTO sops (sop_id, title, course, owner_id, owner_name, 
           created_by_id, created_by_name, status, approved_procedure) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (sop_id, title, course, creator['id'], creator['name'], 
         creator['id'], creator['name'], 'draft', '')
    )
    db.commit()
    
    # Log creation
    db.execute(
        '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (sop_id, 'created', creator['id'], creator['name'], creator['role'], f'Created SOP: {title}', 0, 0)
    )
    db.commit()
    
    flash('SOP created successfully', 'success')
    return redirect(url_for('edit_sop', sop_id=sop_id))

@app.route('/create-draft-from-approved/<sop_id>', methods=['POST'])
def create_draft_from_approved(sop_id):
    """Create a new draft from an approved SOP, leaving the original intact"""
    # Get the approved SOP
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    approved_sop = cursor.fetchone()
    
    if not approved_sop:
        flash('SOP not found', 'error')
        return redirect(url_for('sops'))
    
    if approved_sop[7] != 'approved':
        flash('Can only create drafts from approved SOPs', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Generate new SOP ID for the draft
    new_sop_id = generate_sop_id()
    
    # Create SOP directory for the new draft
    create_sop_directory(new_sop_id, 'draft', approved_sop[3])
    
    # Copy approved procedure as starting point for draft
    approved_content = approved_sop[10]  # approved_procedure
    
    # Create initial approved version (the current approved content) for diff comparison
    # Save it in the draft directory, not creating a separate approved directory
    save_approved_version(new_sop_id, approved_sop[3], approved_content, status='draft')
    
    # Insert new draft SOP with content from approved version
    cursor = db.execute(
        '''INSERT INTO sops (sop_id, title, course, owner_id, owner_name, 
           created_by_id, created_by_name, status, procedure, approved_procedure,
           version_major, version_minor, approved_version_major, approved_version_minor,
           is_major_change) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (new_sop_id, approved_sop[2], approved_sop[3], approved_sop[4], approved_sop[5],
         approved_sop[4], approved_sop[5], 'draft', approved_content, approved_content,
         approved_sop[11], approved_sop[12], approved_sop[11], approved_sop[12], 1)
    )
    db.commit()
    
    # Save procedure to file
    save_sop_file(new_sop_id, 'draft', approved_sop[3], approved_content)
    
    # Log creation
    db.execute(
        '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (new_sop_id, 'created_from_approved', approved_sop[4], approved_sop[5], 'faculty', 
         f'Created draft from approved SOP: {approved_sop[2]}', approved_sop[11], approved_sop[12])
    )
    db.commit()
    
    flash(f'New draft created from approved SOP. Original remains in {approved_sop[3]}.', 'success')
    return redirect(url_for('edit_sop', sop_id=new_sop_id))

@app.route('/edit-sop/<sop_id>', methods=['GET', 'POST'])
def edit_sop(sop_id):
    # Get SOP data
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               version_major, version_minor, approved_procedure, approved_version_major,
               approved_version_minor, created_by_id, created_by_name, created_at,
               updated_at, submitted_at, approved_at, comments, is_major_change,
               approved_by_id, approved_by_name, faculty_approved, next_reviewer_id,
               next_reviewer_name, last_reviewed_at, last_reviewed_by_id,
               last_reviewed_by_name, last_reviewed_version_major, last_reviewed_version_minor
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        flash('SOP not found', 'error')
        return redirect(url_for('sops'))
    
    if request.method == 'GET':
        # Get faculty/admin/faculty_reviewer users for owner dropdown
        cursor = db.execute('SELECT id, name, role FROM users WHERE role IN ("faculty", "faculty_reviewer", "admin") ORDER BY name')
        faculty_admin_users = cursor.fetchall()
        
        # Get faculty_reviewer users for the major-change reviewer dropdown
        cursor = db.execute('SELECT id, name FROM users WHERE role = "faculty_reviewer" ORDER BY name')
        faculty_reviewer_users = cursor.fetchall()
        
        # Get comments
        cursor = db.execute('SELECT * FROM sop_comments WHERE sop_id = ? ORDER BY timestamp DESC', (sop_id,))
        comments = cursor.fetchall()
        
        # Parse sections from procedure (for draft/submitted)
        sections = parse_markdown_sections(sop[6] or '', sop[2])
        
        # Parse approved sections (for approved SOPs)
        approved_sections = parse_markdown_sections(sop[10] or '', sop[2])
        
        # Perform chemical lookup on Reagent list
        reagent_chemicals = []
        approved_reagent_chemicals = []
        
        if CHEMICAL_SAFETY_AVAILABLE:
            # Look up chemicals from draft/submitted procedure
            if 'Reagent list' in sections and sections['Reagent list']:
                reagent_names = parse_reagent_list(sections['Reagent list'])
                reagent_chemicals = lookup_chemicals(reagent_names)
            
            # Look up chemicals from approved procedure
            if 'Reagent list' in approved_sections and approved_sections['Reagent list']:
                approved_reagent_names = parse_reagent_list(approved_sections['Reagent list'])
                approved_reagent_chemicals = lookup_chemicals(approved_reagent_names)
        
        # Generate diff if pending
        diff_html = None
        if sop[7] == 'submitted':
            if sop[10]:  # approved_procedure exists
                diff_html = format_diff_html(sop[10], sop[6])
            else:
                # No approved version yet - show entire procedure as new
                diff_html = format_diff_html('', sop[6])
        
        return render_template('edit_sop.html', 
                               sop=sop, 
                               faculty_admin_users=faculty_admin_users,
                               faculty_reviewer_users=faculty_reviewer_users,
                               comments=comments,
                               diff_html=diff_html,
                               sections=sections,
                               approved_sections=approved_sections,
                               standard_sections=STANDARD_SOP_SECTIONS,
                               reagent_chemicals=reagent_chemicals,
                               approved_reagent_chemicals=approved_reagent_chemicals,
                               chemical_safety_available=CHEMICAL_SAFETY_AVAILABLE)
    
    # POST - handle actions based on the button pressed
    action = request.form.get('action')
    
    if action == 'save':
        return handle_save_sop(sop_id, sop)
    elif action == 'submit':
        return handle_submit_sop(sop_id, sop)
    elif action == 'pull_back':
        return handle_pull_back_sop(sop_id, sop)
    elif action == 'approve':
        return handle_approve_sop(sop_id, sop)
    elif action == 'send_back':
        return handle_send_back_sop(sop_id, sop)
    
    flash('Invalid action', 'error')
    return redirect(url_for('edit_sop', sop_id=sop_id))

def handle_save_sop(sop_id, sop):
    title = request.form.get('title')
    course = request.form.get('course')
    owner_id = request.form.get('ownerId')
    version_type = request.form.get('versionType')  # 'major' or 'minor'
    
    # Collect section content from form
    sections = {}
    for section_name in STANDARD_SOP_SECTIONS:
        sections[section_name] = request.form.get(f'section_{section_name}', '').strip()
    
    # Build markdown from sections
    procedure = build_markdown_from_sections(title, sections)
    
    if not version_type:
        flash('Please select whether this is a major or minor change', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    is_major_change = 1 if version_type == 'major' else 0
    
    old_status = sop[7]
    old_course = sop[3]
    
    # DO NOT increment version on save - only on approval
    # Just store the is_major_change flag for when it gets approved
    
    # Update SOP
    db.execute(
        '''UPDATE sops 
           SET title = ?, course = ?, owner_id = ?, 
               owner_name = (SELECT name FROM users WHERE id = ?),
               procedure = ?, updated_at = CURRENT_TIMESTAMP,
               is_major_change = ?,
               status = 'draft'
           WHERE sop_id = ?''',
        (title, course, owner_id, owner_id, procedure, is_major_change, sop_id)
    )
    db.commit()
    
    # Save procedure to file
    save_sop_file(sop_id, 'draft', course, procedure)
    
    # Move directory if needed
    if old_course != course or old_status != 'draft':
        move_sop_directory(sop_id, old_status, 'draft', old_course, course)
    
    flash(f'SOP saved successfully', 'success')
    return redirect(url_for('sops'))

def handle_submit_sop(sop_id, sop):
    owner_pin = request.form.get('ownerPin')
    
    if not owner_pin:
        flash('Owner PIN is required', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    sop_owner_id = sop[4]
    sop_course = sop[3]
    sop_status = sop[7]
    
    if sop_status != 'draft':
        flash('Only draft SOPs can be submitted', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Verify owner PIN
    cursor = db.execute('SELECT * FROM users WHERE id = ?', (sop_owner_id,))
    owner = cursor.fetchone()
    
    if not owner or not bcrypt.checkpw(owner_pin.encode('utf-8'), owner[2].encode('utf-8')):
        flash('Invalid owner PIN', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Update status
    db.execute(
        '''UPDATE sops 
           SET status = 'submitted', submitted_at = CURRENT_TIMESTAMP
           WHERE sop_id = ?''',
        (sop_id,)
    )
    db.commit()
    
    # Move to pending approval folder
    move_sop_directory(sop_id, 'draft', 'submitted', sop_course, sop_course)
    
    # Log action
    db.execute(
        '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (sop_id, 'submitted', owner[0], owner[1], owner[3], 'Submitted for approval', sop[8], sop[9])
    )
    db.commit()
    
    flash('SOP submitted for approval', 'success')
    return redirect(url_for('sops'))

def handle_pull_back_sop(sop_id, sop):
    owner_pin = request.form.get('ownerPin')
    
    if not owner_pin:
        flash('Owner PIN is required', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    sop_owner_id = sop[4]
    sop_course = sop[3]
    sop_status = sop[7]
    
    if sop_status != 'submitted':
        flash('Only submitted SOPs can be pulled back', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Verify owner PIN
    cursor = db.execute('SELECT * FROM users WHERE id = ?', (sop_owner_id,))
    owner = cursor.fetchone()
    
    if not owner or not bcrypt.checkpw(owner_pin.encode('utf-8'), owner[2].encode('utf-8')):
        flash('Invalid owner PIN', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Update status
    db.execute(
        '''UPDATE sops 
           SET status = 'draft'
           WHERE sop_id = ?''',
        (sop_id,)
    )
    db.commit()
    
    # Move back to draft folder
    move_sop_directory(sop_id, 'submitted', 'draft', sop_course, sop_course)
    
    # Log action
    db.execute(
        '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (sop_id, 'pulled_back', owner[0], owner[1], owner[3], 'Pulled back to draft', sop[8], sop[9])
    )
    db.commit()
    
    flash('SOP pulled back to draft', 'success')
    return redirect(url_for('sops'))

def handle_approve_sop(sop_id, sop):
    approver_pin = request.form.get('approverPin')
    comment = request.form.get('comment', '')
    
    if not approver_pin:
        flash('Approver PIN is required', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    sop_course = sop[3]
    sop_status = sop[7]
    sop_procedure = sop[6]
    
    if sop_status != 'submitted':
        flash('Only submitted SOPs can be approved', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Verify approver PIN and role
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()
    
    approver = None
    for user in users:
        if bcrypt.checkpw(approver_pin.encode('utf-8'), user[2].encode('utf-8')):
            if user[3] in ['lab_manager', 'admin']:
                approver = {'id': user[0], 'name': user[1], 'role': user[3]}
            break
    
    if not approver:
        flash('Invalid PIN or insufficient permissions. Only lab managers and admins can approve SOPs.', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Approve
    db.execute(
        '''UPDATE sops 
           SET status = 'approved', approved_at = CURRENT_TIMESTAMP,
               approved_procedure = procedure,
               approved_version_major = version_major,
               approved_version_minor = version_minor,
               comments = ?
           WHERE sop_id = ?''',
        (comment, sop_id)
    )
    db.commit()
    
    # Move to approved folder first
    move_sop_directory(sop_id, 'submitted', 'approved', sop_course, sop_course)
    
    # Then save approved version (now that it's in the right place)
    save_approved_version(sop_id, sop_course, sop_procedure)
    
    # Log action
    db.execute(
        '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (sop_id, 'approved', approver['id'], approver['name'], approver['role'], 
         f'Approved by {approver["name"]}', sop[8], sop[9])
    )
    db.commit()
    
    # Add comment if provided
    if comment:
        db.execute(
            '''INSERT INTO sop_comments (sop_id, user_id, user_name, user_role, comment) 
               VALUES (?, ?, ?, ?, ?)''',
            (sop_id, approver['id'], approver['name'], approver['role'], comment)
        )
        db.commit()
    
    flash('SOP approved successfully', 'success')
    return redirect(url_for('sops'))

def handle_send_back_sop(sop_id, sop):
    approver_pin = request.form.get('approverPin')
    comment = request.form.get('comment', '')
    
    if not approver_pin:
        flash('Approver PIN is required', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    if not comment:
        flash('Comment is required when sending back', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    sop_course = sop[3]
    sop_status = sop[7]
    is_major_change = sop[20] or 0  # Default to 0 if None
    faculty_approved = sop[23] or 0  # Default to 0 if None
    next_reviewer_id = sop[24]
    next_reviewer_name = sop[25]
    
    # Debug logging
    print(f"DEBUG handle_send_back_sop:")
    print(f"  sop_id: {sop_id}") 
    print(f"  is_major_change: {is_major_change}")
    print(f"  faculty_approved: {faculty_approved}")
    print(f"  next_reviewer_id: {next_reviewer_id}")
    print(f"  next_reviewer_name: {next_reviewer_name}")
    print(f"  sop_status: {sop_status}")
    
    if sop_status != 'submitted':
        flash('Only submitted SOPs can be sent back', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Verify approver PIN and role
    cursor = db.execute('SELECT * FROM users')
    users = cursor.fetchall()
    
    approver = None
    matched_user = None
    
    # First, find the user with matching PIN
    for user in users:
        if bcrypt.checkpw(approver_pin.encode('utf-8'), user[2].encode('utf-8')):
            matched_user = user
            break
    
    if not matched_user:
        flash('Invalid PIN', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Check if user has permission to send back
    user_role = matched_user[3]
    user_id = matched_user[0]
    
    if user_role in ['lab_manager', 'admin']:
        # Lab managers and admins can always send back
        approver = {'id': matched_user[0], 'name': matched_user[1], 'role': matched_user[3]}
    elif user_role == 'faculty':
        # Faculty can only send back if they're reviewing a major change
        print(f"DEBUG Faculty check:")
        print(f"  user_id: {user_id}")
        print(f"  is_major_change: {is_major_change} (type: {type(is_major_change)})")
        print(f"  faculty_approved: {faculty_approved} (type: {type(faculty_approved)})")
        print(f"  next_reviewer_id: {next_reviewer_id} (type: {type(next_reviewer_id)})")
        print(f"  Condition 1 (is_major_change): {is_major_change}")
        print(f"  Condition 2 (faculty_approved == 0): {faculty_approved == 0}")
        print(f"  Condition 3 (next_reviewer_id exists): {bool(next_reviewer_id)}")
        print(f"  Condition 4 (next_reviewer_id == user_id): {next_reviewer_id == user_id}")
        
        if is_major_change and faculty_approved == 0 and next_reviewer_id and next_reviewer_id == user_id:
            approver = {'id': matched_user[0], 'name': matched_user[1], 'role': matched_user[3]}
        else:
            flash('You are not authorized to send back this SOP. Only the designated faculty reviewer, lab managers, and admins can send back SOPs.', 'error')
            return redirect(url_for('edit_sop', sop_id=sop_id))
    else:
        flash('Insufficient permissions. Only faculty reviewers, lab managers, and admins can send back SOPs.', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    if not approver:
        flash('Authorization failed. Please contact an administrator.', 'error')
        return redirect(url_for('edit_sop', sop_id=sop_id))
    
    # Send back to draft and reset review routing
    db.execute(
        '''UPDATE sops 
           SET status = 'draft',
               next_reviewer_id = NULL,
               next_reviewer_name = NULL,
               faculty_approved = 0
           WHERE sop_id = ?''',
        (sop_id,)
    )
    db.commit()
    
    # Move back to draft folder
    move_sop_directory(sop_id, 'submitted', 'draft', sop_course, sop_course)
    
    # Add comment
    db.execute(
        '''INSERT INTO sop_comments (sop_id, user_id, user_name, user_role, comment) 
           VALUES (?, ?, ?, ?, ?)''',
        (sop_id, approver['id'], approver['name'], approver['role'], comment)
    )
    db.commit()
    
    # Log action
    db.execute(
        '''INSERT INTO sop_log (sop_id, action, user_id, user_name, user_role, details, version_major, version_minor) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (sop_id, 'sent_back', approver['id'], approver['name'], approver['role'], 
         'Sent back to draft with comments', sop[8], sop[9])
    )
    db.commit()
    
    flash('SOP sent back to owner with comments', 'success')
    return redirect(url_for('sops'))

# --- DOWNLOAD/UPLOAD MARKDOWN ---
@app.route('/download-sop-md/<sop_id>')
def download_sop_md(sop_id):
    """Download SOP as markdown file"""
    # Get SOP data
    cursor = db.execute('''
        SELECT id, sop_id, title, course, owner_id, owner_name, procedure, status,
               approved_procedure
        FROM sops WHERE sop_id = ?
    ''', (sop_id,))
    sop = cursor.fetchone()
    
    if not sop:
        flash('SOP not found', 'error')
        return redirect(url_for('sops'))
    
    title = sop[2]
    course = sop[3]
    owner_name = sop[5]
    status = sop[7]
    
    # Use approved_procedure if status is approved, otherwise use current procedure
    if status == 'approved' and sop[8]:
        procedure = sop[8]
    else:
        procedure = sop[6] or ''
    
    # Parse existing sections
    sections = parse_markdown_sections(procedure, title)
    
    # Pre-populate Lab Description section
    metadata = f"Course: {course}\nOwner: {owner_name}"
    sections['Lab Description'] = metadata
    
    # Build complete markdown
    procedure = build_markdown_from_sections(title, sections)
    
    # Create file in memory
    file_data = io.BytesIO(procedure.encode('utf-8'))
    
    # Generate filename
    filename = f"{sanitize_filename(title)}_{sop_id}.md"
    
    return send_file(
        file_data,
        mimetype='text/markdown',
        as_attachment=True,
        download_name=filename
    )

@app.route('/upload-sop-md', methods=['POST'])
def upload_sop_md():
    """Parse uploaded markdown file and return sections"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'})
    
    file = request.files['file']
    
    if not file or file.filename == '' or file.filename is None:
        return jsonify({'success': False, 'error': 'No file selected'})
    
    if not file.filename.endswith('.md'):
        return jsonify({'success': False, 'error': 'File must be a markdown (.md) file'})
    
    # Read file content
    content = file.read().decode('utf-8')
    
    # Extract title (first H1 heading)
    title = ''
    for line in content.split('\n'):
        if line.startswith('# ') and not line.startswith('## '):
            title = line[2:].strip()
            break
    
    # Parse sections
    sections = parse_markdown_sections(content, title)
    
    return jsonify({
        'success': True,
        'title': title,
        'sections': sections
    })

# --- RUN APP ---
def main():
    """Main entry point for the application"""
    app.run(debug=True, host='localhost', port=3000)

if __name__ == '__main__':
    main()
