import pandas as pd
from .db_utils import fetch_facility_hierarchy

def merge_db_and_dhis2(db_data, dhis_df):
    """
    Merge DB 'Used' stock data with DHIS2 aggregated indicators.
    - Fills missing facility, LGA, and cluster info from DB
    - Computes total DHIS2 indicators
    - Ensures numeric columns are correct
    - Adds a comparison column: total_used - total_dhis2
    """

    if not db_data:
        return pd.DataFrame()

    # Convert DB list of dicts to DataFrame
    db_df = pd.DataFrame(db_data)

    # Ensure 'orgunitid' exists
    if 'orgunitid' not in db_df.columns:
        raise KeyError("'orgunitid' missing from DB data")

    # Merge DB and DHIS2 on orgunitid/date
    merged = pd.merge(
        db_df,
        dhis_df,
        left_on=['orgunitid', 'date'],
        right_on=['ou', 'pe_name'],
        how='outer',
        suffixes=('_db', '_dhis')
    )
    
    # Ensure orgunitid is filled from either DB or DHIS2
    merged['orgunitid'] = merged['orgunitid'].combine_first(merged['ou'])
    merged['date'] = merged['date'].combine_first(merged['pe_name'])
    
    # Drop DHIS2 merge columns that are no longer needed
    merged.drop(columns=['pe_name', 'ou', 'ou_name'], inplace=True)

    # -----------------------
    # Fill missing facility/LGA/cluster info from DB
    # -----------------------
    hierarchy_df = fetch_facility_hierarchy()
    merged = pd.merge(
        merged,
        hierarchy_df,
        on='orgunitid',
        how='left',
        suffixes=('', '_hierarchy')
    )
    
    #merged.to_excel("merged_debug.xlsx", index=False)  # Debug output

    # Fill missing columns from hierarchy
    for col in ['facility_id', 'facility_name', 'lga_id', 'lga_name', 'cluster_id', 'cluster_name']:
        merged[col] = merged[col].combine_first(merged.get(f"{col}_hierarchy"))
        merged.drop(columns=[f"{col}_hierarchy"], inplace=True, errors='ignore')

    # -----------------------
    # Compute total DHIS2 indicators
    # -----------------------
    dhis_cols = ['HTS3e', 'HTS3e(Pos)', 'VT1', 'VT1(Pos)', 'YP2', 'YP2(Pos)', 'KP_CTRR', 'KP_CTRR(Pos)']
    dhis_cols_existing = [c for c in dhis_cols if c in merged.columns]

    if dhis_cols_existing:
        merged[dhis_cols_existing] = merged[dhis_cols_existing].apply(pd.to_numeric, errors='coerce').fillna(0)
        merged['total_dhis2'] = merged[dhis_cols_existing].sum(axis=1)
    else:
        merged['total_dhis2'] = 0

    # -----------------------
    # Ensure DB total_used is numeric
    # -----------------------
    if 'total_used' in merged.columns:
        merged['total_used'] = pd.to_numeric(merged['total_used'], errors='coerce').fillna(0)
    else:
        merged['total_used'] = 0

    # -----------------------
    # Comparison column
    # -----------------------
    merged['tested_comparison'] = merged['total_used'] - merged['total_dhis2']
    merged = merged[['date','cluster_name','lga_name','facility_name','HTS3e','HTS3e(Pos)','VT1','VT1(Pos)','YP2','YP2(Pos)','KP_CTRR', 'KP_CTRR(Pos)','total_dhis2','total_used','tested_comparison']]
    
    merged.rename(columns={
        'date': 'Date',
        'cluster_name': 'Cluster',
        'lga_name': 'LGA',
        'facility_name': 'Facility',
        'total_dhis2': 'TOTAL TESTING REPORTED ON NEW DPT',
        'total_used': 'TOTAL KITS USAGE REPORTED IN SOH TRACKER',
        'tested_comparison': 'Difference (Used - DHIS2)'
    }, inplace=True)

    return merged
