import geopandas as gpd
import pandas as pd # Import pandas
from shapely.geometry import Point, Polygon # Import Polygon
import time # Import time module
import folium  # Import folium for map visualization

print("Script started.")
start_time = time.time()

# 1. Load data from CSV files
print("Loading parcel attribute data (ITSPE_View)...")
load_start1 = time.time()
parcels_df = pd.read_csv("ITSPE_View_05022025_6763517825838124791.csv", low_memory=False) # Added low_memory=False for potential mixed types
load_end1 = time.time()
print(f"Parcel attributes loaded in {load_end1 - load_start1:.2f} seconds. {len(parcels_df)} records found.")

print("Loading address point data (Address_Points)...")
load_start2 = time.time()
address_df = pd.read_csv("Address_Points.csv", low_memory=False)
load_end2 = time.time()
print(f"Address points loaded in {load_end2 - load_start2:.2f} seconds. {len(address_df)} records found.")

# 2. Prepare and Merge Data
print("Preparing and merging data...")
merge_start = time.time()
# Select necessary columns from address data
address_coords = address_df[['SSL', 'LATITUDE', 'LONGITUDE']].copy()

# --- Data Type Check and Conversion for SSL --- 
# Check initial types
print(f"  Parcel SSL type: {parcels_df['SSL'].dtype}, Address SSL type: {address_coords['SSL'].dtype}")
# Convert both SSL columns to string to ensure consistent merging
parcels_df['SSL'] = parcels_df['SSL'].astype(str)
address_coords['SSL'] = address_coords['SSL'].astype(str)
print(f"  Converted SSL types to string.")
# Optional: Clean whitespace if necessary
parcels_df['SSL'] = parcels_df['SSL'].str.strip()
address_coords['SSL'] = address_coords['SSL'].str.strip()
# --- End Data Type Check --- 

# Drop duplicates in address data based on SSL to avoid issues during merge
address_coords.drop_duplicates(subset=['SSL'], keep='first', inplace=True)
print(f"  Address points deduplicated by SSL: {len(address_coords)} unique SSLs remain.")

# Merge parcel attributes with coordinates
parcels_merged = pd.merge(parcels_df, address_coords, on='SSL', how='left')
merge_end = time.time()
print(f"Data merged in {merge_end - merge_start:.2f} seconds.")

# --- Save unmatched parcels --- 
unmatched_parcels = parcels_merged[parcels_merged['LATITUDE'].isnull()]
if not unmatched_parcels.empty:
    # Select only the original columns from parcels_df for the output
    original_columns = parcels_df.columns.tolist()
    unmatched_output = unmatched_parcels[original_columns]
    output_filename = "unmatched_parcels.csv"
    print(f"  Saving {len(unmatched_output)} parcels that could not be matched to {output_filename}...")
    unmatched_output.to_csv(output_filename, index=False)
    print(f"  Saved unmatched parcels.")
else:
    print("  All parcels were successfully matched with coordinates.")
# --- End save unmatched parcels ---

# Filter out parcels that couldn't be matched before creating GeoDataFrame
parcels_with_coords = parcels_merged.dropna(subset=['LATITUDE', 'LONGITUDE']).copy()
print(f"  {len(parcels_with_coords)} parcels successfully merged with coordinates.")

# Handle potential errors if no coordinates were found
if len(parcels_with_coords) == 0:
    print("Error: No parcels could be matched with coordinates. Check SSL values in both files.")
    exit()

# 3. Create GeoDataFrame (using only parcels with coordinates)
print("Creating GeoDataFrame...")
geo_start = time.time()
geometry = gpd.points_from_xy(parcels_with_coords.LONGITUDE, parcels_with_coords.LATITUDE)
parcels = gpd.GeoDataFrame(parcels_with_coords, geometry=geometry, crs="EPSG:4326") # Set initial CRS (WGS84)
geo_end = time.time()
print(f"GeoDataFrame created in {geo_end - geo_start:.2f} seconds.")
print(f"Initial CRS set to: {parcels.crs}")

# *** DIAGNOSTIC: Print total bounds of the data ***
print(f"Data bounds (minx, miny, maxx, maxy) in {parcels.crs}: {parcels.total_bounds}")

# Project all geometries to a suitable projected CRS for buffering (meters)
print(f"Projecting {len(parcels)} parcels to EPSG:3857...")
project_start = time.time()
parcels_proj = parcels.to_crs(epsg=3857)  # Web Mercator (meters)
project_end = time.time()
print(f"Projection completed in {project_end - project_start:.2f} seconds.")
print(f"Projected data bounds (minx, miny, maxx, maxy) in {parcels_proj.crs}: {parcels_proj.total_bounds}")

# 4. Define Locations of Interest and Process Each

# Define polygon geometries for specific neighborhoods
navy_yard_poly = Polygon([
    (-77.0120, 38.8850),
    (-76.9950, 38.8829),
    (-76.9881, 38.8683),
    (-77.0116, 38.8710),
    (-77.0120, 38.8850)
])

the_wharf_poly = Polygon([
    (-77.03098, 38.88056),
    (-77.01578, 38.88056), # Corrected: Should be longitude, latitude for the second point of the polygon as well
    (-77.01600, 38.86700),
    (-77.03098, 38.86700),
    (-77.03098, 38.88056)
])

union_market_poly = Polygon([
    (-77.00400, 38.90190),
    (-76.99300, 38.90190),
    (-76.99300, 38.90858),
    (-77.00400, 38.90858),
    (-77.00400, 38.90190)
])

locations_of_interest = [
    {"name": "RFK Stadium", "latitude": 38.890, "longitude": -76.972, "color": "red", "geometry_type": "buffer"},
    {"name": "Navy Yard", "polygon": navy_yard_poly, "color": "blue", "geometry_type": "polygon"},
    {"name": "The Wharf", "polygon": the_wharf_poly, "color": "green", "geometry_type": "polygon"},
    {"name": "Union Market", "polygon": union_market_poly, "color": "purple", "geometry_type": "polygon"}
]

rfk_buffer_radius_miles = 0.5  # Buffer radius for RFK Stadium
rfk_buffer_distance_meters = rfk_buffer_radius_miles * 1609.34

all_parcels_for_map_list = [] # List to store GeoDataFrames for concatenation
output_parcel_data = [] # Initialize list to store data for CSV output

for location in locations_of_interest:
    loc_name = location["name"]
    loc_color = location["color"]
    geometry_type = location["geometry_type"]
    print(f"\n--- Processing: {loc_name} ---")

    loc_boundary_projected = None # Initialize variable

    if geometry_type == "buffer":
        loc_point = Point(location["longitude"], location["latitude"])
        # Project location point and create buffer
        loc_point_proj = gpd.GeoSeries([loc_point], crs="EPSG:4326").to_crs(parcels_proj.crs).iloc[0]
        loc_boundary_projected = loc_point_proj.buffer(rfk_buffer_distance_meters)
        print(f"Circular buffer for {loc_name} created with radius {rfk_buffer_radius_miles} miles.")
    elif geometry_type == "polygon":
        loc_polygon = location["polygon"]
        # Project the polygon to the same CRS as parcels_proj
        loc_boundary_gdf = gpd.GeoDataFrame([{'geometry': loc_polygon}], crs="EPSG:4326")
        loc_boundary_projected = loc_boundary_gdf.to_crs(parcels_proj.crs).geometry.iloc[0]
        print(f"Using predefined polygon for {loc_name}.")
    else:
        print(f"Unknown geometry type for {loc_name}. Skipping.")
        continue
    
    if loc_boundary_projected:
        print(f"Boundary for {loc_name} (projected) bounds: {loc_boundary_projected.bounds}")

        print(f"Filtering parcels within boundary of {loc_name}...")
        # Ensure parcels_proj has a valid spatial index for faster intersection
        if not parcels_proj.has_sindex:
             parcels_proj.sindex
        parcels_near_loc = parcels_proj[parcels_proj.geometry.intersects(loc_boundary_projected)].copy()
        print(f"Found {len(parcels_near_loc)} parcels near {loc_name}.")

        if not parcels_near_loc.empty:
            # Summarize assessed values
            parcels_near_loc['NEWTOTAL'] = pd.to_numeric(parcels_near_loc['NEWTOTAL'], errors='coerce')
            summary_loc = parcels_near_loc.groupby('USECODE')['NEWTOTAL'].agg(['count', 'mean', 'sum'])
            print(f"\n--- Summary of Assessed Values near {loc_name} ---")
            print(summary_loc)
            
            if not summary_loc.empty:
                total_assessed_value_loc = summary_loc['sum'].sum()
                print(f"\nTotal Assessed Value of Parcels near {loc_name}: ${total_assessed_value_loc:,.2f}")

                # Extract data for CSV output
                for _, parcel_row in parcels_near_loc.iterrows():
                    output_parcel_data.append({
                        'Area': loc_name,
                        'SSL': parcel_row.get('SSL', 'N/A'),
                        'Address': parcel_row.get('PREMISEADD', 'N/A'), # Assuming PREMISEADD is the address column
                        'Assessed Value': pd.to_numeric(parcel_row.get('NEWTOTAL', 0), errors='coerce')
                    })
            else:
                print(f"No assessable parcels found for {loc_name} to calculate total value.")

            # Prepare for map by reprojecting to EPSG:4326 and adding location info
            parcels_for_map_loc = parcels_near_loc.to_crs(epsg=4326)
            parcels_for_map_loc['location_name'] = loc_name
            parcels_for_map_loc['color'] = loc_color
            all_parcels_for_map_list.append(parcels_for_map_loc)
        else:
            print(f"No parcels found within the boundary for {loc_name}.")
    else:
        print(f"Could not define boundary for {loc_name}.")

# Consolidate all parcels for the map into a single GeoDataFrame
if all_parcels_for_map_list:
    all_parcels_for_map = pd.concat(all_parcels_for_map_list, ignore_index=True)
else:
    all_parcels_for_map = gpd.GeoDataFrame() # Empty GeoDataFrame if no parcels found anywhere

# Save detailed parcel data to CSV
if output_parcel_data:
    output_df = pd.DataFrame(output_parcel_data)
    output_csv_filename = "parcels_in_each_area_details.csv"
    print(f"\\nSaving detailed parcel data to {output_csv_filename}...")
    output_df.to_csv(output_csv_filename, index=False)
    print(f"Detailed parcel data saved to {output_csv_filename}.")
else:
    print("\\nNo parcel data to save to CSV.")

# 7. Visualize parcels near all locations on a map
if not all_parcels_for_map.empty:
    print("\nCreating map visualization for all locations...")
    map_start = time.time()

    # Center map on the first location or a general DC coordinate
    map_center_lat = locations_of_interest[0]["latitude"]
    map_center_lon = locations_of_interest[0]["longitude"]
    main_map = folium.Map(location=[map_center_lat, map_center_lon], zoom_start=12)

    for _, row in all_parcels_for_map.iterrows():
        if row.geometry.is_valid:
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=3, # Smaller radius for potentially many points
                color=row['color'],
                fill=True,
                fill_color=row['color'],
                fill_opacity=0.6,
                tooltip=f"{row['location_name']}<br>SSL: {row.get('SSL', 'N/A')}<br>Value: ${pd.to_numeric(row.get('NEWTOTAL', 0), errors='coerce'):,.0f}"
            ).add_to(main_map)

    map_filename = "all_locations_map.html"
    main_map.save(map_filename)
    map_end = time.time()
    print(f"Map visualization saved to {map_filename} in {map_end - map_start:.2f} seconds.")
else:
    print("No parcels found near any location to visualize on the map.")

end_time = time.time()
print(f"\nTotal script execution time: {end_time - start_time:.2f} seconds.")