from flask import Blueprint

# Blueprint for DHIS2 API integration
dhis2api_bp = Blueprint('dhis2api', __name__, url_prefix='/dhis2')

from . import routes  # Import routes after defining blueprint
