import pandas as pd
from werkzeug.security import generate_password_hash

from app import app, db
from models import Cluster, LGA, Facility, Product, User  # import your User model

df = pd.read_excel("facilities.xlsx")

with app.app_context():
    # seed clusters, lgas, facilities
    for _, row in df.iterrows():
        cluster_name = row["Cluster"]
        lga_name = row["LGA"]
        facility_name = row["Facility"]

        cluster = Cluster.query.filter_by(name=cluster_name).first()
        if not cluster:
            cluster = Cluster(name=cluster_name)
            db.session.add(cluster)
            db.session.commit()

        lga = LGA.query.filter_by(name=lga_name, cluster_id=cluster.id).first()
        if not lga:
            lga = LGA(name=lga_name, cluster_id=cluster.id)
            db.session.add(lga)
            db.session.commit()

        facility = Facility.query.filter_by(name=facility_name, lga_id=lga.id).first()
        if not facility:
            facility = Facility(name=facility_name, lga_id=lga.id)
            db.session.add(facility)
            db.session.commit()

    # optional: add some products
    products = ["ARV", "TPT", "Test Kit"]
    for prod_name in products:
        if not Product.query.filter_by(name=prod_name).first():
            db.session.add(Product(name=prod_name, unit="Units"))
    db.session.commit()

    # seed superuser if not exists
    super_username = "admin"
    super_password = "admin123"  # change this in production!
    existing_super = User.query.filter_by(username=super_username).first()
    if not existing_super:
        super_user = User(
            username=super_username,
            password_hash=generate_password_hash(super_password),
            role="super"  # or whatever your roles are
        )
        db.session.add(super_user)
        db.session.commit()
        print(f"Superuser '{super_username}' created with password '{super_password}'")
    else:
        print("Superuser already exists")

print("Seeding complete!")
