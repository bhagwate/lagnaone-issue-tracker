import os
import sqlite3
import datetime
import hashlib
from flask import Flask, request, render_template, redirect, url_for, session, flash, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime, timezone, timedelta
import random
import json

# --- Basic Setup ---
app = Flask(__name__)
app.secret_key = 'a_very_secret_key_for_lagnaone' # Change this in a real application
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max file size
app.config['DATABASE'] = 'lagnaone_issues.db'

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- Database Helper Functions ---
def get_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

# --- Application Routes ---

@app.route('/', methods=['GET', 'POST'])
def submit_issue():
    """Renders the submission form and handles new issue submissions."""
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        issue_type = request.form['type']
        details = request.form['details']

        screenshot_filename = None
        if 'screenshot' in request.files:
            file = request.files['screenshot']
            if file and file.filename:
                # Secure the filename and save the file
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{file.filename}")
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                screenshot_filename = filename

        conn = get_db()
        conn.execute(
            'INSERT INTO issues (name, email, type, details, screenshot) VALUES (?, ?, ?, ?, ?)',
            (name, email, issue_type, details, screenshot_filename)
        )
        conn.commit()
        conn.close()
        
        flash('Your issue has been submitted successfully!', 'success')
        return redirect(url_for('submit_issue'))

    return render_template('submit.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    """Handles admin login and displays the dashboard."""
    if request.method == 'POST':
        # This is a very basic password check.
        if request.form['password'] == 'admin123':
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            flash('Incorrect password.', 'danger')

    if not session.get('logged_in'):
        return render_template('login.html')

    conn = get_db()
    issues = conn.execute('SELECT * FROM issues ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('dashboard.html', issues=issues)

@app.route('/admin/logout')
def logout():
    session.pop('logged_in', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('admin'))

@app.route('/admin/update_status/<int:issue_id>', methods=['POST'])
def update_status(issue_id):
    if not session.get('logged_in'):
        return redirect(url_for('admin'))
    
    status = request.form['status']
    conn = get_db()
    conn.execute('UPDATE issues SET status = ? WHERE id = ?', (status, issue_id))
    conn.commit()
    conn.close()
    flash(f'Issue #{issue_id} status updated to {status}.', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete_issue/<int:issue_id>', methods=['POST'])
def delete_issue(issue_id):
    if not session.get('logged_in'):
        return redirect(url_for('admin'))

    conn = get_db()
    # First, get the screenshot filename to delete the file
    issue = conn.execute('SELECT screenshot FROM issues WHERE id = ?', (issue_id,)).fetchone()
    if issue and issue['screenshot']:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], issue['screenshot']))
        except OSError as e:
            print(f"Error deleting file {issue['screenshot']}: {e.strerror}")

    # Then, delete the database record
    conn.execute('DELETE FROM issues WHERE id = ?', (issue_id,))
    conn.commit()
    conn.close()
    flash(f'Issue #{issue_id} has been deleted.', 'success')
    return redirect(url_for('admin'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serves uploaded files."""
    if not session.get('logged_in'):
        return "Access denied", 403
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Command to initialize the database
@app.cli.command('initdb')
def initdb_command():
    """Creates the database tables."""
    init_db()
    print('Initialized the database.')

if __name__ == '__main__':
    app.run(debug=True)
