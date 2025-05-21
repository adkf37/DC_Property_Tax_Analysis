from flask import Flask, render_template, request, jsonify, send_file, session
import geopandas
import pandas as pd
from shapely.geometry import shape
from shapely.ops import union_all # union_all is preferred over unary_union for a list of geometries
import folium
from folium.plugins import Draw
import io
import os
import gdown
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.secret_key = os.urandom(24) # Required for session management

# --- Global variable for the final merged and processed data ---
merged_gdf = None
logging.info("Script started. Flask app initializing...")

# --- Data Loading and Preprocessing ---
DATA_FILES = {
    "parcels": {
        "path": "ITSPE_View_Parcels_Under_Jurisdiction_Of_ITS_Prior_To_Transferring_To_DOES_Or_DGS.csv",
        "id": "17534kvrP65GCPqMfMbbRsShJTedfHM_G"
    },
    "address": {
        "path": "Address_Points.csv",
        "id": "1Cx8BQPGMis_8HLT2AteQ-5HQV-r1FOGZ"
    }
    # Removed "tax_parcels" as it's not used
}

def download_if_needed(file_info):
    """Downloads a file from Google Drive if it doesn't exist locally."""
    if not os.path.exists(file_info["path"]):
        logging.info(f"Downloading {file_info['path']} from Google Drive...")
        # Construct the direct download URL for Google Drive
        url = f"https://drive.google.com/uc?export=download&id={file_info['id']}"
        try:
            gdown.download(url, file_info["path"], quiet=False, fuzzy=True) # Added fuzzy=True for robustness
            logging.info(f"Finished downloading {file_info['path']}.")
        except Exception as e:
            logging.error(f"Error downloading {file_info['path']} from Google Drive (ID: {file_info['id']}): {e}")
            raise
    else:
        logging.info(f"{file_info['path']} already exists locally.")

def load_all_data():
    global merged_gdf # Declare that we are modifying the global variable

    # Download data files at startup if they don't exist
    for key, file_info in DATA_FILES.items():
        # Removed check for placeholder ID for tax_parcels as it's no longer in DATA_FILES
        try:
            download_if_needed(file_info)
        except Exception as e:
            logging.critical(f"Failed to download essential data file {file_info['path']}. Application might not work correctly. Error: {e}")

    # --- Load Parcel Data (ITSPE View) ---
    parcels_data_path = DATA_FILES["parcels"]["path"]
    current_parcels_gdf = None
    if os.path.exists(parcels_data_path):
        try:
            logging.info(f"Loading parcel data from {parcels_data_path}...")
            current_parcels_gdf = geopandas.read_file(parcels_data_path, dtype={'SSL': str}, low_memory=False)
            logging.info(f"Parcel data loaded. Shape: {current_parcels_gdf.shape}, Initial CRS: {current_parcels_gdf.crs}")
            
            # Validate geometries and set CRS
            current_parcels_gdf = current_parcels_gdf[current_parcels_gdf.is_valid & ~current_parcels_gdf.is_empty]
            if current_parcels_gdf.crs is None:
                logging.warning("Parcels GDF has no CRS, setting to EPSG:4326")
                current_parcels_gdf = current_parcels_gdf.set_crs("EPSG:4326", allow_override=True)
            elif current_parcels_gdf.crs.to_string().upper() != "EPSG:4326":
                logging.info(f"Reprojecting parcels_gdf from {current_parcels_gdf.crs} to EPSG:4326")
                current_parcels_gdf = current_parcels_gdf.to_crs("EPSG:4326")

            # Derive ASSESSED_VALUE_TAX from the parcels data itself
            if 'NEWTOTAL' in current_parcels_gdf.columns:
                logging.info("Using 'NEWTOTAL' column from parcels data for assessed value.")
                current_parcels_gdf['ASSESSED_VALUE_TAX'] = pd.to_numeric(current_parcels_gdf['NEWTOTAL'], errors='coerce').fillna(0)
            elif 'ASSESSMENT' in current_parcels_gdf.columns: # Fallback to 'ASSESSMENT'
                logging.info("Using 'ASSESSMENT' column from parcels data for assessed value.")
                current_parcels_gdf['ASSESSED_VALUE_TAX'] = pd.to_numeric(current_parcels_gdf['ASSESSMENT'], errors='coerce').fillna(0)
            else:
                logging.warning("'NEWTOTAL' or 'ASSESSMENT' column not found in parcels data. 'ASSESSED_VALUE_TAX' will be initialized to 0.")
                current_parcels_gdf['ASSESSED_VALUE_TAX'] = 0 # Ensure the column exists

            logging.info(f"Parcel data processed. Shape: {current_parcels_gdf.shape}, CRS: {current_parcels_gdf.crs}. Columns: {current_parcels_gdf.columns.tolist()}")

        except Exception as e:
            logging.error(f"Error loading or processing parcel data from {parcels_data_path}: {e}")
            current_parcels_gdf = geopandas.GeoDataFrame(columns=['SSL', 'geometry', 'ASSESSED_VALUE_TAX'], crs="EPSG:4326")
            current_parcels_gdf['ASSESSED_VALUE_TAX'] = 0 # Ensure column exists in empty GDF
    else:
        logging.error(f"Parcel data file {parcels_data_path} not found. Skipping loading.")
        current_parcels_gdf = geopandas.GeoDataFrame(columns=['SSL', 'geometry', 'ASSESSED_VALUE_TAX'], crs="EPSG:4326")
        current_parcels_gdf['ASSESSED_VALUE_TAX'] = 0 # Ensure column exists

    # --- Load Address Data ---
    address_data_path = DATA_FILES["address"]["path"]
    address_df = None
    if os.path.exists(address_data_path):
        try:
            logging.info(f"Loading address data from {address_data_path}...")
            address_df = pd.read_csv(address_data_path, dtype={'SSL': str}, low_memory=False)
            # Select only necessary columns and drop duplicates by SSL, keeping the first occurrence
            if 'SSL' in address_df.columns and 'FULLADDRESS' in address_df.columns:
                 address_df = address_df[['SSL', 'FULLADDRESS']].drop_duplicates(subset=['SSL'], keep='first')
            else:
                logging.warning("Address data missing SSL or FULLADDRESS columns.")
                address_df = pd.DataFrame(columns=['SSL', 'FULLADDRESS'])
            logging.info(f"Address data loaded and processed. Shape: {address_df.shape}")
        except Exception as e:
            logging.error(f"Error loading address data from {address_data_path}: {e}")
            address_df = pd.DataFrame(columns=['SSL', 'FULLADDRESS'])
    else:
        logging.error(f"Address data file {address_data_path} not found. Skipping loading.")
        address_df = pd.DataFrame(columns=['SSL', 'FULLADDRESS'])

    # --- Load Tax Data ---
    # This section is now removed as we are not using a separate tax file.
    # tax_data_path = DATA_FILES["tax_parcels"]["path"] 
    # tax_df = None
    # if DATA_FILES["tax_parcels"]["id"] == "YOUR_TAX_PARCELS_FILE_ID_HERE":
    #     logging.warning(f"Tax parcel data file ID is a placeholder. Tax data will be empty.")
    #     tax_df = pd.DataFrame(columns=['SSL', 'ASSESSED_VALUE_TAX'])
    # elif os.path.exists(tax_data_path):
    #     try:
    #         logging.info(f"Loading tax data from {tax_data_path}...")
    #         tax_df = pd.read_csv(tax_data_path, dtype={'SSL': str}, low_memory=False)
    #         if 'SSL' in tax_df.columns and 'ASSESSMENT' in tax_df.columns:
    #             tax_df = tax_df[['SSL', 'ASSESSMENT']].rename(columns={'ASSESSMENT': 'ASSESSED_VALUE_TAX'})
    #             # Ensure ASSESSED_VALUE_TAX is numeric, coercing errors
    #             tax_df['ASSESSED_VALUE_TAX'] = pd.to_numeric(tax_df['ASSESSED_VALUE_TAX'], errors='coerce')
    #         else:
    #             logging.warning("Tax data missing SSL or ASSESSMENT columns.")
    #             tax_df = pd.DataFrame(columns=['SSL', 'ASSESSED_VALUE_TAX'])
    #         logging.info(f"Tax data loaded and processed. Shape: {tax_df.shape}")
    #     except Exception as e:
    #         logging.error(f"Error loading tax data from {tax_data_path}: {e}")
    #         tax_df = pd.DataFrame(columns=['SSL', 'ASSESSED_VALUE_TAX'])
    # else:
    #    logging.error(f"Tax data file {tax_data_path} not found. Skipping loading.")
    #    tax_df = pd.DataFrame(columns=['SSL', 'ASSESSED_VALUE_TAX'])


    # --- Merge DataFrames ---
    logging.info("Merging dataframes...")
    # Start with parcel data (which now includes ASSESSED_VALUE_TAX if NEWTOTAL/ASSESSMENT was found)
    temp_merged_gdf = current_parcels_gdf.copy()

    # Merge with address data
    if not address_df.empty and 'SSL' in address_df.columns:
        temp_merged_gdf = temp_merged_gdf.merge(address_df, on='SSL', how='left')
        logging.info(f"Shape after merging with address_df: {temp_merged_gdf.shape}")
    else:
        logging.warning("Address data is empty or missing SSL column. Skipping merge with address data.")
        if 'FULLADDRESS' not in temp_merged_gdf.columns: # Ensure column exists even if no merge
            temp_merged_gdf['FULLADDRESS'] = pd.NA

    # Merge with tax data - This section is removed as tax_df is no longer loaded separately.
    # if not tax_df.empty and 'SSL' in tax_df.columns:
    #     temp_merged_gdf = temp_merged_gdf.merge(tax_df, on='SSL', how='left')
    #     logging.info(f"Shape after merging with tax_df: {temp_merged_gdf.shape}")
    # else:
    #     logging.warning("Tax data is empty or missing SSL column. Skipping merge with tax data.")
    #     if 'ASSESSED_VALUE_TAX' not in temp_merged_gdf.columns: # Ensure column exists
    #         temp_merged_gdf['ASSESSED_VALUE_TAX'] = pd.NA


    # Final processing for ASSESSED_VALUE_TAX (ensuring it's numeric and 0 if NA)
    # This is important as it might not have been set if NEWTOTAL/ASSESSMENT wasn't in parcels_gdf
    # or if it was set from parcels_gdf but had issues.
    if 'ASSESSED_VALUE_TAX' in temp_merged_gdf.columns:
        temp_merged_gdf['ASSESSED_VALUE_TAX'] = pd.to_numeric(temp_merged_gdf['ASSESSED_VALUE_TAX'], errors='coerce').fillna(0)
    else:
        logging.warning("'ASSESSED_VALUE_TAX' column was not found or created from parcels data. Initializing to 0.")
        temp_merged_gdf['ASSESSED_VALUE_TAX'] = 0
        
    # Assign to the global merged_gdf
    merged_gdf = temp_merged_gdf

    if merged_gdf.empty:
        logging.error("CRITICAL: Merged GeoDataFrame is empty. The application will not have data to display or process.")
    else:
        logging.info(f"Final merged_gdf. Shape: {merged_gdf.shape}, CRS: {merged_gdf.crs}. Columns: {merged_gdf.columns.tolist()}")
        # Ensure geometry is valid and CRS is set one last time
        merged_gdf = merged_gdf[merged_gdf.is_valid & ~merged_gdf.is_empty]
        if merged_gdf.crs is None:
            merged_gdf = merged_gdf.set_crs("EPSG:4326", allow_override=True)
        elif merged_gdf.crs.to_string().upper() != "EPSG:4326":
            merged_gdf = merged_gdf.to_crs("EPSG:4326")
        logging.info(f"Final merged_gdf after validation. Shape: {merged_gdf.shape}, CRS: {merged_gdf.crs}")

    logging.info("Data loading and preprocessing complete.")

# Load data at application startup
logging.info("Attempting to load all data at application startup...")
load_all_data()
if merged_gdf is None or merged_gdf.empty:
    logging.critical("FATAL: Data loading failed or resulted in empty GeoDataFrame at startup. Application may not function correctly.")
else:
    logging.info("Data loaded successfully at startup.")


@app.route('/')
def index():
    global merged_gdf # Ensure we are using the globally loaded and processed GDF
    if merged_gdf is None or merged_gdf.empty:
        logging.error("merged_gdf is not available for the index route.")
        # Attempt to reload data if it's missing, as a fallback.
        # This might be redundant if startup loading is robust.
        logging.info("Attempting to reload data for index route...")
        load_all_data()
        if merged_gdf is None or merged_gdf.empty:
            return "Error: Parcel data could not be loaded or is empty. Please check server logs.", 500

    # Calculate map center
    # Check if 'geometry' column exists and is not empty before trying to access .union_all()
    if 'geometry' in merged_gdf.columns and not merged_gdf['geometry'].empty and merged_gdf.geom_type.is_valid.all():
        try:
            # Filter out any invalid geometries before union_all
            valid_geometries = merged_gdf[merged_gdf.is_valid]
            if not valid_geometries.empty:
                 # union_all() expects a list/array of geometries
                map_center_geom = union_all(valid_geometries['geometry'].tolist())
                map_center = [map_center_geom.centroid.y, map_center_geom.centroid.x]
            else: # Fallback if no valid geometries
                logging.warning("No valid geometries in merged_gdf for map centering, using default.")
                map_center = [38.9072, -77.0369] # Default to DC center
        except Exception as e:
            logging.error(f"Error calculating map center from merged_gdf: {e}. Using default.")
            map_center = [38.9072, -77.0369] # Default to DC center
    else:
        logging.warning("merged_gdf is empty, missing 'geometry' column, or contains invalid geometries for map centering. Using default.")
        map_center = [38.9072, -77.0369] # Default to DC center
        
    m = folium.Map(location=map_center, zoom_start=12, tiles="CartoDB positron")
    draw = Draw(
        export=False,
        filename='drawn_boundary.geojson',
        position='topleft',
        draw_options={'polyline': False, 'marker': False, 'circlemarker': False, 'circle': False, 'rectangle': True, 'polygon': True},
        edit_options={'edit': False, 'remove': True}
    )
    m.add_child(draw)

    # JavaScript to be injected into the Folium map's HTML (runs inside the iframe)
    # m.get_name() will give the JavaScript variable name of the map instance (e.g., "map_123abc")
    js_to_inject = f"""
    <script type="text/javascript">
        function attachDrawListenerToMap() {{
            try {{
                var mapObject = window['{{m.get_name()}}']; // Access the map instance using its JS variable name
                if (mapObject) {{
                    mapObject.on('draw:created', function (e) {{
                        var layer = e.layer;
                        var geoJsonData = layer.toGeoJSON();
                        console.log('Folium map (iframe context) draw:created, sending data to parent:', geoJsonData);
                        window.parent.postMessage({{ type: 'foliumDrawData', data: geoJsonData }}, '*');
                    }});
                    console.log('Folium map (iframe context) draw:created listener attached to map: {{m.get_name()}}');
                }} else {{
                    console.error('Folium map (iframe context) instance {{m.get_name()}} not found. Retrying...');
                    setTimeout(attachDrawListenerToMap, 500); // Retry if map not found immediately
                }}
            }} catch (err) {{
                console.error('Error in attachDrawListenerToMap (iframe context):', err);
                setTimeout(attachDrawListenerToMap, 500); // Retry on error
            }}
        }}
        // Ensure this runs after Folium's own map initialization scripts
        if (document.readyState === 'complete' || document.readyState === 'interactive') {{
            attachDrawListenerToMap();
        }} else {{
            window.addEventListener('load', attachDrawListenerToMap);
        }}
    </script>
    """
    m.get_root().html.add_child(folium.Element(js_to_inject))

    map_html = m._repr_html_()
    return render_template('index.html', map_html=map_html)

@app.route('/process_boundary', methods=['POST'])
def process_boundary():
    global merged_gdf # Ensure we are using the globally loaded and processed GDF
    data = request.get_json()
    logging.info(f"Received boundary data: {data}")

    if not data or 'geometry' not in data or not data['geometry']:
        logging.error("No geometry data received in /process_boundary")
        return jsonify({"error": "No geometry data received"}), 400

    try:
        user_geojson_geometry = data['geometry']
        user_polygon = shape(user_geojson_geometry) # shapely.geometry.shape

        if merged_gdf is None or merged_gdf.empty or 'geometry' not in merged_gdf.columns:
            logging.error("merged_gdf is empty or missing geometry column before spatial query.")
            return jsonify({"error": "No parcel data available for processing. Check server logs."}), 500
        
        # Ensure current_merged_gdf is a GeoDataFrame and has a valid CRS
        current_merged_gdf_for_query = merged_gdf.copy() # Work with a copy for safety
        if not isinstance(current_merged_gdf_for_query, geopandas.GeoDataFrame):
            logging.error("Data is not a GeoDataFrame before spatial query.")
            return jsonify({"error": "Internal server error: Parcel data is not in expected format."}), 500

        if current_merged_gdf_for_query.crs is None:
            logging.warning("merged_gdf has no CRS in process_boundary, setting to EPSG:4326")
            current_merged_gdf_for_query = current_merged_gdf_for_query.set_crs("EPSG:4326", allow_override=True)
        elif current_merged_gdf_for_query.crs.to_string().upper() != "EPSG:4326":
            logging.warning(f"Reprojecting merged_gdf from {current_merged_gdf_for_query.crs} to EPSG:4326 in process_boundary")
            current_merged_gdf_for_query = current_merged_gdf_for_query.to_crs("EPSG:4326")

        # Perform spatial query
        # Ensure user_polygon is implicitly EPSG:4326 (standard for GeoJSON)
        # Filter out invalid geometries from the query GeoDataFrame
        valid_query_gdf = current_merged_gdf_for_query[current_merged_gdf_for_query.is_valid]
        if valid_query_gdf.empty:
            logging.info("No valid geometries in merged_gdf to perform intersection.")
            intersecting_parcels = geopandas.GeoDataFrame([])
        else:
            # Use sindex if available and GDF is large, otherwise direct intersection
            if hasattr(valid_query_gdf, 'sindex') and valid_query_gdf.sindex is not None:
                 possible_matches_index = list(valid_query_gdf.sindex.intersection(user_polygon.bounds))
                 possible_matches = valid_query_gdf.iloc[possible_matches_index]
                 intersecting_parcels = possible_matches[possible_matches.intersects(user_polygon)]
            else: # Fallback for smaller GDFs or if sindex is not built/available
                 intersecting_parcels = valid_query_gdf[valid_query_gdf.intersects(user_polygon)]


        logging.info(f"Found {len(intersecting_parcels)} intersecting parcels.")

        if intersecting_parcels.empty:
            total_assessed_value = 0
            parcel_details_list = []
        else:
            total_assessed_value = intersecting_parcels['ASSESSED_VALUE_TAX'].fillna(0).sum()
            # Ensure FULLADDRESS exists, fill with 'N/A' if not
            if 'FULLADDRESS' not in intersecting_parcels.columns:
                details_df = intersecting_parcels.copy() # Avoid SettingWithCopyWarning
                details_df['FULLADDRESS'] = 'N/A'
                parcel_details_list = details_df[['SSL', 'FULLADDRESS', 'ASSESSED_VALUE_TAX']].fillna({'SSL': 'N/A', 'FULLADDRESS': 'N/A', 'ASSESSED_VALUE_TAX': 0}).to_dict(orient='records')
            else:
                parcel_details_list = intersecting_parcels[['SSL', 'FULLADDRESS', 'ASSESSED_VALUE_TAX']].fillna({'SSL': 'N/A', 'FULLADDRESS': 'N/A', 'ASSESSED_VALUE_TAX': 0}).to_dict(orient='records')
        
        # Store data in session for CSV download
        session['parcel_details'] = parcel_details_list

        return jsonify({
            "message": "Boundary processed successfully",
            "total_value": total_assessed_value,
            "parcel_count": len(intersecting_parcels),
            "parcels": parcel_details_list # Optionally send some details back directly
        })

    except Exception as e:
        logging.error(f"Error processing boundary: {e}", exc_info=True)
        return jsonify({"error": f"Error processing boundary: {str(e)}"}), 500

@app.route('/download_csv')
def download_csv():
    # Retrieve data from session
    parcel_data_for_csv = session.get('parcel_details') 
    if not parcel_data_for_csv:
        return "No data for CSV. Draw a boundary first.", 404

    df_to_download = pd.DataFrame(parcel_data_for_csv)
    csv_buffer = io.StringIO()
    df_to_download.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    return send_file(
        io.BytesIO(csv_buffer.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='parcels_in_boundary.csv'
    )

if __name__ == '__main__':
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
        logging.info(f"Created templates directory at {templates_dir}")
    
    # Data is already loaded at the module level by load_all_data() call.
    # No need to call load_and_prepare_data() here anymore.
        
    logging.info("Flask app starting. Access at http://127.0.0.1:5001/ or http://<your-local-ip>:5001/")
    app.run(debug=True, port=5001, host='0.0.0.0')
