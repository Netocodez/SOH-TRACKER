import pandas as pd
from app import app, db
from models import Product  # make sure your Product model is imported

# Path to your products Excel file
PRODUCTS_FILE = "products.xlsx"

with app.app_context():
    # Read the products Excel file
    df_prod = pd.read_excel(PRODUCTS_FILE)

    if "Product" not in df_prod.columns:
        print("Error: 'Product' column not found in products.xlsx")
    else:
        product_names = df_prod["Product"].dropna().unique()

        for prod_name in product_names:
            # Check if product already exists
            existing_product = Product.query.filter_by(name=prod_name).first()
            if not existing_product:
                new_product = Product(name=prod_name, unit="Units")  # change unit if needed
                db.session.add(new_product)
                print(f"Added product: {prod_name}")
        db.session.commit()

    print("Product seeding complete!")
