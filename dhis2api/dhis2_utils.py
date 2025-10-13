import os
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from models import db, Facility

# Paths
EXPORT_DIR = "dhis2downloads"
METADATA_CACHE_FILE = os.path.join(EXPORT_DIR, "metadata_cache.json")


def generate_date_param(start_date, end_date):
    """Generate semicolon-separated date list for DHIS2 analytics API."""
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    date_list = [
        (start_date + timedelta(days=i)).strftime("%Y%m%d")
        for i in range((end_date - start_date).days + 1)
    ]
    return ";".join(date_list)


def fetch_orgunitids_from_db():
    """Fetch all distinct orgunit IDs from Facility table."""
    facilities = (
        db.session.query(Facility.newdpt_orgunitid)
        .filter(Facility.newdpt_orgunitid.isnot(None))
        .distinct()
        .all()
    )
    return [f[0].strip() for f in facilities if f[0]]


def load_cached_metadata():
    """Load cached DHIS2 metadata if available."""
    if os.path.exists(METADATA_CACHE_FILE):
        try:
            with open(METADATA_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_metadata_cache(metadata_items):
    """Save metadata to cache for reuse."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    try:
        with open(METADATA_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(metadata_items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to save metadata cache: {e}")


def fetch_dhis2_data(start_date, end_date):
    """Fetch DHIS2 analytics data, enrich with metadata, and save as CSV (with caching)."""
    base_url = "https://dhis-hfr.ahnigeria.org/api/analytics.json"
    username = os.getenv("DHIS2_USERNAME", "PUzondu")
    password = os.getenv("DHIS2_PASSWORD", "Password@1")

    date_param = generate_date_param(start_date, end_date)
    org_units = fetch_orgunitids_from_db()
    ou_param = ";".join(org_units) if org_units else "USER_ORGUNIT_GRANDCHILDREN"

    print(f"Fetching DHIS2 data for {len(org_units)} org units...")

    params = {
        "dimension": [
            "dx:A3eiT7MRcS8;EN7EVuCjiKQ;rhYlSSECY4l;cwKfS7NnJtO;w2VWBiX0AGs;"
            "kSr5Ji1hWcR;hLcOesWK2Rp;MFDtCt48Osx;D8saCxBmZ4E;XhznPWwUtZ9;"
            "Rij59JNReZQ;Kg2HWFUxoi1;pLIUMhHJRNd;dLV7YVv1V6F;f08DZFl7DBg;"
            "Tz43EVMVeaf;l9jK86N01Xv;iEpkmNeEMH3;rq0KbK4H649;wyDg2Sy7KuC;"
            "WfaVp1GTXWm;MXx056eFOiO;U7oTzvzWk4t;beewUdGdQuT;GSQBiRSxvWp;"
            "cdsihyrRJXI;Rwl007WlsiJ;t9sqNZCP1ZH;TwgBpgBB5K1",
            f"pe:{date_param}",
            f"ou:{ou_param}",
        ],
        "includeMetadataDetails": "true",
        "hierarchyMeta": "false",
        "showHierarchy": "false",
        "includeNumDen": "false",
        "skipRounding": "false",
        "completedOnly": "false",
        "outputIdScheme": "UID",
    }

    try:
        response = requests.get(base_url, params=params, auth=(username, password))
        response.raise_for_status()
        data = response.json()

        # ✅ Convert to DataFrame
        headers = [h["name"] for h in data.get("headers", [])]
        rows = data.get("rows", [])
        df = pd.DataFrame(rows, columns=headers)

        # ✅ Load or update metadata cache
        cached_meta = load_cached_metadata()
        fresh_meta = data.get("metaData", {}).get("items", {})

        # merge new metadata with cache
        if fresh_meta:
            cached_meta.update(fresh_meta)
            save_metadata_cache(cached_meta)

        meta_lookup = {k: v.get("name", k) for k, v in cached_meta.items()}

        # --- Enrich DataFrame with names and drop irrelevant ID columns except 'ou' ---
        for col in ["dx", "pe"]:
            if col in df.columns:
                df[f"{col}_name"] = df[col].map(meta_lookup)
                df.drop(columns=[col], inplace=True)  # drop original ID column

        # 'ou' is kept as ID, but we also add readable name
        if "ou" in df.columns:
            df["ou_name"] = df["ou"].map(meta_lookup)

        # ✅ Save to CSV
        os.makedirs(EXPORT_DIR, exist_ok=True)
        csv_filename = f"dhis2_data_{start_date}_to_{end_date}.csv"
        csv_path = os.path.join(EXPORT_DIR, csv_filename)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        print(f"Data saved to {csv_path} ({len(df)} rows)")
        return {
            "status": "success",
            "csv_file": csv_path,
            "rows": len(df),
            "columns": list(df.columns),
            "metadata_cached": len(cached_meta),
        }

    except requests.exceptions.RequestException as e:
        print(f"DHIS2 API request failed: {e}")
        return {"status": "error", "message": str(e)}


def load_dhis2_csv_to_df(csv_file=None, start_date=None, end_date=None):
    """
    Load DHIS2 CSV to a DataFrame.
    If csv_file is None, generates path based on start/end date.
    """
    if csv_file is None:
        if start_date is None or end_date is None:
            raise ValueError("Either csv_file or start_date/end_date must be provided")
        csv_file = os.path.join(EXPORT_DIR, f"dhis2_data_{start_date}_to_{end_date}.csv")
    
    if not os.path.exists(csv_file):
        raise FileNotFoundError(f"CSV file not found: {csv_file}")
    
    df = pd.read_csv(csv_file, encoding="utf-8-sig")
    return df

def aggregate_dhis2_data(df):
    """
    Aggregate DHIS2 data by pe_name (date), ou, and ou_name,
    applying conditional sums for different HIV testing indicators.
    """

    if df.empty:
        return pd.DataFrame()

    # Ensure 'value' column exists
    if "value" not in df.columns:
        raise ValueError("DataFrame must include 'value' column.")

    # Convert value to numeric
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0)

    # -------------------------
    # Conditional columns
    # -------------------------
    df['HTS3e'] = np.where(
        df['dx_name'].isin([
            'GF_Number of Clients Screened and Tested for HIVÂ  (Rat) - OPD',
            'GF_Number of Individuals Who Received HIV Testing Services (Hts) And Received Their Test Results - CT',
            'GF_Number of Individuals Who Received HIV Testing Services (HTS) And Received Their Test Results - Accident And Emergency',
            'GF_Number of Individuals Who Received HIV Testing Services (HTS) And Received Their Test Results - In-Patient',
            'GF_Number of Individuals Who Received HIV Testing Services (HTS) And Received Their Test Results - Peadiatrics Clinic',
            'GF_Number of Individuals Who Received HIV Testing Services (HTS) And Received Their Test Results - Blood Bank',
            'GF_Number of Individuals Who Received HIV Testing Services (HTS) And Received Their Test Results - STI',
            'GF_Number of Individuals Who Received HIV Testing Services (Hts) And Received Their Test Results - TB',
            'GF_Number of Individuals Who Received HIV Testing Services (HTS) and Received Their Test Results - Other PITC'
        ]),
        df['value'],
        0
    )

    df['HTS3e(Pos)'] = np.where(
        df['dx_name'].isin([
            'GF_Number of Clients tested HIV Positive (From Rat) - OPD',
            'GF_Number of People Tested HIV Positive & Received Results - CT',
            'GF_Number of People Tested HIV Positive & Received Results - Accident And Emergency',
            'GF_Number of People Tested HIV Positive & Received Results - In-Patient',
            'GF_Number of People Tested HIV Positive & Received Results - Peadiatrics Clinic',
            'GF_Number of People Tested HIV Positive & Received Results - Blood Bank',
            'GF_Number of People Tested HIV Positive & Received Results - STI',
            'GF_Number of People Tested HIV Positive & Received Results - TB',
            'GF_Number of People Tested HIV Positive & Received Results - Other PITC'
        ]),
        df['value'],
        0
    )

    df['VT1'] = np.where(
        df['dx_name'].isin([
            'GF_Number of Pregnant Women Who Received HIV Testing Services (Hts) And Received Their Test Results - ANC',
            'GF_Number of Pregnant Women Who Received HIV Testing Services (Hts) And Received Their Test Results - L&D',
            'GF_Number of Pregnant Women Tested Post Partum -PP'
        ]),
        df['value'],
        0
    )

    df['VT1(Pos)'] = np.where(
        df['dx_name'].isin([
            'GF_Number of People Tested HIV Positive & Received Results - ANC',
            'GF_Number of People Tested HIV Positive & Received Results - L&D'
        ]),
        df['value'],
        0
    )

    df['YP2'] = np.where(
        df['dx_name'].isin([
            'GF_Number of AGYW counseled tested and received result- Walk-In',
            'GF_Number of AGYW counseled tested and received result- Community'
        ]),
        df['value'],
        0
    )

    df['YP2(Pos)'] = np.where(
        df['dx_name'].isin([
            'GF_Number of AGYW tested HIV positive and received result- Walk-In',
            'GF_Number of AGYW tested HIV positive and received result- Community'
        ]),
        df['value'],
        0
    )

    df['KP_CTRR'] = np.where(
        df['dx_name'].isin([
            'GF_Number of KPs counseled tested and received result'
        ]),
        df['value'],
        0
    )

    df['KP_CTRR(Pos)'] = np.where(
        df['dx_name'].isin([
            'GF_Number of KPs tested HIV positive and received result'
        ]),
        df['value'],
        0
    )

    # -------------------------
    # Group by period, org unit
    # -------------------------
    agg_cols = ['HTS3e', 'HTS3e(Pos)', 'VT1', 'VT1(Pos)', 'YP2', 'YP2(Pos)', 'KP_CTRR', 'KP_CTRR(Pos)']
    df_agg = df.groupby(['pe_name', 'ou', 'ou_name'], as_index=False)[agg_cols].sum()
    df_agg[agg_cols] = df_agg[agg_cols].fillna(0)
    df_agg = df_agg.loc[(df_agg[agg_cols] != 0).any(axis=1)]
    
    # Add a total column summing all agg indicators
    # -------------------------
    #df_agg['Total CTRR (Including Confirmatory Test)'] = df_agg[agg_cols].sum(axis=1)
    
    # ✅ Save to CSV
    os.makedirs(EXPORT_DIR, exist_ok=True)
    csv_filename = f"agg_dhis2_data.csv"
    csv_path = os.path.join(EXPORT_DIR, csv_filename)
    df_agg.to_csv(csv_path, index=False, encoding="utf-8-sig")

    return df_agg