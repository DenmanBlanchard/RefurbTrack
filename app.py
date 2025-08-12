import os
from datetime import datetime, date, timedelta
from flask import Flask, json, render_template, request, redirect, url_for, flash, send_file, abort
from models import db, Item, ActivityLog, User, Company
from forms import ItemForm
import qrcode
from io import BytesIO
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from functools import wraps

# --- Custom Decorators ---
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)  # Forbidden
            return f(*args, **kwargs)
        return wrapped
    return decorator

def require_company(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.company_id:
            flash("You must join or create a company to access this page.", "warning")
            return redirect(url_for("create_company"))
        return f(*args, **kwargs)
    return decorated_function

login_manager = LoginManager()
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)


UPLOAD_FOLDER = "uploads"
ALLOWED_EXT = {"png","jpg","jpeg","gif"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXT

def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///refurb.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "devsecret")
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))  # go to dashboard if logged in
        return render_template("index.html")  # public landing page


    @app.template_filter('dateiso')
    def dateiso(d):
        return d.isoformat() if d else ""
    
    @app.route("/create_company", methods=["GET", "POST"])
    @login_required
    @role_required("Admin")
    def create_company():
        if request.method == "POST":
            name = request.form.get("name").strip()

            if not name:
                flash("Company name is required.", "danger")
                return redirect(url_for("create_company"))

            # Create company
            company = Company(name=name)
            db.session.add(company)
            db.session.commit()

            # Assign this company to the current admin
            current_user.company_id = company.id
            db.session.commit()

            flash(f"Company '{name}' created with join code: {company.join_code}", "success")
            return redirect(url_for("dashboard"))

        return render_template("create_company.html")


    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            username = request.form.get("username")
            email = request.form.get("email")
            password = request.form.get("password")
            role = request.form.get("role")
            join_code = request.form.get("join_code", "").strip()

            company = None
            if join_code:
                company = Company.query.filter_by(join_code=join_code).first()
                if not company:
                    flash("Invalid join code.", "danger")
                    return redirect(url_for("signup"))
            elif role != "Admin":
                flash("Join code is required for non-admin accounts.", "danger")
                return redirect(url_for("signup"))

            user = User(username=username, email=email, role=role)
            user.set_password(password)
            if company:
                user.company_id = company.id
            elif role == "Admin":
                user.approved = True  # Admins are auto-approved

            db.session.add(user)
            db.session.commit()

            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))

        return render_template("signup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form["email"]
            password = request.form["password"]
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                if not user.approved:
                    flash("Your account is pending admin approval.", "warning")
                    return redirect(url_for("login"))
                login_user(user)
                return redirect(url_for("dashboard"))
            flash("Invalid email or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("Logged out successfully.", "success")
        return redirect(url_for("login"))

    @app.route("/pending_users")
    @login_required
    @role_required("Admin")
    @require_company
    def pending_users():
        if current_user.role != "Admin":
            abort(403)
        pending = User.query.filter_by(company_id=current_user.company_id, approved=False).all()
        return render_template("pending_users.html", users=pending)

    @app.route("/approve_user/<user_id>", methods=["POST"])
    @login_required
    @role_required("Admin")
    @require_company
    def approve_user(user_id):
        if current_user.role != "Admin":
            abort(403)
        user = User.query.get_or_404(user_id)
        if user.company_id != current_user.company_id:
            abort(403)
        user.approved = True
        db.session.commit()
        flash(f"User {user.username} approved.", "success")
        return redirect(url_for("pending_users"))


    @app.route("/dashboard")
    @login_required
    @require_company
    def dashboard():
        # quick stats
        counts = {}
        for s in ["Received","Needs Repair","In Repair","Ready for Sale","Sold","Shipped"]:
            counts[s] = Item.query.filter_by(status=s).count()
        # upcoming shipments
        upcoming = Item.query.filter(Item.ship_by != None).filter(Item.ship_by >= date.today()).order_by(Item.ship_by).limit(10).all()
        return render_template("dashboard.html", counts=counts, upcoming=upcoming)

    @app.route("/items")
    @login_required
    @require_company
    def items():
        q = request.args.get("q", "")
        status = request.args.get("status", "")
        query = Item.query.filter_by(company_id=current_user.company_id)
        if q:
            query = query.filter((Item.model.contains(q)) | (Item.serial.contains(q)) | (Item.buyer_name.contains(q)))
        if status:
            query = query.filter_by(status=status)
        items = query.order_by(Item.created_at.desc()).limit(200).all()
        return render_template("list_views.html", items=items, q=q, status=status)
    
    @app.route("/items/compress_shipped", methods=["POST"])
    @login_required
    @require_company
    @role_required("Admin")
    def compress_shipped():
        cutoff = datetime.utcnow() - timedelta(days=30)
        old_shipped = Item.query.filter(Item.status=="Shipped", Item.updated_at <= cutoff).all()
        if not old_shipped:
            flash("No shipped items older than 30 days to compress.", "info")
            return redirect(url_for("items", status="Shipped"))

        os.makedirs("archives", exist_ok=True)
        data = [ {c.name: getattr(i, c.name) for c in i.__table__.columns} for i in old_shipped ]
        filename = f"archives/shipped_{datetime.utcnow().strftime('%Y%m%d')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, default=str, indent=2)

        for i in old_shipped:
            db.session.delete(i)
        db.session.commit()

        flash(f"Compressed {len(data)} shipped items to {filename}", "success")
        return redirect(url_for("items", status="Shipped"))


    @app.route("/item/add", methods=["GET","POST"])
    @login_required
    @require_company
    def add_item():
        form = ItemForm()
        if form.validate_on_submit():
            photo_filename = None
            if 'photo' in request.files:
                f = request.files['photo']
                if f and allowed_file(f.filename):
                    filename = secure_filename(f.filename)
                    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                    filename = f"{ts}_{filename}"
                    f.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                    photo_filename = filename
            item = Item(
                model=form.model.data,
                serial=form.serial.data,
                notes=form.notes.data,
                status=form.status.data,
                location=form.location.data,
                buyer_name=form.buyer_name.data,
                buyer_order=form.buyer_order.data,
                ship_by=form.ship_by.data,
                photo_filename=photo_filename,
                specs_url=form.specs_url.data,
                company_id=current_user.company_id
            )
            db.session.add(item)
            db.session.commit()
            log = ActivityLog(item_id=item.id, actor="system", action="Created item")
            db.session.add(log)
            db.session.commit()
            flash("Item created", "success")
            return redirect(url_for("view_item", item_id=item.id))
        return render_template("add_item.html", form=form)

    @app.route("/item/<item_id>", methods=["GET", "POST"])
    @login_required
    @require_company
    def view_item(item_id):
        item = Item.query.get_or_404(item_id)
        if item.company_id != current_user.company_id:
            abort(403)

        if request.method == "POST":
            new_status = request.form.get("status")
            ship_by = request.form.get("ship_by")
            address = request.form.get("buyer_address")

            if new_status:
                if new_status == "Sold":
                    if not ship_by or not address:
                        return "ERROR: Ship By date and Buyer Address are required when marking as Sold.", 400
                    item.ship_by = datetime.strptime(ship_by, "%Y-%m-%d").date()
                    item.buyer_address = address

                old_status = item.status
                item.status = new_status
                log = ActivityLog(item_id=item.id, actor="system",
                                action=f"Status changed {old_status} → {new_status}")
                db.session.add(log)
                db.session.commit()
                return "", 204  # No page reload needed for JS

        logs = item.logs.order_by(ActivityLog.timestamp.desc()).limit(50).all()
        qr_url = url_for('qr', item_id=item.id)
        return render_template("view_item.html", item=item, logs=logs, qr_url=qr_url)
        # QR code URL for item
    @app.route("/item/<item_id>/qr")
    @login_required
    @require_company
    def qr(item_id):
        # generate QR code that points to item page (assumes accessible)
        item = Item.query.get_or_404(item_id)
        # base URL
        base = request.url_root.rstrip("/")
        url = f"{base}{url_for('view_item', item_id=item.id)}"
        img = qrcode.make(url)
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png", download_name=f"{item.id}.png")
    
    @app.route("/item/<item_id>/delete", methods=["POST"])
    @login_required
    @require_company
    @role_required("Admin")
    def delete_item(item_id):
        item = Item.query.get_or_404(item_id)

        # Check if the confirmation name matches
        confirm_name = request.form.get("confirm_name", "").strip()
        if confirm_name != item.model:
            flash("Item name does not match. Deletion cancelled.", "danger")
            return redirect(url_for("view_item", item_id=item.id))

        db.session.delete(item)
        db.session.commit()
        flash(f"Item '{item.model}' has been deleted.", "success")
        return redirect(url_for("items"))

    @app.route("/item/<item_id>/edit", methods=["GET","POST"])
    def edit_item(item_id):
        item = Item.query.get_or_404(item_id)
        form = ItemForm(obj=item)
        if form.validate_on_submit():
            old_status = item.status
            form.populate_obj(item)
            # photo upload
            if 'photo' in request.files:
                f = request.files['photo']
                if f and allowed_file(f.filename):
                    filename = secure_filename(f.filename)
                    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                    filename = f"{ts}_{filename}"
                    f.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                    item.photo_filename = filename
            db.session.commit()
            # log change
            if old_status != item.status:
                action = f"Status changed {old_status} → {item.status}"
            else:
                action = "Item updated"
            log = ActivityLog(item_id=item.id, actor="system", action=action)
            db.session.add(log)
            db.session.commit()
            flash("Item updated", "success")
            return redirect(url_for("view_item", item_id=item.id))
        return render_template("edit_item.html", form=form, item=item)

    @app.route("/item/<item_id>/log", methods=["POST"])
    @login_required
    @require_company
    def add_log(item_id):
        item = Item.query.get_or_404(item_id)
        actor = request.form.get("actor","unknown")
        action = request.form.get("action","")
        if action:
            log = ActivityLog(item_id=item.id, actor=actor, action=action)
            db.session.add(log)
            db.session.commit()
            flash("Logged action", "success")
        return redirect(url_for("view_item", item_id=item.id))
    
    @app.route("/company_info")
    @login_required
    @require_company
    @role_required("Admin")
    def company_info():
        company = Company.query.get(current_user.company_id)
        if not company:
            flash("Company not found.", "danger")
            return redirect(url_for("dashboard"))
        return render_template("company_info.html", company=company, user=current_user)

    @app.route("/uploads/<filename>")
    @login_required
    @require_company
    def uploaded_file(filename):
        return send_file(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)
