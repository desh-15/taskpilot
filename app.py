import os
from datetime import date, datetime
from functools import wraps

from flask import (
    Flask, abort, flash, redirect, render_template_string,
    request, url_for
)
from flask_login import (
    LoginManager, UserMixin, current_user, login_required,
    login_user, logout_user
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import or_
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-before-deploying")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "sqlite:///taskpilot.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"


STATUSES = [
    "Not Started", "In Progress", "Waiting for Someone",
    "On Hold", "Completed", "Cancelled"
]
PRIORITIES = ["Low", "Medium", "High", "Critical"]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    projects = db.relationship("Project", backref="owner", cascade="all, delete-orphan")
    tasks = db.relationship("Task", backref="owner", cascade="all, delete-orphan")


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="")
    target_date = db.Column(db.Date)
    status = db.Column(db.String(30), default="Active", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    tasks = db.relationship("Task", backref="project", lazy=True)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"))
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    category = db.Column(db.String(100), default="Other")
    priority = db.Column(db.String(20), default="Medium", nullable=False)
    status = db.Column(db.String(40), default="Not Started", nullable=False)
    start_date = db.Column(db.Date)
    due_date = db.Column(db.Date, index=True)
    estimated_minutes = db.Column(db.Integer)
    actual_minutes = db.Column(db.Integer, default=0)
    waiting_for = db.Column(db.String(160))
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def owned_task(task_id):
    task = db.session.get(Task, task_id)
    if task is None or task.user_id != current_user.id:
        abort(404)
    return task


def owned_project(project_id):
    project = db.session.get(Project, project_id)
    if project is None or project.user_id != current_user.id:
        abort(404)
    return project


@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or len(password) < 8:
            flash("Enter an email and a password with at least 8 characters.")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.")
        else:
            user = User(
                email=email,
                password_hash=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for("dashboard"))

    return page(AUTH_PAGE, heading="Create your account")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.")

    return page(AUTH_PAGE, heading="Sign in")


@app.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    tasks = Task.query.filter_by(user_id=current_user.id).all()
    today = date.today()
    active = [t for t in tasks if t.status not in ("Completed", "Cancelled")]
    completed = [t for t in tasks if t.status == "Completed"]
    overdue = [t for t in active if t.due_date and t.due_date < today]
    due_today = [t for t in active if t.due_date == today]
    projects = Project.query.filter_by(user_id=current_user.id).all()

    # Suggest the most urgent active task, with a reason shown in the page.
    def urgency(task):
        days = (task.due_date - today).days if task.due_date else 9999
        priority_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        return (days, priority_rank.get(task.priority, 4))

    recommended = sorted(active, key=urgency)[:1]
    return page(
        DASHBOARD, tasks=tasks, active=active, completed=completed,
        overdue=overdue, due_today=due_today, projects=projects,
        recommended=recommended
    )


@app.route("/tasks")
@login_required
def task_list():
    query = Task.query.filter_by(user_id=current_user.id)
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    priority = request.args.get("priority", "")

    if search:
        query = query.filter(or_(
            Task.title.ilike(f"%{search}%"),
            Task.description.ilike(f"%{search}%"),
            Task.category.ilike(f"%{search}%")
        ))
    if status in STATUSES:
        query = query.filter_by(status=status)
    if priority in PRIORITIES:
        query = query.filter_by(priority=priority)

    tasks = query.order_by(Task.due_date.is_(None), Task.due_date, Task.created_at.desc()).all()
    return page(TASKS_PAGE, tasks=tasks)


@app.route("/tasks/new", methods=["GET", "POST"])
@app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(task_id=None):
    task = owned_task(task_id) if task_id else Task(user_id=current_user.id)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("A task title is required.")
            return redirect(request.url)

        task.title = title[:200]
        task.description = request.form.get("description", "").strip()
        task.category = request.form.get("category", "Other").strip()[:100] or "Other"
        task.priority = request.form.get("priority", "Medium")
        task.status = request.form.get("status", "Not Started")
        task.notes = request.form.get("notes", "").strip()
        task.waiting_for = request.form.get("waiting_for", "").strip() or None

        if task.priority not in PRIORITIES:
            task.priority = "Medium"
        if task.status not in STATUSES:
            task.status = "Not Started"

        task.start_date = parse_date(request.form.get("start_date"))
        task.due_date = parse_date(request.form.get("due_date"))
        task.estimated_minutes = parse_int(request.form.get("estimated_minutes"))
        task.actual_minutes = parse_int(request.form.get("actual_minutes")) or 0

        project_id = parse_int(request.form.get("project_id"))
        project = db.session.get(Project, project_id) if project_id else None
        task.project_id = project.id if project and project.user_id == current_user.id else None

        if task.id is None:
            db.session.add(task)
        db.session.commit()
        flash("Task saved.")
        return redirect(url_for("task_list"))

    projects = Project.query.filter_by(user_id=current_user.id).order_by(Project.name).all()
    return page(
        TASK_FORM, task=task, projects=projects,
        statuses=STATUSES, priorities=PRIORITIES
    )


@app.post("/tasks/<int:task_id>/status")
@login_required
def update_status(task_id):
    task = owned_task(task_id)
    status = request.form.get("status")
    if status in STATUSES:
        task.status = status
        db.session.commit()
        flash("Task status updated.")
    return redirect(request.referrer or url_for("task_list"))


@app.post("/tasks/<int:task_id>/delete")
@login_required
def delete_task(task_id):
    task = owned_task(task_id)
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted.")
    return redirect(url_for("task_list"))


@app.route("/projects", methods=["GET", "POST"])
@login_required
def projects():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            project = Project(
                user_id=current_user.id,
                name=name[:160],
                description=request.form.get("description", "").strip(),
                target_date=parse_date(request.form.get("target_date"))
            )
            db.session.add(project)
            db.session.commit()
            flash("Project created.")
        return redirect(url_for("projects"))

    rows = Project.query.filter_by(user_id=current_user.id).order_by(Project.name).all()
    return page(PROJECTS_PAGE, projects=rows)


@app.post("/projects/<int:project_id>/delete")
@login_required
def delete_project(project_id):
    project = owned_project(project_id)
    # Keep tasks and remove their project association.
    for task in project.tasks:
        task.project_id = None
    db.session.delete(project)
    db.session.commit()
    flash("Project deleted. Its tasks were kept.")
    return redirect(url_for("projects"))


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_int(value):
    try:
        number = int(value)
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


BASE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title or "TaskPilot" }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        rel="stylesheet">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/styles.css') }}">
</head>
<body>
<nav class="navbar navbar-expand-lg mb-4">
  <div class="container">
    <a class="brand fw-bold fs-4" href="{{ url_for('dashboard') }}">TaskPilot</a>
    {% if current_user.is_authenticated %}
    <div class="d-flex gap-3 align-items-center">
      <a href="{{ url_for('dashboard') }}">Dashboard</a>
      <a href="{{ url_for('task_list') }}">Tasks</a>
      <a href="{{ url_for('projects') }}">Projects</a>
      <form method="post" action="{{ url_for('logout') }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button class="btn btn-sm btn-outline-light">Log out</button>
      </form>
    </div>
    {% endif %}
  </div>
</nav>
<main class="container pb-5">
  {% for message in get_flashed_messages() %}
    <div class="alert alert-info">{{ message }}</div>
  {% endfor %}
  {{ content|safe }}
</main>
<script src="{{ url_for('static', filename='js/app.js') }}" defer></script>
</body>
</html>
"""


def page(content, **context):
    inner = render_template_string(content, **context)
    return render_template_string(BASE, content=inner, **context)


AUTH_PAGE = """
<div class="row justify-content-center"><div class="col-md-5">
<div class="card p-4">
<h1 class="h3 mb-3">{{ heading }}</h1>
<form method="post">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <label class="form-label">Email</label>
  <input class="form-control mb-3" type="email" name="email" required>
  <label class="form-label">Password (8 characters minimum)</label>
  <input class="form-control mb-3" type="password" name="password" minlength="8" required>
  <button class="btn btn-primary w-100">Continue</button>
</form>
<p class="mt-3 mb-0">
{% if heading == "Sign in" %}
  New here? <a href="{{ url_for('register') }}">Create an account</a>
{% else %}
  Already registered? <a href="{{ url_for('login') }}">Sign in</a>
{% endif %}
</p>
</div></div></div>
"""


DASHBOARD = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <div><h1 class="h2 mb-1">Your workspace</h1><div class="muted">A clear view of what needs attention.</div></div>
  <a class="btn btn-primary" href="{{ url_for('edit_task') }}">+ Quick add task</a>
</div>
<div class="row g-3 mb-4">
{% for label, value in [
  ("Active", active|length), ("Completed", completed|length),
  ("Overdue", overdue|length), ("Due today", due_today|length),
  ("Projects", projects|length)
] %}
<div class="col-6 col-lg"><div class="card p-3">
  <div class="muted">{{ label }}</div><div class="fs-3 fw-bold">{{ value }}</div>
</div></div>
{% endfor %}
</div>
<div class="row g-3">
<div class="col-lg-7"><div class="card p-4">
  <h2 class="h5">Today's focus</h2>
  {% if due_today %}
    {% for task in due_today %}<p><a href="{{ url_for('edit_task', task_id=task.id) }}">{{ task.title }}</a> · {{ task.priority }}</p>{% endfor %}
  {% else %}<p class="muted mb-0">No tasks due today.</p>{% endif %}
</div></div>
<div class="col-lg-5"><div class="card p-4">
  <h2 class="h5">What should I do next?</h2>
  {% if recommended %}
    {% set task = recommended[0] %}
    <p class="mb-1"><a href="{{ url_for('edit_task', task_id=task.id) }}">{{ task.title }}</a></p>
    <p class="muted mb-0">
      Recommended because it is {{ task.priority|lower }} priority
      {% if task.due_date %}and due {{ task.due_date }}{% else %}and has no due date set{% endif %}.
    </p>
  {% else %}<p class="muted mb-0">You have no active tasks.</p>{% endif %}
</div></div>
</div>
<div class="card p-4 mt-3">
  <div class="d-flex justify-content-between"><h2 class="h5">Recent tasks</h2><a href="{{ url_for('task_list') }}">View all</a></div>
  {% for task in tasks[:6] %}
  <div class="d-flex justify-content-between border-top py-2">
    <span><a href="{{ url_for('edit_task', task_id=task.id) }}">{{ task.title }}</a>
      <span class="muted">· {{ task.project.name if task.project else task.category }}</span></span>
    <span>{{ task.status }}{% if task.due_date %} · {{ task.due_date }}{% endif %}</span>
  </div>
  {% else %}<p class="muted mb-0">Add a task to get started.</p>{% endfor %}
</div>
"""


TASKS_PAGE = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1 class="h2">My tasks</h1><a class="btn btn-primary" href="{{ url_for('edit_task') }}">+ Add task</a>
</div>
<form class="row g-2 mb-3">
  <div class="col-md-5"><input class="form-control" name="q" placeholder="Search tasks" value="{{ request.args.get('q','') }}"></div>
  <div class="col-md-3"><select class="form-select" name="status"><option value="">Any status</option>
  {% for s in ["Not Started","In Progress","Waiting for Someone","On Hold","Completed","Cancelled"] %}
    <option {{ "selected" if request.args.get('status') == s }}>{{ s }}</option>
  {% endfor %}</select></div>
  <div class="col-md-2"><select class="form-select" name="priority"><option value="">Any priority</option>
  {% for p in ["Low","Medium","High","Critical"] %}
    <option {{ "selected" if request.args.get('priority') == p }}>{{ p }}</option>
  {% endfor %}</select></div>
  <div class="col-md-2"><button class="btn btn-outline-primary w-100">Filter</button></div>
</form>
<div class="card p-3">
{% for task in tasks %}
<div class="border-bottom py-3">
  <div class="d-flex justify-content-between gap-3">
    <div>
      <a class="fw-semibold" href="{{ url_for('edit_task', task_id=task.id) }}">{{ task.title }}</a>
      <div class="muted">{{ task.project.name if task.project else task.category }}
        · {{ task.status }} · {{ task.priority }}
        {% if task.due_date %} · Due {{ task.due_date }}{% endif %}
        {% if task.waiting_for %} · Waiting for {{ task.waiting_for }}{% endif %}
      </div>
    </div>
    <form method="post" action="{{ url_for('update_status', task_id=task.id) }}" class="d-flex gap-2">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <select class="form-select form-select-sm" name="status">
      {% for s in ["Not Started","In Progress","Waiting for Someone","On Hold","Completed","Cancelled"] %}
        <option {{ "selected" if task.status == s }}>{{ s }}</option>
      {% endfor %}
      </select><button class="btn btn-sm btn-outline-primary">Save</button>
    </form>
  </div>
</div>
{% else %}<p class="muted mb-0">No matching tasks.</p>{% endfor %}
</div>
"""


TASK_FORM = """
<h1 class="h2 mb-3">{{ "Edit task" if task.id else "Quick add task" }}</h1>
<div class="card p-4"><form method="post">
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
<div class="mb-3"><label class="form-label">Title</label>
<input class="form-control" name="title" maxlength="200" required value="{{ task.title or '' }}"></div>
<div class="mb-3"><label class="form-label">Description</label>
<textarea class="form-control" name="description" rows="3">{{ task.description or '' }}</textarea></div>
<div class="row g-3">
<div class="col-md-4"><label class="form-label">Category</label>
<input class="form-control" name="category" value="{{ task.category or 'Other' }}"></div>
<div class="col-md-4"><label class="form-label">Project</label>
<select class="form-select" name="project_id"><option value="">No project</option>
{% for p in projects %}<option value="{{ p.id }}" {{ "selected" if task.project_id == p.id }}>{{ p.name }}</option>{% endfor %}
</select></div>
<div class="col-md-4"><label class="form-label">Priority</label>
<select class="form-select" name="priority">{% for p in priorities %}
<option {{ "selected" if task.priority == p }}>{{ p }}</option>{% endfor %}</select></div>
<div class="col-md-4"><label class="form-label">Status</label>
<select class="form-select" name="status">{% for s in statuses %}
<option {{ "selected" if task.status == s }}>{{ s }}</option>{% endfor %}</select></div>
<div class="col-md-4"><label class="form-label">Start date</label>
<input class="form-control" type="date" name="start_date" value="{{ task.start_date or '' }}"></div>
<div class="col-md-4"><label class="form-label">Due date</label>
<input class="form-control" type="date" name="due_date" value="{{ task.due_date or '' }}"></div>
<div class="col-md-4"><label class="form-label">Estimated minutes</label>
<input class="form-control" type="number" min="0" name="estimated_minutes" value="{{ task.estimated_minutes or '' }}"></div>
<div class="col-md-4"><label class="form-label">Actual minutes</label>
<input class="form-control" type="number" min="0" name="actual_minutes" value="{{ task.actual_minutes or 0 }}"></div>
<div class="col-md-4"><label class="form-label">Waiting for</label>
<input class="form-control" name="waiting_for" value="{{ task.waiting_for or '' }}"></div>
</div>
<div class="mt-3"><label class="form-label">Notes</label>
<textarea class="form-control" name="notes" rows="2">{{ task.notes or '' }}</textarea></div>
<button class="btn btn-primary mt-3">Save task</button>
<a class="btn btn-light mt-3" href="{{ url_for('task_list') }}">Cancel</a>
{% if task.id %}
<button class="btn btn-outline-danger mt-3 float-end" form="delete-form">Delete</button>
{% endif %}
</form>
{% if task.id %}<form id="delete-form" method="post" action="{{ url_for('delete_task', task_id=task.id) }}">
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"></form>{% endif %}
</div>
"""


PROJECTS_PAGE = """
<div class="row g-3">
<div class="col-lg-5"><h1 class="h2">Projects</h1><div class="card p-4">
<h2 class="h5">Add a project</h2><form method="post">
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
<label class="form-label">Project name</label><input class="form-control mb-3" name="name" required>
<label class="form-label">Description</label><textarea class="form-control mb-3" name="description"></textarea>
<label class="form-label">Target date</label><input class="form-control mb-3" type="date" name="target_date">
<button class="btn btn-primary">Create project</button>
</form></div></div>
<div class="col-lg-7"><div class="card p-4 mt-5">
{% for p in projects %}
<div class="border-bottom py-3">
<div class="d-flex justify-content-between">
<div><strong>{{ p.name }}</strong><div class="muted">{{ p.description }}
{% if p.target_date %} · Target {{ p.target_date }}{% endif %}</div></div>
<form method="post" action="{{ url_for('delete_project', project_id=p.id) }}">
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
<button class="btn btn-sm btn-outline-danger">Delete</button></form>
</div>
{% set total = p.tasks|length %}
{% set done = p.tasks|selectattr("status", "equalto", "Completed")|list|length %}
<div class="progress mt-2" role="progressbar">
<div class="progress-bar" style="width: {{ (done * 100 / total)|round|int if total else 0 }}%"></div></div>
<small class="muted">{{ done }} of {{ total }} tasks completed</small>
</div>
{% else %}<p class="muted mb-0">No projects yet.</p>{% endfor %}
</div></div></div>
"""


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")



