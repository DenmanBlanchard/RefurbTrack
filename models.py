from datetime import datetime
import uuid
from flask_sqlalchemy import SQLAlchemy
import secrets
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import random
import string

def gen_uuid():
    return str(uuid.uuid4())

db = SQLAlchemy()

class Company(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(120), nullable=False, unique=True)
    join_code = db.Column(db.String(12), unique=True, nullable=False, default=lambda: secrets.token_hex(6).upper())
    users = db.relationship("User", backref="company", lazy=True)
    items = db.relationship("Item", backref="company", lazy=True)

    @staticmethod
    def generate_join_code():
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

class User(UserMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="Stocker")  # Admin, Stocker, Repair-Tech
    approved = db.Column(db.Boolean, default=False)

    company_id = db.Column(db.String(36), db.ForeignKey("company.id"), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)



def gen_uuid():
    return str(uuid.uuid4())

class Item(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    model = db.Column(db.String(120), nullable=False)
    serial = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False, default="Received")
    location = db.Column(db.String(120), nullable=True)
    buyer_name = db.Column(db.String(120), nullable=True)
    buyer_order = db.Column(db.String(120), nullable=True)
    ship_by = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    photo_filename = db.Column(db.String(256), nullable=True)
    buyer_address = db.Column(db.Text, nullable=True)
    specs_url = db.Column(db.String(500), nullable=True)
    company_id = db.Column(db.String(36), db.ForeignKey("company.id"), nullable=False)

    logs = db.relationship('ActivityLog', backref='item', cascade="all, delete-orphan", lazy='dynamic')

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.String(36), db.ForeignKey('item.id'), nullable=False)
    actor = db.Column(db.String(120), nullable=True)
    action = db.Column(db.String(256), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
