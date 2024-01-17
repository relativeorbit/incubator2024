from datetime import datetime
from typing import Any, Dict

import pystac
from pystac.utils import str_to_datetime
from pystac import Extent, ProviderRole, SpatialExtent, TemporalExtent
from pystac.extensions import sar
from pystac.link import Link
from pystac import Summaries
from pystac.extensions.projection import ProjectionExtension
from pystac.extensions.raster import RasterBand, RasterExtension
from pystac.extensions.sar import SarExtension
from pystac.extensions.sat import OrbitState, SatExtension

import pandas as pd

import rasterio

import hyp3_sdk as sdk

import concurrent.futures

# Import extension version
from rio_stac.stac import PROJECTION_EXT_VERSION, RASTER_EXT_VERSION

# Import rio_stac methods
from rio_stac.stac import (
    get_dataset_geom,
    get_projection_info,
    #get_raster_info,
    #get_eobands_info,
    bbox_to_geom,
    #get_media_type
)


# https://github.com/developmentseed/rio-stac/blob/4523242b555d1ce2ae4ff7200722579ada1e97c3/docs/docs/examples/Multi_assets_item.ipynb#L9
def hyp32stac(job):
    ''' convert ASF HYP3 Ouput to STAC ITEM 
    '''
    # get root url:
    url = job.files[0]['url']
    outdir = job.files[0]['filename'].rstrip('.zip')
    gdal_path = f'/vsizip//vsicurl/{url}/{outdir}/{outdir}'
    #print(gdal_path)
    
    # Mapping of assets
    assets = [ 
        {"name": "conncomp", "href": gdal_path+'_conncomp.tif', "role": ['data'], "type":pystac.MediaType.GEOTIFF},
        {"name": "corr", "href": gdal_path+'_corr.tif', "role": ['data'], "type":pystac.MediaType.GEOTIFF},
        {"name": "dem", "href": gdal_path+'_dem.tif', "role": ['data'], "type":pystac.MediaType.GEOTIFF},
        {"name": "lv_phi", "href": gdal_path+'_lv_phi.tif', "role": ['data'], "type":pystac.MediaType.GEOTIFF},
        {"name": "lv_theta", "href": gdal_path+'_lv_theta.tif', "role": ['data'], "type":pystac.MediaType.GEOTIFF},
        {"name": "unwrapped", "href": gdal_path+'_unw_phase.tif', "role": ['data'], "type":pystac.MediaType.GEOTIFF},
        {"name": "wrapped", "href": gdal_path+'_wrapped_phase.tif', "role": ['data'], "type":pystac.MediaType.GEOTIFF},
        {"name": "browse", "href": job.browse_images[0], "role": ['overview'], "type":pystac.MediaType.PNG},
        {"name": "thumbnail", "href": job.thumbnail_images[0], "role": ['thumbnail'], "type":pystac.MediaType.PNG},
        {"name": "metadata", "href": gdal_path+'.txt', "role": ['metadata'], "type":pystac.MediaType.TEXT},
    ]

    # Assume all tifs same dimensions
    with rasterio.open(gdal_path+'_unw_phase.tif') as src_dst:
        # Get BBOX and Footprint
        dataset_geom = get_dataset_geom(src_dst, densify_pts=0, precision=-1)  
        bbox = dataset_geom["bbox"]

        proj_info = {
            f"proj:{name}": value
            for name, value in get_projection_info(src_dst).items()
        }

    pystac_assets = []

    for asset in assets:
        pystac_assets.append(
            (
                asset["name"], 
                pystac.Asset(
                    href=asset["href"],
                    media_type=asset["type"],
                    #extra_fields={
                        #**proj_info, # Put into properties to avoid duplication
                        #**raster_info, #avoid opening all these for now... 
                    #},
                    roles=asset["role"],
                ),
            )
        )


    ref,sec = job.job_parameters['granules']
    start = ref.split('_')[3]
    end = sec.split('_')[3]

    # additional properties to add in the item
    properties = dict(
                      start_datetime=str_to_datetime(start).isoformat()+'Z',
                      end_datetime=str_to_datetime(end).isoformat()+'Z',
                      processingDate=str_to_datetime(job.request_time).isoformat()+'Z',
                      burstId=job['name'][:14],
                      granules=job.job_parameters['granules'],
                     )
    #properties['sat:orbit_state']=row.flightDirection.lower()
    # Add projection information 
    properties.update(proj_info)            

    # WARNING: only works for non-redundant time series
    input_datetime = str_to_datetime(start)

    # STAC Item Id
    id = job['name']

    # name of collection the item belongs to
    #collection = 'OPERA_L2_RTC'
    #collection_url = None

    extensions =[
        f"https://stac-extensions.github.io/projection/{PROJECTION_EXT_VERSION}/schema.json", 
        #f"https://stac-extensions.github.io/raster/{RASTER_EXT_VERSION}/schema.json",
    ]
    
    # item
    item = pystac.Item(
        id=id,
        geometry=bbox_to_geom(bbox),
        bbox=bbox,
        # collection=collection,
        stac_extensions=extensions,
        datetime=input_datetime,
        properties=properties,
    )

    for key, asset in pystac_assets:
        item.add_asset(key=key, asset=asset)

    #item.validate()
    
    return item


# NOTE: copied from https://github.com/stactools-packages/sentinel1/blob/main/src/stactools/sentinel1/rtc/constants.py
# General Sentinel-1 Constants
SENTINEL_LICENSE = Link(
    rel="license",
    target="https://sentinel.esa.int/documents/"
    + "247904/690755/Sentinel_Data_Legal_Notice",
)

SENTINEL_INSTRUMENTS = ["c-sar"]
SENTINEL_CONSTELLATION = "sentinel-1"
SENTINEL_PLATFORMS = ["sentinel-1a", "sentinel-1b"]
SENTINEL_FREQUENCY_BAND = sar.FrequencyBand.C
SENTINEL_CENTER_FREQUENCY = 5.405
SENTINEL_OBSERVATION_DIRECTION = sar.ObservationDirection.RIGHT

SENTINEL_PROVIDER = pystac.Provider(
    name="ESA",
    roles=[ProviderRole.LICENSOR, ProviderRole.PRODUCER],
    url="https://sentinel.esa.int/web/sentinel/missions/sentinel-1",
)

SENTINEL_LICENSE = Link(
    rel="license", target="https://spacedata.copernicus.eu/data-offer/legal-documents"
)

SENTINEL_BURST_PROVIDER = pystac.Provider(
    name="ASF DAAC",
    roles=[ProviderRole.LICENSOR, ProviderRole.PROCESSOR, ProviderRole.HOST],
    url="https://hyp3-docs.asf.alaska.edu/guides/burst_insar_product_guide/",
    extra_fields={
        "processing:level": "L3",
        "processing:lineage": "ASF DAAC HyP3 2023 using the hyp3_isce2 plugin version 0.9.1 running ISCE release 2.6.3",  # noqa: E501
        "processing:software": {"ISCE2": "2.6.3"},
    },
)

SENTINEL_BURST_LICENSE = Link(
    rel="license", target="https://doi.org/10.5281/zenodo.8007397"
)

SENTINEL_BURST_DESCRIPTION = "SAR Interferometry (InSAR) products and their associated files. The source data for these products are Sentinel-1 bursts, extracted from Single Look Complex (SLC) products processed by ESA, and they were processed using InSAR Scientific Computing Environment version 2 (ISCE2) software."  # noqa: E501

# NOTE: GLobal forward processing of available bursts started June 2023
# Select areas have more available back to S1A data availability of October 2014!
SENTINEL_BURST_START: datetime = str_to_datetime("2019-01-01T00:00:00Z")
SENTINEL_BURST_EXTENT = Extent(
    SpatialExtent([-180, -90, 180, 90]),
    TemporalExtent([[SENTINEL_BURST_START, None]]),
)

# NOTE: so far, just working with 10
utm_zones = ["10"]#, "11", "12", "13", "14", "15", "16", "17", "18", "19"]
SENTINEL_BURST_EPSGS = [int(f"326{x}") for x in utm_zones]

SENTINEL_BURST_SAR: Dict[str, Any] = {
    "instrument_mode": "IW",
    "product_type": "UNW",
    "polarizations": [sar.Polarization.VV],
    "looks_range": 5,
    "looks_azimuth": 1,
    "gsd": 20,  # final MGRS pixel posting
}


def create_collection(collection_id):
    ''' aggregate summary of items at collection level '''
    summary_dict = {
        "constellation": [SENTINEL_CONSTELLATION],
        "platform": SENTINEL_PLATFORMS,
        "gsd": [SENTINEL_BURST_SAR["gsd"]],
        "proj:epsg": SENTINEL_BURST_EPSGS,
    }

    collection = pystac.Collection(
        id=collection_id, # NOTE: required?
        description=SENTINEL_BURST_DESCRIPTION,
        extent=SENTINEL_BURST_EXTENT,
        title="ASF S1 BURST INTERFEROGRAMS",
        stac_extensions=[
            SarExtension.get_schema_uri(),
            SatExtension.get_schema_uri(),
            ProjectionExtension.get_schema_uri(),
            RasterExtension.get_schema_uri(),
            # Can use pystac.extensions once implemented
            "https://stac-extensions.github.io/processing/v1.0.0/schema.json",
            "https://stac-extensions.github.io/mgrs/v1.0.0/schema.json",
        ],
        keywords=["sentinel", "copernicus", "esa", "sar"],
        providers=[SENTINEL_PROVIDER, SENTINEL_BURST_PROVIDER],
        summaries=Summaries(summary_dict),
    )
    
    return collection