import sqlite3
import bcrypt
import os
from datetime import datetime

# Database connection
db = sqlite3.connect('lab_management.db', check_same_thread=False)
db.row_factory = sqlite3.Row

def init_db():
    """Initialize database schema and create admin user"""
    cursor = db.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            pin_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'faculty', 'faculty_reviewer', 'lab_manager', 'general')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            approved_by INTEGER,
            FOREIGN KEY (approved_by) REFERENCES users(id)
        )
    ''')
    
    # Pending approvals table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            pin_hash TEXT NOT NULL,
            requested_role TEXT NOT NULL CHECK(requested_role IN ('faculty', 'faculty_reviewer', 'lab_manager', 'general')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Approval log table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS approval_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL,
            requested_role TEXT NOT NULL,
            approved_by_name TEXT NOT NULL,
            approved_by_role TEXT NOT NULL,
            approval_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # SOPs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sop_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            course TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            owner_name TEXT NOT NULL,
            procedure TEXT,
            status TEXT DEFAULT 'draft' CHECK(status IN ('draft', 'submitted', 'approved')),
            version_major INTEGER DEFAULT 0,
            version_minor INTEGER DEFAULT 0,
            approved_procedure TEXT,
            approved_version_major INTEGER DEFAULT 0,
            approved_version_minor INTEGER DEFAULT 0,
            created_by_id INTEGER NOT NULL,
            created_by_name TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            submitted_at DATETIME,
            approved_at DATETIME,
            comments TEXT,
            FOREIGN KEY (owner_id) REFERENCES users(id),
            FOREIGN KEY (created_by_id) REFERENCES users(id)
        )
    ''')
    
    # SOP log table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sop_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sop_id TEXT NOT NULL,
            action TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            user_role TEXT NOT NULL,
            details TEXT,
            version_major INTEGER,
            version_minor INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sop_id) REFERENCES sops(sop_id)
        )
    ''')
    
    # SOP comments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sop_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sop_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            user_role TEXT NOT NULL,
            comment TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sop_id) REFERENCES sops(sop_id)
        )
    ''')
    
    db.commit()
    
    # Run migrations to add any missing columns
    migrate_db()

def migrate_db():
    """Add any missing columns to existing tables"""
    cursor = db.cursor()
    
    # Migrate sops table
    cursor.execute('PRAGMA table_info(sops)')
    existing_sops_columns = {row[1] for row in cursor.fetchall()}
    
    sops_columns_to_add = {
        'version_major': 'INTEGER DEFAULT 0',
        'version_minor': 'INTEGER DEFAULT 0',
        'approved_procedure': 'TEXT',
        'approved_version_major': 'INTEGER DEFAULT 0',
        'approved_version_minor': 'INTEGER DEFAULT 0',
        'submitted_at': 'DATETIME',
        'approved_at': 'DATETIME',
        'comments': 'TEXT',
        'is_major_change': 'INTEGER DEFAULT 1',
        'approved_by_id': 'INTEGER',
        'approved_by_name': 'TEXT',
        'next_reviewer_id': 'INTEGER',
        'next_reviewer_name': 'TEXT',
        'faculty_approved': 'INTEGER DEFAULT 0',
        'last_reviewed_at': 'DATETIME',
        'last_reviewed_by_id': 'INTEGER',
        'last_reviewed_by_name': 'TEXT',
        'last_reviewed_version_major': 'INTEGER',
        'last_reviewed_version_minor': 'INTEGER'
    }
    
    for column_name, column_type in sops_columns_to_add.items():
        if column_name not in existing_sops_columns:
            try:
                cursor.execute(f'ALTER TABLE sops ADD COLUMN {column_name} {column_type}')
                print(f'Added column {column_name} to sops table')
            except sqlite3.OperationalError as e:
                print(f'Could not add column {column_name}: {e}')
    
    # Migrate sop_log table
    cursor.execute('PRAGMA table_info(sop_log)')
    existing_log_columns = {row[1] for row in cursor.fetchall()}
    
    log_columns_to_add = {
        'version_major': 'INTEGER',
        'version_minor': 'INTEGER'
    }
    
    for column_name, column_type in log_columns_to_add.items():
        if column_name not in existing_log_columns:
            try:
                cursor.execute(f'ALTER TABLE sop_log ADD COLUMN {column_name} {column_type}')
                print(f'Added column {column_name} to sop_log table')
            except sqlite3.OperationalError as e:
                print(f'Could not add column {column_name}: {e}')

    # Migrate users table to support faculty_reviewer role
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
    users_schema = cursor.fetchone()
    if users_schema and 'faculty_reviewer' not in users_schema[0]:
        cursor.execute('ALTER TABLE users RENAME TO _users_old')
        cursor.execute('''CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            pin_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'faculty', 'faculty_reviewer', 'lab_manager', 'general')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            approved_by INTEGER,
            FOREIGN KEY (approved_by) REFERENCES users(id)
        )''')
        cursor.execute('INSERT INTO users SELECT * FROM _users_old')
        cursor.execute('DROP TABLE _users_old')
        print('Migrated users table to support faculty_reviewer role')

    # Migrate pending_approvals table to support faculty_reviewer role
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pending_approvals'")
    pa_schema = cursor.fetchone()
    if pa_schema and 'faculty_reviewer' not in pa_schema[0]:
        cursor.execute('ALTER TABLE pending_approvals RENAME TO _pending_approvals_old')
        cursor.execute('''CREATE TABLE pending_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            pin_hash TEXT NOT NULL,
            requested_role TEXT NOT NULL CHECK(requested_role IN ('faculty', 'faculty_reviewer', 'lab_manager', 'general')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        cursor.execute('INSERT INTO pending_approvals SELECT * FROM _pending_approvals_old')
        cursor.execute('DROP TABLE _pending_approvals_old')
        print('Migrated pending_approvals table to support faculty_reviewer role')

    db.commit()
