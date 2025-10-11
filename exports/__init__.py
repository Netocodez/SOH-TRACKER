from flask import Blueprint

export_bp = Blueprint('exports', __name__, template_folder='templates')

from . import routes
