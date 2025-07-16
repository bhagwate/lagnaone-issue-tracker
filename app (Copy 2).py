import os
import sqlite3
import datetime
import hashlib
from flask import Flask, request, render_template, redirect, url_for, session, flash, send_from_directory
from werkzeug.utils import secure_filename
from datetime import datetime, timezone, timedelta
import random
import json

app = Flask(__name__)
app.secret_key = 'lagnaone_secret_key'  # Replace with a secure key in production
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max file size

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database setup
def init_db():
    conn = sqlite3.connect('lagnaone_issues.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        type TEXT NOT NULL,
        details TEXT NOT NULL,
        screenshot TEXT,
        status TEXT NOT NULL DEFAULT 'Open',
        created_at TIMESTAMP NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_limit (
        date TEXT PRIMARY KEY,
        count INTEGER NOT NULL DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS admin_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    # Set default daily limit and admin password if not set
    c.execute("INSERT OR IGNORE INTO admin_config (key, value) VALUES ('daily_limit', '50')")
    c.execute("INSERT OR IGNORE INTO admin_config (key, value) VALUES ('admin_password', ?)",
              (hashlib.sha256('admin123'.encode()).hexdigest(),))  # Default password: admin123
    conn.commit()
    conn.close()

init_db()

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

# Helper to get current IST date
def get_ist_date():
    return datetime.now(IST).strftime('%Y-%m-%d')

# Check and reset daily limit
def check_daily_limit():
    conn = sqlite3.connect('lagnaone_issues.db')
    c = conn.cursor()
    today = get_ist_date()
    c.execute("SELECT count FROM daily_limit WHERE date = ?", (today,))
    result = c.fetchone()
    c.execute("SELECT value FROM admin_config WHERE key = 'daily_limit'")
    daily_limit = int(c.fetchone()[0])
    if not result:
        c.execute("INSERT INTO daily_limit (date, count) VALUES (?, 0)", (today,))
        count = 0
    else:
        count = result[0]
    # Reset old dates
    c.execute("DELETE FROM daily_limit WHERE date != ?", (today,))
    conn.commit()
    conn.close()
    return count < daily_limit, count, daily_limit

# User form route
@app.route('/', methods=['GET', 'POST'])
def submit_issue():
    if request.method == 'POST':
        can_submit, count, daily_limit = check_daily_limit()
        if not can_submit:
            flash(f'Daily submission limit of {daily_limit} reached. Try again tomorrow.', 'error')
            return redirect(url_for('submit_issue'))

        name = request.form['name']
        email = request.form['email']
        issue_type = request.form['type']
        details = request.form['details']
        captcha_answer = request.form['captcha_answer']
        captcha_solution = session.get('captcha_solution')

        if not captcha_answer or int(captcha_answer) != captcha_solution:
            flash('Invalid CAPTCHA answer.', 'error')
            return redirect(url_for('submit_issue'))

        screenshot = None
        if 'screenshot' in request.files:
            file = request.files['screenshot']
            if file and file.filename:
                filename = secure_filename(file.filename)
                if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    screenshot = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(screenshot)
                else:
                    flash('Invalid file format. Only PNG, JPG, JPEG allowed.', 'error')
                    return redirect(url_for('submit_issue'))

        conn = sqlite3.connect('lagnaone_issues.db')
        c = conn.cursor()
        c.execute("INSERT INTO issues (name, email, type, details, screenshot, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                  (name, email, issue_type, details, screenshot, datetime.now(IST)))
        c.execute("UPDATE daily_limit SET count = count + 1 WHERE date = ?", (get_ist_date(),))
        conn.commit()
        conn.close()
        flash('Issue submitted successfully!', 'success')
        return redirect(url_for('submit_issue'))

    # Generate CAPTCHA
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    session['captcha_solution'] = num1 + num2
    captcha_question = f"What is {num1} + {num2}?"
    return render_template('submit.html', captcha_question=captcha_question)

# Admin login
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form['password']
        conn = sqlite3.connect('lagnaone_issues.db')
        c = conn.cursor()
        c.execute("SELECT value FROM admin_config WHERE key = 'admin_password'")
        stored_password = c.fetchone()[0]
        conn.close()
        if hashlib.sha256(password.encode()).hexdigest() == stored_password:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Invalid password.', 'error')
    return render_template('login.html')

# Admin dashboard
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('lagnaone_issues.db')
    c = conn.cursor()
    c.execute("SELECT id, name, email, type, details, screenshot, status, created_at FROM issues ORDER BY created_at DESC")
    issues = c.fetchall()
    c.execute("SELECT value FROM admin_config WHERE key = 'daily_limit'")
    daily_limit = c.fetchone()[0]
    
    # Data for graphs
    c.execute("SELECT type, COUNT(*) FROM issues GROUP BY type")
    type_data = c.fetchall()
    c.execute("SELECT status, COUNT(*) FROM issues GROUP BY status")
    status_data = c.fetchall()
    c.execute("SELECT strftime('%Y-%m-%d', created_at, 'localtime') as date, COUNT(*) FROM issues GROUP BY date ORDER BY date")
    daily_trend = c.fetchall()
    
    # Average time to close
    c.execute("SELECT AVG(strftime('%s', created_at, 'localtime') - strftime('%s', (SELECT created_at FROM issues i2 WHERE i2.id < i1.id AND i2.status = 'Closed' ORDER BY i2.created_at DESC LIMIT 1))) FROM issues i1 WHERE status = 'Closed'")
    avg_close_time = c.fetchone()[0]
    avg_close_time = round(avg_close_time / 86400, 2) if avg_close_time else 0  # Convert seconds to days
    
    conn.close()
    return render_template('dashboard.html', issues=issues, type_data=json.dumps(type_data),
                         status_data=json.dumps(status_data), daily_trend=json.dumps(daily_trend),
                         daily_limit=daily_limit, avg_close_time=avg_close_time)

# Update issue status
@app.route('/admin/update_status/<int:id>', methods=['POST'])
def update_status(id):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    status = request.form['status']
    conn = sqlite3.connect('lagnaone_issues.db')
    c = conn.cursor()
    c.execute("UPDATE issues SET status = ? WHERE id = ?", (status, id))
    conn.commit()
    conn.close()
    flash('Status updated successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

# Update daily limit
@app.route('/admin/update_limit', methods=['POST'])
def update_limit():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    new_limit = request.form['daily_limit']
    conn = sqlite3.connect('lagnaone_issues.db')
    c = conn.cursor()
    c.execute("UPDATE admin_config SET value = ? WHERE key = 'daily_limit'", (new_limit,))
    conn.commit()
    conn.close()
    flash('Daily limit updated successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

# Serve screenshots
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

