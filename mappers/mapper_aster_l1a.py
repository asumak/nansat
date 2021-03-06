# Name:        mapper_obpg_l2
# Purpose:     Mapping for L2 data from the OBPG web-site
# Authors:      Anton Korosov
# Licence:      This file is part of NANSAT. You can redistribute it or modify
#               under the terms of GNU General Public License, v.3
#               http://www.gnu.org/licenses/gpl-3.0.html

from vrt import GeolocationArray, VRT, gdal, osr, latlongSRS, parse
from datetime import datetime, timedelta
from math import ceil
from nansat_tools import set_defaults

class Mapper(VRT):
    ''' Mapper for ASTER L1A VNIR data'''

    def __init__(self, fileName, gdalDataset, gdalMetadata, **kwargs):
        ''' Create VRT '''
        # check if it is ASTER L1A
        assert 'AST_L1A_' in fileName
        shortName = gdalMetadata['INSTRUMENTSHORTNAME']
        assert shortName == 'ASTER'

        subDatasets = gdalDataset.GetSubDatasets()

        kwDict = {'GCP_COUNT' : 10,         # number of GCPs along each dimention
                  'bandNames' : ['VNIR_Band1', 'VNIR_Band2', 'VNIR_Band3N'],
                  'bandWaves' : [560, 660, 820]}
        '''
        'VNIR_Band3B' : 820, 'SWIR_Band4' : 1650, 'SWIR_Band5' : 2165,
        'SWIR_Band6' : 2205, 'SWIR_Band7' : 2260, 'SWIR_Band8' : 2330,
        'SWIR_Band9' : 2395, 'TIR_Band10' : 8300, 'TIR_Band11' : 8650,
        'TIR_Band12' : 9100, 'TIR_Band13' : 10600, 'TIR_Band14' : 11300
        '''

        # set kwargs
        asterL1aKwargs = {}
        for key in kwargs:
            if key.startswith('aster_l1a'):
                keyName = key.replace('aster_l1a_', '')
                asterL1aKwargs[keyName] = kwargs[key]

        # modify the default values using input values
        kwDict = set_defaults(kwDict, asterL1aKwargs)

        # find datasets for each band and generate metaDict
        metaDict = []
        bandDatasetMask = 'HDF4_EOS:EOS_SWATH:"%s":%s:ImageData'
        for bandName, bandWave in zip(kwDict['bandNames'],
                                      kwDict['bandWaves']):
            metaEntry = {
                'src': {
                    'SourceFilename': bandDatasetMask % (fileName, bandName),
                    'SourceBand': 1,
                    'DataType': 6,
                    },
                'dst':  {
                    'wkv': 'toa_outgoing_spectral_radiance',
                    'wavelength': str(bandWave),
                    'suffix': str(bandWave),
                    },
                }
            metaDict.append(metaEntry)

        # create empty VRT dataset with geolocation only
        gdalSubDataset = gdal.Open(metaDict[0]['src']['SourceFilename'])
        VRT.__init__(self, gdalSubDataset, **kwargs)

        # add bands with metadata and corresponding values to the empty VRT
        self._create_bands(metaDict)

        # find largest lon/lat subdatasets
        latShape0 = 0
        for subDataset in subDatasets:
            if 'Latitude' in subDataset[1]:
                ls = int(subDataset[1].strip().split('[')[1].split('x')[0])
                if ls >= latShape0:
                    latShape0 = ls
                    latSubDS = subDataset[0]
            if 'Longitude' in subDataset[1]:
                ls = int(subDataset[1].strip().split('[')[1].split('x')[0])
                if ls >= latShape0:
                    latShape0 = ls
                    lonSubDS = subDataset[0]
        self.logger.debug(latSubDS)
        self.logger.debug(lonSubDS)

        # get lat/lon matrices
        xDataset = gdal.Open(lonSubDS)
        yDataset = gdal.Open(latSubDS)

        longitude = xDataset.ReadAsArray()
        latitude = yDataset.ReadAsArray()

        step0 = longitude.shape[0] / kwDict['GCP_COUNT']
        step1 = longitude.shape[1] / kwDict['GCP_COUNT']

        # estimate pixel/line step
        pixelStep = int(ceil(float(gdalSubDataset.RasterXSize) / float(xDataset.RasterXSize)))
        lineStep = int(ceil(float(gdalSubDataset.RasterYSize) / float(xDataset.RasterYSize)))
        self.logger.debug('steps: %d %d %d %d' % (step0, step1, pixelStep, lineStep))

        # generate list of GCPs
        gcps = []
        k = 0
        for i0 in range(0, latitude.shape[0], step0):
            for i1 in range(0, latitude.shape[1], step1):
                # create GCP with X,Y,pixel,line from lat/lon matrices
                lon = float(longitude[i0, i1])
                lat = float(latitude[i0, i1])
                if (lon >= -180 and lon <= 180 and lat >= -90 and lat <= 90):
                    gcp = gdal.GCP(lon, lat, 0, i1 * pixelStep, i0 * lineStep)
                    self.logger.debug('%d %d %d %f %f' % (k, gcp.GCPPixel, gcp.GCPLine, gcp.GCPX, gcp.GCPY))
                    gcps.append(gcp)
                    k += 1
        # append GCPs and lat/lon projection to the vsiDataset
        self.dataset.SetGCPs(gcps, latlongSRS.ExportToWkt())

        self._set_time(parse(gdalMetadata['FIRSTPACKETTIME']))

