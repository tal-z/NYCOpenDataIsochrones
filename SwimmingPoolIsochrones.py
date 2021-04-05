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


"""1. Compose multi-directional graph of New York City's walkable streets."""
# Read NYC Borough Boundary polygons (with water,
# so as to capture bridges/tunnels) from NYC DCP into a GeoDataFrame.
nyc_boroughs_withwater = gpd.read_file('https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services/NYC_Borough_Boundary_Water_Included/FeatureServer/0/query?where=1=1&outFields=*&outSR=4326&f=pgeojson')
# Use the borough polygons to query Open Steet Map for street data,
# and create a list of multi-directional graphs that represent each borough's walkable street network.
Graphs = [ox.graph_from_polygon(geom, network_type='walk', simplify=False) for geom in nyc_boroughs_withwater['geometry']]
# Stitch the borough graphs together into a single, citywide network graph.
G = nx.compose_all(Graphs)


"""2. Query geodata on NYC's swimming pools from NYC Open Data portal."""
# Authenticate user account on NYC Open Data platform (Socrata).
print("Logging into NYC Open Data.")
client = Socrata("data.cityofnewyork.us",
                 'odQdEcIxnATZPym3KySwgWw27',
                 username=os.getenv('username'),
                 password=os.getenv('password'))
# Request records from the desired resource:
results = client.get("qafw-han9",
                     content_type='geojson',
                     limit=102)
# Read the records into a GeoDataFrame.
pools_gdf = gpd.GeoDataFrame.from_features(results).set_crs(epsg=4326, inplace=True)
print("pools_gdf columns:", pools_gdf.columns)
# Dedupe the data, to account for multiple pools that share a location (adult pool vs. kids pool).
pools_gdf.sort_values(by='name')
pools_gdf.drop_duplicates(subset='gispropnum', inplace=True, keep='last')
pools_gdf.drop_duplicates(subset='name', inplace=True, keep='last')
print(pools_gdf)

"""3. Calculate isochrones surrounding each swimming pool."""
# Since the pool objects are Multipolygons, and we wish to work with point data,
# take the centroid of each multipolygon. We will use these centroids as proxies for pool locations.
pools_gdf['centroids'] = pools_gdf['geometry'].centroid
pools_gdf['centroids'] = pools_gdf['centroids'].to_crs('EPSG:4326')

# Calculate a set of isochrones for each centroid in the dataset,
# and store them to the same GeoDataFrame.
pools_gdf['five_min_isochrones'] = pools_gdf['centroids'].apply(lambda coor: get_isochrone_from_graph(G, coor.x, coor.y,walk_time=5)).to_crs("EPSG:4326")
pools_gdf['ten_min_isochrones'] = pools_gdf['centroids'].apply(lambda coor: get_isochrone_from_graph(G, coor.x, coor.y,walk_time=10)).to_crs("EPSG:4326")
pools_gdf['twenty_min_isochrones'] = pools_gdf['centroids'].apply(lambda coor: get_isochrone_from_graph(G, coor.x, coor.y,walk_time=20)).to_crs("EPSG:4326")

"""4. Plot the data on a map."""
# Grab borough boundaries to use for an NYC base map, this time clipped to the shoreline,
# and re-project it to geographic projection to match the projection of our pools data.
nyc_gdf = gpd.read_file(gpd.datasets.get_path('nybb')).to_crs("EPSG:4326")
# Add the base map to a matplotlib plot.
fig, ax = plt.subplots(figsize=(8,8),dpi=400)
base = nyc_gdf.plot(ax=ax, color='lightgray', edgecolor='gray')
# Clip the isochrone layers to the basemap (borough boundaries),
# to deal with edge effects caused by use of the convex hull method.
pools_gdf['five_min_isochrones'] = gpd.clip(pools_gdf['five_min_isochrones'], nyc_gdf)
pools_gdf['ten_min_isochrones'] = gpd.clip(pools_gdf['ten_min_isochrones'], nyc_gdf)
pools_gdf['twenty_min_isochrones'] = gpd.clip(pools_gdf['twenty_min_isochrones'], nyc_gdf)
# Plot the 5, 10, and 20 minute isochrones surrounding each pool proxy.
pools_gdf['twenty_min_isochrones'].plot(ax=base, color='#FF595E', zorder=5)
pools_gdf['ten_min_isochrones'].plot(ax=base, color='#FFCA3A', zorder=10)
pools_gdf['five_min_isochrones'].plot(ax=base, color='#8AC926', zorder=20)

"""5. Style the map."""
# Calculate and store the centroids of each five-min isochrone, to use as representative points for labeling.
pools_gdf['repr_point'] = pools_gdf['five_min_isochrones'].centroid
# Add a title within the plot, by placing text using axis coordinates.
ax.text(0.05, 0.95, "Walking times\nto New York City's\npublic pools.",
        transform=ax.transAxes, fontsize=25, verticalalignment='top')
# Add a custom legend.
custom_lines = [Line2D([0], [0], color='#8AC926', lw=4),
                Line2D([0], [0], color='#FFCA3A', lw=4),
                Line2D([0], [0], color='#FF595E', lw=4),
                Line2D([0], [0], color='lightgray', lw=4),]
ax.legend(custom_lines, ['5 Minutes', '10 Minutes', '20 Minutes', '>20 Minutes'], loc='lower right', title='Walk Times')
# Add labels to each isochrone centroid (note that centroids
# themselves are not plotted, so as to reduce visual noise).
texts = []
for x, y, label in zip(pools_gdf['repr_point'].x, pools_gdf['repr_point'].y, pools_gdf['name']):
    ax.annotate(label, (x,y), zorder=100, fontsize=3, arrowprops=dict(arrowstyle="-", zorder=100, lw=.5, color='gray'))
# Move the labels from the axis object to the figure object,
# so that they display in the correct z order.
i = 0
for item in ax.texts:
    fig.texts.append(ax.texts.pop(i))
    i += 1
# Use the adjustText library to iteratively adjust label positions.
aT.adjust_text(fig.texts, force_text=0.5, expand_text=(1.2, 1.5), ax=ax)
plt.axis('off')

"""6. Save and display the new map!"""
plt.savefig(f'WalkToPools_{datetime.now()}.png', bbox_inches="tight")
plt.show()

