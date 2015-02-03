import numpy as np
from collections import OrderedDict
from utils import get_geo_dim, filter_coord, get_index
from datetime import datetime
from pymongo import Connection
import h5py

# CONSTANTS
DATA_PATH = "/g/data1/v10/HPCData/"

def load_full_tile(item, lazy=True):
    # TODO Hardcoded values
    return Tile2(sat="LS5_TM", origin_id=item,
                bands=6, lat_start=item[u'lat_start'], lat_end=item[u'lat_start']+item[u'lat_extent'],
                lon_start=item[u'lon_start'], lon_end=item[u'lon_start']+item[u'lon_extent'], lazy=lazy)


def load_partial_tile(item, lat_start, lat_end, lon_start, lon_end, lazy=True):
    # TODO Hardcoded values
    return Tile2(sat="LS5_TM", origin_id=item, 
                 bands=6, lat_start=lat_start, lat_end=lat_end, lon_start=lon_start, lon_end=lon_end, lazy=lazy)
                 


class Tile2(object):

    # Consider integrating satellite information inside id_object
    def __init__(self, sat=None, origin_id=None, bands=None, lat_start=None, lat_end=None,
                 lon_start=None, lon_end=None, lazy=True):

        self._origin_id = origin_id
        self._origin_id["satellite"] = sat

        orig_y_dim = get_geo_dim(origin_id["lat_start"], origin_id["lat_extent"], origin_id["pixel_size"])
        orig_x_dim = get_geo_dim(origin_id["lon_start"], origin_id["lon_extent"], origin_id["pixel_size"])

        corr_lat_start = filter_coord(lat_start, orig_y_dim)
        corr_lon_start = filter_coord(lon_start, orig_x_dim)

        corr_lat_end = filter_coord(lat_end, orig_y_dim)
        corr_lon_end = filter_coord(lon_end, orig_x_dim)

        lat1 = get_index(corr_lat_start, orig_y_dim)
        lat2 = get_index(corr_lat_end, orig_y_dim) + 1
        lon1 = get_index(corr_lon_start, orig_x_dim) 
        lon2 = get_index(corr_lon_end, orig_x_dim) + 1

        self.y_dim = get_geo_dim(corr_lat_start, corr_lat_end-corr_lat_start+self._origin_id["pixel_size"], self._origin_id["pixel_size"])
        self.x_dim = get_geo_dim(corr_lon_start, corr_lon_end-corr_lon_start+self._origin_id["pixel_size"], self._origin_id["pixel_size"])
        self.band_dim = np.arange(0,bands,1)+1
        self.array = None

        if not lazy:
            with h5py.File(DATA_PATH + "{0}_{1:03d}_{2:04d}_{3}.nc".format(self._origin_id["satellite"],
                                                               int(self._origin_id[u'lon_start']),
                                                               int(self._origin_id[u'lat_start']),
                                                               self._origin_id[u'time'].year), 'r') as dfile:
                
                self.array = dfile[self._origin_id["product"]][self.timestamp].value[lat1:lat2, lon1:lon2]

    def __getitem__(self, index):
        # TODO: Properly implement band dimension
        if len(index) == 2:

            #Mostly sure about comparisons
            #lat_bounds = self._y_dim[0] <= index[0].start <= self._y_dim[-1] or self._y_dim[0] < index[0].stop < self._y_dim[-1]
            #lon_bounds = self._x_dim[0] <= index[1].start <= self._x_dim[-1] or self._x_dim[0] < index[1].stop < self._x_dim[-1]
            lat_bounds = index[0].start <= self.y_dim[-1] and index[0].stop > self.y_dim[0]
            lon_bounds = index[1].start <= self.x_dim[-1] and index[1].stop > self.x_dim[0]

            bounds = (lat_bounds, lon_bounds)

            if bounds.count(True) == len(bounds):

                start_lat_index = max(index[0].start, self.y_dim[0])
                array_lat_start_index = np.abs(self.y_dim - index[0].start).argmin()
                start_lon_index = max(index[1].start, self.x_dim[0])
                array_lon_start_index = np.abs(self.x_dim - index[1].start).argmin()

                if index[0].stop > np.max(self.y_dim):
                    end_lat_index = np.max(self.y_dim) + self._origin_id["pixel_size"]
                    array_lat_end_index = None

                else:
                    end_lat_index = index[0].stop
                    array_lat_end_index = np.abs(self.y_dim - index[0].stop).argmin()

                if index[1].stop > np.max(self.x_dim):
                    end_lon_index = np.max(self.x_dim) + self._origin_id["pixel_size"]
                    array_lon_end_index = None

                else:
                    end_lon_index = index[1].stop
                    array_lon_end_index = np.abs(self.x_dim - index[1].stop).argmin()


                if self._array is None:
                    return Tile2(self._sat, self._prod, self._lat_id, self._lon_id, self._time, self._pixel_size,
                                len(self._band_dim), start_lat_index, start_lon_index,
                                end_lat_index-start_lat_index, end_lon_index-start_lon_index, None)

                else:
                    return Tile2(self._sat, self._prod, self._lat_id, self._lon_id, self._time, self._pixel_size,
                                len(self._band_dim), start_lat_index, start_lon_index,
                                end_lat_index-start_lat_index, end_lon_index-start_lon_index, 
                                self._array[array_lon_start_index:array_lon_end_index,
                                array_lat_start_index:array_lat_end_index])

            else:
                return None
        else:
            # TODO: Properly manage index exceptions
            raise Exception

    @property
    def dims(self):
        """Mapping from dimension names to lengths.
        This dictionary cannot be modified directly, but is updated when adding
        new variables.
        """
        dim = OrderedDict()
        dim["latitude"] = self.y_dim
        dim["longitude"] = self.x_dim
        dim["band"] = self.band_dim
        return dim


    @property
    def shape(self):
        """Mapping from dimension names to lengths.
        This dictionary cannot be modified directly, but is updated when adding
        new variables.
        """
        dim = self.dims
        return "({}, {}, {})".format(dim["latitude"].shape[0], dim["longitude"].shape[0], dim["band"].shape[0])


    @property
    def timestamp(self):
        """Mapping from dimension names to lengths.
        This dictionary cannot be modified directly, but is updated when adding
        new variables.
        """
        return self._origin_id[u'time'].strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]


    def traverse_time(self, position=1):

        conn = Connection('128.199.74.80', 27017)
        db = conn["datacube"]


        if position >= 0:
	    cursor = db.index2.find({"product": self._prod, "lat_start": self._lat_id, "lon_start": self._lon_id, "time": {"$gte": self._time}}).sort("time", 1)
            item = cursor[position]
        else:
	    cursor = db.index2.find({"product": self._prod, "lat_start": self._lat_id, "lon_start": self._lon_id, "time": {"$lte": self._time}}).sort("time", -1)
            item = cursor[abs(position)]
	
        if item is not None:
            return Tile2(item[u'product'], item[u'lat_start'], item[u'lat_extent'], item[u'lon_start'], item[u'lon_extent'], item[u'pixel_size'],
                        item[u'time'], bands= 6, array=None)

        else:
            return None 

if __name__ == "__main__":

    conn = Connection('128.199.74.80', 27017)
    db = conn["datacube"]

    time1 = datetime.strptime("2006-01-01T00:00:00.000Z", '%Y-%m-%dT%H:%M:%S.%fZ')
    time2 = datetime.strptime("2007-01-01T00:00:00.000Z", '%Y-%m-%dT%H:%M:%S.%fZ')
    
    item = db.index.find_one({"product": "NBAR", "lat_start": -34, "lon_start": 121, "time": {"$gte": time1, "$lt": time2}})
    print item
    print get_geo_dim(item["lat_start"], item["lat_extent"], item["pixel_size"]).shape
    tile = load_full_tile(item)
    tile = load_partial_tile(item, -33.83333333, -33.333333, 80, 130, lazy=False)
    print tile.dims
    print tile.timestamp
    print tile.shape
    if tile.array is not None: 
        print tile.array.shape
    else:
        print "Empty array"
