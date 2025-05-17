import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon
from flask import Flask, render_template, request, jsonify, send_file
import folium
from folium.plugins import Draw
import io
import os

app = Flask(__name__)

# --- Global variable for preloaded data ---
parcels_gdf = None
print("Script started. Flask app initializing...")

def load_and_prepare_data():
    """Loads and prepares parcel data."""
    global parcels_gdf
    if parcels_gdf is not None:
        print("Parcel data already loaded.")
        return

    print("Loading parcel attribute data (ITSPE_View)...")
    try:
        # Ensure this CSV file is in the same directory as app.py or provide a full path
        parcels_df = pd.read_csv("ITSPE_View_05022025_6763517825838124791.csv", low_memory=False)
        print(f"Parcel attributes loaded. {len(parcels_df)} records found.")

        print("Loading address point data (Address_Points)...")
        address_df = pd.read_csv("Address_Points.csv", low_memory=False)
        print(f"Address points loaded. {len(address_df)} records found.")

        print("Preparing and merging data...")
        address_coords = address_df[['SSL', 'LATITUDE', 'LONGITUDE']].copy()

        parcels_df['SSL'] = parcels_df['SSL'].astype(str).str.strip()
        address_coords['SSL'] = address_coords['SSL'].astype(str).str.strip()
        address_coords.drop_duplicates(subset=['SSL'], keep='first', inplace=True)

        parcels_merged = pd.merge(parcels_df, address_coords, on='SSL', how='left')
        
        unmatched_parcels = parcels_merged[parcels_merged['LATITUDE'].isnull()]
        if not unmatched_parcels.empty:
            print(f"Warning: {len(unmatched_parcels)} parcels could not be matched with coordinates.")

        parcels_with_coords = parcels_merged.dropna(subset=['LATITUDE', 'LONGITUDE']).copy()
        if len(parcels_with_coords) == 0:
            print("Error: No parcels could be matched with coordinates. Cannot proceed.")
            return

        print(f"{len(parcels_with_coords)} parcels successfully merged with coordinates.")
        geometry = gpd.points_from_xy(parcels_with_coords.LONGITUDE, parcels_with_coords.LATITUDE)
        parcels_gdf = gpd.GeoDataFrame(parcels_with_coords, geometry=geometry, crs="EPSG:4326")
        
        parcels_gdf['NEWTOTAL'] = pd.to_numeric(parcels_gdf['NEWTOTAL'], errors='coerce').fillna(0)
        
        print(f"GeoDataFrame created with {len(parcels_gdf)} geocoded parcels. CRS: {parcels_gdf.crs}")

    except FileNotFoundError as e:
        print(f"Error loading data files: {e}. Make sure CSV files are in the workspace root.")
        return
    except Exception as e:
        print(f"An unexpected error occurred during data loading: {e}")
        return

@app.before_request
def initialize_data():
    if parcels_gdf is None:
        print("First request, attempting to load data...")
        load_and_prepare_data()
        if parcels_gdf is None:
            print("Data loading failed. The application might not work correctly.")
        else:
            print("Data loaded successfully for the request.")

@app.route('/')
def index():
    if parcels_gdf is None:
        load_and_prepare_data()
        if parcels_gdf is None:
            return "Error: Parcel data could not be loaded. Please check server logs.", 500

    if not parcels_gdf.empty:
        map_center = [parcels_gdf.union_all().centroid.y, parcels_gdf.union_all().centroid.x]
    else:
        map_center = [38.9072, -77.0369]
        
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
    <script type=\"text/javascript\">
        function attachDrawListenerToMap() {{
            try {{
                var mapObject = window['{m.get_name()}']; // Access the map instance using its JS variable name
                if (mapObject) {{
                    mapObject.on('draw:created', function (e) {{
                        var layer = e.layer;
                        var geoJsonData = layer.toGeoJSON();
                        console.log('Folium map (iframe context) draw:created, sending data to parent:', geoJsonData);
                        window.parent.postMessage({{ type: 'foliumDrawData', data: geoJsonData }}, '*');
                    }});
                    console.log('Folium map (iframe context) draw:created listener attached to map: {m.get_name()}');
                }} else {{
                    console.error('Folium map (iframe context) instance {m.get_name()} not found. Retrying...');
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
    if parcels_gdf is None:
        print("Error: parcels_gdf is None in process_boundary")
        return jsonify({"error": "Parcel data not loaded on server"}), 500

    data = request.get_json()
    if not data or 'geometry' not in data:
        print(f"Error: No geometry data received. Data: {data}")
        return jsonify({"error": "No geometry data received"}), 400

    geojson_geom = data['geometry']
    if not geojson_geom or 'coordinates' not in geojson_geom:
        print(f"Error: Invalid geometry format. GeoJSON: {geojson_geom}")
        return jsonify({"error": "Invalid geometry format"}), 400

    print(f"Received geometry: {geojson_geom['type']}, coordinates: {str(geojson_geom['coordinates'])[:100]}...") # Log snippet of coords

    try:
        coords = geojson_geom['coordinates']
        if geojson_geom['type'] == 'Polygon':
            drawn_polygon = Polygon(coords[0]) 
        elif geojson_geom['type'] == 'Rectangle': # folium-draw might send rectangle as Polygon
            drawn_polygon = Polygon(coords[0])
        else:
            print(f"Error: Unsupported geometry type: {geojson_geom['type']}")
            return jsonify({"error": f"Unsupported geometry type: {geojson_geom['type']}"}), 400

        print(f"Drawn polygon type: {drawn_polygon.geom_type}, Is valid: {drawn_polygon.is_valid}")
        if not drawn_polygon.is_valid:
            drawn_polygon = drawn_polygon.buffer(0)
            print(f"Drawn polygon after buffer(0), Is valid: {drawn_polygon.is_valid}")
        
        if not drawn_polygon.is_valid:
            print("Error: Drawn geometry is still not valid after buffering.")
            return jsonify({"error": "Drawn geometry is not valid even after buffering"}), 400

        print(f"Drawn polygon bounds: {drawn_polygon.bounds}")
        print(f"Parcels GDF CRS: {parcels_gdf.crs}, Total parcels: {len(parcels_gdf)}")

        # Perform intersection
        parcels_in_boundary = parcels_gdf[parcels_gdf.intersects(drawn_polygon)].copy()
        print(f"Number of parcels found in boundary: {len(parcels_in_boundary)}")

        response_data = {}
        if parcels_in_boundary.empty:
            print("No parcels found in the drawn boundary.")
            response_data = {
                "message": "No parcels found within the drawn boundary.",
                "total_assessed_value": 0,
                "parcel_count": 0,
                "csv_available": False
            }
        else:
            # Ensure NEWTOTAL is numeric for sum()
            parcels_in_boundary['NEWTOTAL'] = pd.to_numeric(parcels_in_boundary['NEWTOTAL'], errors='coerce').fillna(0)
            total_assessed_value = parcels_in_boundary['NEWTOTAL'].sum()
            parcel_count = len(parcels_in_boundary)
            
            print(f"Calculated total_assessed_value: {total_assessed_value}, parcel_count: {parcel_count}")
            if 'PREMISEADD' not in parcels_in_boundary.columns:
                print("Warning: 'PREMISEADD' column missing in parcels_in_boundary. CSV might lack addresses.")
                # Add a placeholder if it's missing to prevent error later, though data will be incomplete
                parcels_in_boundary['PREMISEADD'] = 'Address N/A'


            csv_data_preview = parcels_in_boundary[['SSL', 'PREMISEADD', 'NEWTOTAL']].copy()
            csv_data_preview.rename(columns={'PREMISEADD': 'Address', 'NEWTOTAL': 'Assessed Value'}, inplace=True)
            
            app.config['LAST_PROCESSED_PARCELS_FOR_CSV'] = csv_data_preview.to_dict(orient='records')
            
            response_data = {
                "message": f"Found {parcel_count} parcels.",
                "total_assessed_value": float(total_assessed_value),
                "parcel_count": parcel_count,
                "csv_available": True
            }

        print(f"Returning JSON: {response_data}")
        return jsonify(response_data)

    except Exception as e:
        print(f"Error processing boundary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"An server-side error occurred: {str(e)}"}), 500

@app.route('/download_csv')
def download_csv():
    parcel_data_for_csv = app.config.get('LAST_PROCESSED_PARCELS_FOR_CSV')
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
        print(f"Created templates directory at {templates_dir}")
    
    # Load data at application startup
    print("Attempting to load data at application startup...")
    load_and_prepare_data()
    if parcels_gdf is None:
        print("FATAL: Data loading failed at startup. Application may not function correctly.")
    else:
        print("Data loaded successfully at startup.")
        
    print("Flask app starting. Access at http://127.0.0.1:5001/")
    app.run(debug=True, port=5001, host='0.0.0.0')
