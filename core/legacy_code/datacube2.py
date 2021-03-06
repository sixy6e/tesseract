import time
from datetime import datetime
import numpy as np
import pandas as pd
from collections import OrderedDict, namedtuple
from tile2 import Tile2, load_partial_tile, drill_pixel_tile, drill_pixel_tile_parallel, drill_tile_complete
from math import floor
from utils import get_geo_dim
# import only for test plotting
#from matplotlib.ticker import LinearLocator, FormatStrFormatter
import matplotlib.pyplot as plt
#from matplotlib import cm
from mpl_toolkits.mplot3d.axes3d import Axes3D
from pymongo import Connection

from multiprocessing import Process, Manager

mongo_ip = 'localhost'

def load_data(prod, min_lat, max_lat, min_lon, max_lon, time_start, time_end, lazy=True):

    conn = Connection(mongo_ip, 27017)
    db = conn["datacube"]

    cursor = db.index.find({"product": prod, "lat_start": {"$gte": int(floor(min_lat)), "$lte": int(floor(max_lat))},
                             "lon_start": {"$gte": int(floor(min_lon)), "$lte": int(floor(max_lon))},
                             "time": {"$gte": time_start, "$lt": time_end}})
    tiles = []
    for item in cursor:
        tiles.append(load_partial_tile(item, min_lat, max_lat, min_lon, max_lon, lazy=lazy))

    return DataCube(tiles)


def get_snapshot(prod, min_lat, max_lat, min_lon, max_lon, time, lazy=True):

    lats = np.arange(floor(min_lat), floor(max_lat)+1)  
    lons = np.arange(floor(min_lon), floor(max_lon)+1)  

    conn = Connection(mongo_ip, 27017)
    db = conn["datacube"]
    
    partial_image = None

    for lat in lats:
        image_row = None
        for lon in lons:
            cursor = db.index.find({"product": prod, "lat_start": lat, "lon_start": lon}).sort("time", -1).limit(1)
            
            if cursor.count(with_limit_and_skip = True) == 1:
                item = cursor[0]

                tile_complete = drill_tile_complete(item, min_lat, max_lat, min_lon, max_lon, 0)
                if image_row is None:
                    image_row = tile_complete
               
                else:    
                    image_row = np.hstack((image_row, tile_complete))
        
        if partial_image is None:
                partial_image = image_row
        else:    
                partial_image = np.vstack((partial_image ,image_row))
    
    return partial_image


def get_timeseries(product, lat, lon, time_start, time_end, band, nan_value=-999):
    
    conn = Connection(mongo_ip, 27017)
    db = conn["datacube"]

    cursor = db.index.find({"product": product, "lat_start": int(floor(lat)), "lon_start": int(floor(lon)),
                             "time": {"$gte": time_start, "$lt": time_end}}).sort("time", 1)
    tiles = drill_pixel_tile(cursor, lat, lon, product, band)
    
    ts_data = []
    if len(tiles[0].array.shape) == 3:
        for tile in tiles:
            filt_array = [None if x==nan_value else x for x in tile.array[0][0]]
            if all(filt_array):
                filt_array = [tile.origin_id[u'time']] + filt_array
                ts_data.append(tuple(filt_array))
    else: 
        for tile in tiles:
            filt_array = [None if x==nan_value else x for x in tile.array[0]]
            if all(filt_array):
                filt_array = [tile.origin_id[u'time']] + filt_array
                ts_data.append(tuple(filt_array))
   
    return pd.DataFrame(ts_data)


def get_timeseries_parallel(product, lat, lon, time_start, time_end, band, nan_value=-999):
    
    conn = Connection(mongo_ip, 27017)
    db = conn["datacube"]

    cursor = db.index.find({"product": product, "lat_start": int(floor(lat)), "lon_start": int(floor(lon)),
                             "time": {"$gte": time_start, "$lt": time_end}}).sort("time", 1)

    processes = []
    manager = Manager()
    queue = manager.Queue()
    
    chunk = []
    max_chunk = 200
    counter = 0

    for item in cursor:
        counter += 1
        chunk.append(item)
        if len(chunk) == max_chunk:
            p = Process(target=drill_pixel_tile_parallel, args=(queue, chunk, lat, lon, product, band))
            processes.append(p)
            p.start()
            counter = 0
            chunk = []

    if len(chunk) > 0:
        p = Process(target=drill_pixel_tile_parallel, args=(queue, chunk, lat, lon, product, band))
        processes.append(p)
        p.start()
        counter = 0
        chunk = []


    for p in processes:
        p.join()

    tiles = []
    for _ in processes:
        tiles = tiles + queue.get()


    ts_data = [] 
    if len(tiles[0].array.shape) == 3:
        for tile in tiles:
            filt_array = [None if x==nan_value else x for x in tile.array[0][0]]
            if all(filt_array):
                filt_array = [tile.origin_id[u'time']] + filt_array
                ts_data.append(tuple(filt_array))
    else: 
        for tile in tiles:
            filt_array = [None if x==nan_value else x for x in tile.array[0]]
            if all(filt_array):
                filt_array = [tile.origin_id[u'time']] + filt_array
                ts_data.append(tuple(filt_array))
   
    return pd.DataFrame(ts_data)

class DataCube(object):
    
    def __init__(self, tiles=[]):
        self._dims = None 
        self._tiles = tiles
        self._attrs = None
        self._dims_init()

    def _dims_init(self):
        dims = OrderedDict()

        products = np.unique(np.sort(np.array([tile.origin_id[u'product'] for tile in self._tiles])))
        dims["product"] = products

        max_pixel = max([tile.origin_id[u'pixel_size'] for tile in self._tiles])
        
        min_lat = min([min(tile.y_dim) for tile in self._tiles])
        max_lat = max([max(tile.y_dim) for tile in self._tiles])
        latitudes = get_geo_dim(min_lat, max_lat-min_lat, max_pixel)
        dims["latitude"] = latitudes
        
        min_lon = min([min(tile.x_dim) for tile in self._tiles])
        max_lon = max([max(tile.x_dim) for tile in self._tiles])
        longitudes = get_geo_dim(min_lon, max_lon-min_lon, max_pixel)
        dims["longitude"] = longitudes
       
        times = np.unique(np.sort(np.array([tile.origin_id[u'time'] for tile in self._tiles])))
        dims["time"] = times
        self._dims = dims        

    def __getitem__(self, index):
        #TODO: Implement rest of dimensions
        if len(index) == 4:
            new_tiles = []
            for tile in self._tiles:
                tile = tile[index[1].start:index[1].stop, index[2].start:index[2].stop]
                if tile is not None:
                    new_tiles.append(tile)
            if len(new_tiles) > 0:
                return DataCube(new_tiles)

            else:
                return None

    
    @property
    def shape(self):
        """Mapping from dimension names to lengths.
        This dictionary cannot be modified directly, but is updated when adding
        new variables.
        """
        return "({}, {}, {}, {})".format(self._dims["product"].shape[0], self._dims["latitude"].shape[0],
                                         self._dims["longitude"].shape[0], self._dims["time"].shape[0])

    @property
    def dims(self):
        """Mapping from dimension names to lengths.
        This dictionary cannot be modified directly, but is updated when adding
        new variables.
        """
        return self._dims


    def plot_datacube(self):
        fig = plt.figure()
        ax = fig.gca(projection='3d')

        times_conv = {}
        min_time = np.inf
        max_time = -np.inf
        for key, value in self._tiles.iteritems():
            times_conv[key.time] = np.float32(key.time)
            if np.float32(key.time) < min_time:
                min_time = np.float32(key.time)
            if np.float32(key.time) > max_time:
                max_time = np.float32(key.time)

        for key, value in self._tiles.iteritems():
            times_conv[key.time] = times_conv[key.time] - min_time

        min_z = np.inf
        max_z = -np.inf
        print len(self._tiles)
        for key, value in self._tiles.iteritems():
            lons = get_geo_dim(key.lon_start, key.lon_extent, key.pixel_size)
            lats = get_geo_dim(key.lat_start, key.lat_extent, key.pixel_size)
            x, y = np.meshgrid(lons, lats)
            z = times_conv[key.time]
            print 1
            ax.plot_wireframe(x, y, z, rstride=1, cstride=1)
            print 2

            if z < min_z:
                min_z = z
            if z > max_z:
                max_z = z

        ax.set_zlim(min_z-1.0, max_z+1.0)

        #ax.zaxis.set_major_locator(LinearLocator(10))
        #ax.zaxis.set_major_formatter(FormatStrFormatter('%.02f'))
        print 3
        plt.show()
        #return plt


    def add_tile(self, tile):

        self._tiles.append(tile) 
        self._dims_init()

    
if __name__ == "__main__":
    time1 = datetime.strptime("1982-08-01T00:00:00.000Z", '%Y-%m-%dT%H:%M:%S.%fZ')
    time2 = datetime.strptime("2011-08-01T00:00:00.000Z", '%Y-%m-%dT%H:%M:%S.%fZ')
    product = "PQA"
    #product = "NBAR"
    
    start = time.time()
    print get_timeseries(product, -31.343, 121.2345, time1, time2, [1], nan_value=-999).head(2)
    stop = time.time()
    print stop-start
    """ 
    start = time.time()
    print get_timeseries_parallel(product, -31.343, 122.2345, time1, time2, 4, nan_value=-999).head(2)
    stop = time.time()
    print stop-start
    start = time.time()
    print get_timeseries_parallel(product, -31.343, 123.2345, time1, time2, 4, nan_value=-999).head(2)
    stop = time.time()
    print stop-start
    start = time.time()
    print get_timeseries_parallel(product, -31.343, 124.2345, time1, time2, 4, nan_value=-999).head(2)
    stop = time.time()
    print stop-start
    start = time.time()
    print get_timeseries_parallel(product, -31.343, 125.2345, time1, time2, 4, nan_value=-999).head(2)
    stop = time.time()
    print stop-start
    start = time.time()
    print get_timeseries_parallel(product, -31.343, 126.2345, time1, time2, 4, nan_value=-999).head(2)
    stop = time.time()
    print stop-start
    start = time.time()
    print get_timeseries_parallel(product, -31.343, 127.2345, time1, time2, 4, nan_value=-999).head(2)
    stop = time.time()
    print stop-start
    start = time.time()
    print get_timeseries_parallel(product, -31.343, 128.2345, time1, time2, 4, nan_value=-999).head(2)
    stop = time.time()
    print stop-start
    start = time.time()
    """
