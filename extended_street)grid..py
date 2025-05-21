"""
# Reintegration of Street Grid at RFK Stadium Site (Washington, DC)

This script creates both a **static map image** and an **interactive web map** to visualize a proposed extension of the street grid through the RFK Stadium site in Washington, DC. The goal is to illustrate how reopening the site’s street network can reconnect it with surrounding neighborhoods (Kingman Park, Rosedale, Capitol Hill) and key features like the Anacostia River and Kingman/Heritage Islands.

## Context & Intent
- **Concept:** All existing surface parking and barriers on the former stadium site are assumed removed, allowing city streets to be extended through the area. We draw these **conceptual street extensions** as dashed lines (distinct from existing streets) to indicate they are new proposals rather than current roads.
- **Base Map:** We use OpenStreetMap imagery as the base to show existing streets and geography for context:contentReference[oaicite:0]{index=0}. Major roads such as East Capitol Street (running east-west along the south edge of the site) and Benning Road (diagonally near the north) will be visible on the base map for orientation. The Anacostia River and Kingman/Heritage Islands appear to the east of the site.
- **Extended Grid:** The dashed **red lines** on the map represent extended street segments following the logical grid alignment. They show how streets from the adjacent grid (e.g. **numbered north-south streets** and **lettered east-west streets**) could continue through the RFK site. For example, we extend a couple of north-south streets roughly corresponding to 21st–23rd Streets NE and a few east-west cross streets, spanning the full site.
- **Nearby Neighborhoods:** The map area includes parts of **Kingman Park** and **Rosedale** (north/northwest of the site) and **Capitol Hill** (west/southwest) for context. This highlights how the extended grid would reconnect these neighborhoods through the RFK site.

## How to Interpret the Visualization
- **Dashed Red Lines:** Proposed new street segments (not currently existing). They are clearly differentiated by a dashed style and color. These lines connect to the existing street network at the edges of the RFK site, demonstrating potential through-streets.
- **Existing Streets:** Shown in the base map (solid lines in standard OSM colors) for reference. The extended segments align with these existing roads where they would be connected.
- **Geographic Features:** The base map displays the Anacostia River (blue water) and Kingman/Heritage Islands (green areas) adjacent to the site. These natural features are labeled or discernible for context, emphasizing the site’s location by the river.

By overlaying the conceptual grid on real map data, city planners and stakeholders can **visualize the connectivity gains** of integrating the RFK site back into the urban fabric. The static image can be used in reports, while the interactive map allows zoom/pan exploration of the area.

## Dependencies
- **geopandas** – for handling geospatial data (creating and projecting geometries).
- **shapely** – to define geometric shapes (LineStrings for street segments).
- **contextily** – to add an OpenStreetMap base map to the static plot.
- **folium** – to create an interactive Leaflet map (already used in the project for mapping:contentReference[oaicite:1]{index=1}).
- **matplotlib** (usually via geopandas/pyplot) – for rendering the static map image.

All these can be installed via pip if not already present (e.g. `pip install geopandas shapely contextily folium matplotlib`). The DC Property Tax Analysis project already includes most of these for its mapping functions:contentReference[oaicite:2]{index=2}.

## Usage
When you run this script, it will generate:
1. **A static map image** saved as `rfk_extended_grid.png` in the current directory.
2. **An interactive HTML map** saved as `rfk_extended_grid_map.html` which you can open in a web browser to explore.

"""

import geopandas as gpd
from shapely.geometry import LineString
import contextily as ctx
import folium
import matplotlib.pyplot as plt

# 1. Define conceptual extended street segments using approximate coordinates (lat, lon)
# We choose representative lines extending through the RFK Stadium site:
# - Three north-south lines (following the alignments of the DC grid's numbered streets)
# - Two east-west lines (following the alignments of lettered streets)
# Coordinates are approximate and cover from the site’s southern edge (near East Capitol St) 
# to the northern edge (near Benning Rd), and from the western edge (near 19th St NE) 
# to the eastern edge by Kingman Island (near 26th St NE). 
extended_lines = [
    # North-South extensions (longitude is fixed for each, latitude varies)
    LineString([(-76.980, 38.889), (-76.980, 38.896)]),  # Western vertical segment (approx near 19th/20th St NE)
    LineString([(-76.972, 38.889), (-76.972, 38.896)]),  # Middle vertical segment (approx through site center):contentReference[oaicite:3]{index=3}
    LineString([(-76.964, 38.889), (-76.964, 38.896)]),  # Eastern vertical segment (approx near 25th/26th St NE)
    # East-West extensions (latitude is fixed for each, longitude varies)
    LineString([(-76.980, 38.893), (-76.964, 38.893)]),  # Lower horizontal segment (mid-site east-west road)
    LineString([(-76.980, 38.895), (-76.964, 38.895)])   # Upper horizontal segment (near north edge of site)
]

# Create a GeoDataFrame for the extended lines (CRS WGS84 latitude/longitude)
ext_gdf = gpd.GeoDataFrame(geometry=extended_lines, crs="EPSG:4326")

# 2. Prepare a static map with contextily (OSM base) and matplotlib
# Project geometries to Web Mercator (EPSG:3857) for plotting with OSM tiles
ext_gdf_merc = ext_gdf.to_crs(epsg=3857)
# Determine plot extents (add a small margin around the data bounds for context)
minx, miny, maxx, maxy = ext_gdf_merc.total_bounds
x_margin = (maxx - minx) * 0.1
y_margin = (maxy - miny) * 0.1
# Create plot
fig, ax = plt.subplots(figsize=(8, 6))
# Plot the extended lines in red dashed style
ext_gdf_merc.plot(ax=ax, color='red', linewidth=2, linestyle='--', label='Proposed Extended Streets')
# Add OpenStreetMap base tiles
ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik)
# Adjust view
ax.set_xlim(minx - x_margin, maxx + x_margin)
ax.set_ylim(miny - y_margin, maxy + y_margin)
ax.set_axis_off()
# Optionally add a legend for clarity (showing dashed red line meaning)
ax.legend(loc='lower right')
# Save the static map to a PNG file
plt.savefig("rfk_extended_grid.png", dpi=300)
plt.close(fig)

# 3. Prepare an interactive map with Folium
# Use center of RFK site (approx 38.890 N, -76.972 W):contentReference[oaicite:4]{index=4} and a suitable zoom level
map_center = [38.890, -76.972]
m = folium.Map(location=map_center, zoom_start=14)  # OpenStreetMap base by default:contentReference[oaicite:5]{index=5}
# Add each extended line to the folium map with a dashed red style
for line in extended_lines:
    # Extract line coordinates in [lat, lon] format for folium
    coords = [(pt[1], pt[0]) for pt in line.coords]  # shapely gives (x, y) as (lon, lat)
    folium.PolyLine(coords, color="red", weight=4, opacity=1, dash_array="5,5").add_to(m)
# (Optional) Add a tooltip or marker legend explaining the dashed lines on the interactive map
folium.LayerControl().add_to(m)  # add layer control if multiple layers (not strictly needed here)

# Save interactive map to an HTML file
m.save("rfk_extended_grid_map.html")

print("Static map saved as rfk_extended_grid.png")
print("Interactive map saved as rfk_extended_grid_map.html")
