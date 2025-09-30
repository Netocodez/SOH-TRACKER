from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from . import auth_bp
from models import db, User, Cluster, LGA, Facility

# login
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if not user.active:
                flash('Your account has been disabled. Contact an admin.', 'danger')
                return redirect(url_for('auth.login'))
            login_user(user)
            flash('Logged in successfully', 'success')
            return redirect(url_for('dashboard.dashboard_home'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out', 'success')
    return redirect(url_for('auth.login'))

# Superuser user management
@auth_bp.route('/users')
@login_required
def list_users():
    if current_user.role != 'super':
        abort(403)
    users = User.query.all()
    return render_template('users.html', users=users)

@auth_bp.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if current_user.role != 'super':
        abort(403)

    clusters = Cluster.query.all()
    lgas = LGA.query.all()
    facilities = Facility.query.all()

    if request.method == 'POST':
        u = User(username=request.form['username'], role=request.form['role'])
        u.set_password(request.form['password'])
        u.cluster_id = request.form.get('cluster_id') or None
        u.lga_id = request.form.get('lga_id') or None
        u.facility_id = request.form.get('facility_id') or None
        db.session.add(u)
        db.session.commit()
        flash('User created', 'success')
        return redirect(url_for('auth.list_users'))

    return render_template('add_user.html', clusters=clusters, lgas=lgas, facilities=facilities)

@auth_bp.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if current_user.role != 'super':
        abort(403)

    user = User.query.get_or_404(user_id)
    clusters = Cluster.query.all()
    lgas = LGA.query.all()
    facilities = Facility.query.all()

    if request.method == 'POST':
        user.username = request.form['username']
        role = request.form['role']
        user.role = role

        # Only change password if provided
        if request.form.get('password'):
            user.password_hash = generate_password_hash(request.form['password'])

        # assign cluster/lga/facility IDs
        user.cluster_id = request.form.get('cluster_id') or None
        user.lga_id = request.form.get('lga_id') or None
        user.facility_id = request.form.get('facility_id') or None

        db.session.commit()
        flash('User updated successfully', 'success')
        return redirect(url_for('auth.list_users'))

    return render_template(
        'edit_user.html',
        user=user,
        clusters=clusters,
        lgas=lgas,
        facilities=facilities
    )

@auth_bp.route('/users/toggle/<int:user_id>')
@login_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    user.active = not user.active
    db.session.commit()
    flash(f"User {user.username} {'enabled' if user.active else 'disabled'}", "success")
    return redirect(url_for('auth.list_users'))  # adjust to your list view

@auth_bp.route('/users/delete/<int:user_id>')
@login_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.username} deleted", "danger")
    return redirect(url_for('auth.list_users'))


