from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, FileField, DateField
from wtforms.validators import DataRequired, Optional

STATUSES = [
    ("Received", "Received"),
    ("Needs Repair", "Needs Repair"),
    ("In Repair", "In Repair"),
    ("Ready for Sale", "Ready for Sale"),
    ("Sold", "Sold"),
    ("Shipped", "Shipped"),
]

class ItemForm(FlaskForm):
    model = StringField("Model", validators=[DataRequired()])
    serial = StringField("Serial #", validators=[Optional()])
    notes = TextAreaField("Notes", validators=[Optional()])
    status = SelectField("Status", choices=STATUSES)
    location = StringField("Location (shelf/bin/tech)", validators=[Optional()])
    photo = FileField("Photo (optional)")
    buyer_name = StringField("Buyer Name", validators=[Optional()])
    buyer_order = StringField("Buyer Order #", validators=[Optional()])
    ship_by = DateField("Ship By", validators=[Optional()], format="%Y-%m-%d")
    specs_url = StringField("Specs URL", validators=[Optional()])

