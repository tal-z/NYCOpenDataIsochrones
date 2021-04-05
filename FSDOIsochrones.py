import os
from datetime import datetime

from sodapy import Socrata
import geopandas as gpd
import networkx as nx
import osmnx as ox
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from shapely.geometry import Point, LineString, Polygon
import adjustText as aT

ox.config(log_console=True, use_cache=True)
ox.__version__
#plt.rcParams["path.snap"] = False
#plt.rcParams['axes.facecolor']='lightskyblue'
#plt.rcParams['savefig.facecolor']='lightskyblue'

walk_speed = 3

def get_isochrone_from_graph(G, x, y, walk_time=10, speed=3):
    """Returns the coordinates of an isochrone polygon
    given a graph and a set of coordinates.
    Travel mode is walking.
    Uses an average walking speed of 4.5 km/h as a default.
    Uses 10-minute walking time as default cutoff."""
    center_node = ox.get_nearest_node(G, (y, x))
    meters_per_minute = speed * 1000 / 60 #km per hour to m per minute
    for u, v, k, data in G.edges(data=True, keys=True):
        data['time'] = data['length'] / meters_per_minute
    subgraph = nx.ego_graph(G, center_node, radius=walk_time, distance='time')
    node_points = [Point(data['x'], data['y']) for node, data in subgraph.nodes(data=True)]
    polys = gpd.GeoSeries(node_points).unary_union.convex_hull
    return polys


# 1. Compose multi-directional graph out of New York City's walkable streets.
nyc_boroughs_withwater = gpd.read_file('https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services/NYC_Borough_Boundary_Water_Included/FeatureServer/0/query?where=1=1&outFields=*&outSR=4326&f=pgeojson')
Graphs = [ox.graph_from_polygon(geom, network_type='walk', simplify=False) for geom in nyc_boroughs_withwater['geometry']]
G = nx.compose_all(Graphs)


# 1. Authenticate user account on NYC Open Data platform (Socrata).
print("Logging into NYC Open Data.")
client = Socrata("data.cityofnewyork.us",
                 'odQdEcIxnATZPym3KySwgWw27',
                 username=os.getenv('username'),
                 password=os.getenv('password'))

# 2. Request records from the desired resource:
results = client.get("if26-z6xq",
                     content_type='geojson',
                     limit=250)

# 3. Read the records into a geodataframe
pools_gdf = gpd.GeoDataFrame.from_features(results).set_crs(epsg=4326, inplace=True)
print("pools_gdf columns:", pools_gdf.columns)
pools_gdf.sort_values(by='food_scrap_drop_off_site')
pools_gdf.drop_duplicates(subset='food_scrap_drop_off_site', inplace=True, keep='last')
pools_gdf.drop_duplicates(subset='geometry', inplace=True, keep='last')
print(pools_gdf)

# 4. Re-project the geometry to a standard projection, which will be used for all layers.
#pools_gdf['geometry'] = pools_gdf['geometry'].to_crs("EPSG:4326")

# 5. Since the pool objects are Multipolygons, and we wish to work with point data,
#    take the centroid of each multipolygon. We will use these centroids as proxies.
pools_gdf['centroids'] = pools_gdf['geometry'].centroid
pools_gdf['centroids'] = pools_gdf['centroids'].to_crs('EPSG:4326')

# 6. Calculate an isochrones for each centroid in the dataset, and store it to the same geodataframe.
pools_gdf['five_min_isochrones'] = pools_gdf['centroids'].apply(lambda coor: get_isochrone_from_graph(G, coor.x, coor.y, walk_time=5, speed=walk_speed)).to_crs("EPSG:4326")
pools_gdf['ten_min_isochrones'] = pools_gdf['centroids'].apply(lambda coor: get_isochrone_from_graph(G, coor.x, coor.y, walk_time=10, speed=walk_speed)).to_crs("EPSG:4326")
pools_gdf['twenty_min_isochrones'] = pools_gdf['centroids'].apply(lambda coor: get_isochrone_from_graph(G, coor.x, coor.y, walk_time=20, speed=walk_speed)).to_crs("EPSG:4326")

# 7. Grab data for an NYC base map, and re-project it to standard projection.
nyc_gdf = gpd.read_file(gpd.datasets.get_path('nybb')).to_crs("EPSG:4326")

# 8. Plot the base map.
fig, ax = plt.subplots(figsize=(8,8),dpi=400)
base = nyc_gdf.plot(ax=ax, color='lightgray', edgecolor='gray')

# 9. Clip the isochrone layers to the basemap.
pools_gdf['five_min_isochrones'] = gpd.clip(pools_gdf['five_min_isochrones'], nyc_gdf)
pools_gdf['ten_min_isochrones'] = gpd.clip(pools_gdf['ten_min_isochrones'], nyc_gdf)
pools_gdf['twenty_min_isochrones'] = gpd.clip(pools_gdf['twenty_min_isochrones'], nyc_gdf)

# 10. Plot the 5, 10, and 20 minute isochrones surrounding each pool.
pools_gdf['twenty_min_isochrones'].plot(ax=base, color='#FF595E', zorder=5)
pools_gdf['ten_min_isochrones'].plot(ax=base, color='#FFCA3A', zorder=10)
pools_gdf['five_min_isochrones'].plot(ax=base, color='#8AC926', zorder=20)

# 11. Plot the centroids of each five-min isochrone.
pools_gdf['repr_point'] = pools_gdf['five_min_isochrones'].centroid

# 12. Add some styling.
ax.text(0.05, 0.95, "Walking times\nto New York City's\nFood Scrap\nDrop-off Sites.",
        transform=ax.transAxes, fontsize=25, verticalalignment='top')
ax.text(0.05, 0.67, f"Walking times computed using an average\nwalking speed of {walk_speed} miles/hour, travelling\nalong NYC's walkable streets and sidewalks.\n\nData from NYC Open Data as of March 2020,\nlast updated prior to COVID-19 program closure.",
        transform=ax.transAxes, fontsize=5, verticalalignment='top')

custom_lines = [Line2D([0], [0], color='#8AC926', lw=4),
                Line2D([0], [0], color='#FFCA3A', lw=4),
                Line2D([0], [0], color='#FF595E', lw=4),
                Line2D([0], [0], color='lightgray', lw=4),]
ax.legend(custom_lines, ['5 Minutes', '10 Minutes', '20 Minutes', '>20 Minutes'], loc='lower right', title='Walk Times')

plt.axis('off')

# 13. Show it off.
plt.savefig(f'WalkToFSDOs_{datetime.now()}.png', bbox_inches="tight")
plt.show()

