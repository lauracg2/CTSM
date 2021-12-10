#!/usr/bin/env python3
"""
|------------------------------------------------------------------|
|---------------------  Instructions  -----------------------------|
|------------------------------------------------------------------|

Instructions for running on Cheyenne/Casper:

load the following into your local environment
    module load python
    ncar_pylib

-------------------------------------------------------------------
To see the available options for single point cases:
    ./subset_data.py point --help

To see the available options for regional cases:
    ./subset_data.py reg --help 
-------------------------------------------------------------------

This script extracts domain files, surface dataset, and DATM files
at either a single point or a region using the global dataset.

After creating a case using a global compset, run preview_namelist.  
From the resulting lnd_in file in the run directory, find the name 
of the domain file, and the surface data file.

From the datm streams files (e.g. datm.streams.txt.CLMGSWP3v1.Precip)
find the name of the datm forcing data domain file and forcing files.  
Use these file names as the sources for the single point/regional
files to  be created (see below).

After running this script, point to the new CLM domain and surface 
dataset using the user_nl_clm file in the case directory.  In addition, 
copy the datm.streams files to the case directory, with the prefix 
'user_', e.g. user_datm.streams.txt.CLMGSWP3v1.Precip.  Change the 
information in the user_datm.streams* files to point to the single 
point datm data (domain and forcing files) created using this script.  

The domain file is not set via user_nl_clm, but requires changing 
LND_DOMAIN and ATM_DOMAIN (and their paths) in env_run.xml.  

Using single point forcing data requires specifying the nearest 
neighbor mapping algorithm for the datm streams (usually they are 
the first three in the list) in user_nl_datm: mapalgo = 'nn','nn','nn', 
..., where the '...' can still be 'bilinear', etc, depending on the 
other streams that are being used, e.g. aerosols, anomaly forcing, 
bias correction.

The file env_mach_pes.xml should be modified to specify a single 
processor.  The mpi-serial libraries should also be used, and can be 
set in env_build.xml by changing "MPILIB" to "mpi-serial" prior to 
setting up the case.  

The case for the single point simulation should have river routing 
and land ice models turned off (i.e. the compset should use stub 
models SROF and SGLC)

By default, it only extracts surface dataset and for extracting other
files, the appropriate flags should be used.
-------------------------------------------------------------------
To run the script for a single point:
    ./subset_data.py point --help
 
To run the script for a region:
    ./subset_data.py reg --help 

To remove NPL from your environment on Cheyenne/Casper:
    deactivate
-------------------------------------------------------------------
"""

# TODO
# Automatic downloading of missing files if they are missing
# default 78 pft vs 16 pft

#  Import libraries
from __future__ import print_function

import sys
import os
import string
import logging
import subprocess
import argparse

import numpy as np
import xarray as xr

from datetime import date
from getpass import getuser
from logging.handlers import RotatingFileHandler
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter


from ctsm.site_and_regional.base_case import BaseCase
from ctsm.site_and_regional.single_point_case import SinglePointCase
from ctsm.site_and_regional.regional_case import RegionalCase

from ctsm.ctsm_logging import (
    setup_logging_pre_config,
    add_logging_args,
    process_logging_args,
)

logger = logging.getLogger(__name__)

myname = getuser()

def get_parser():
    """
    Get the parser object for subset_data.py script.
    """
    parser = ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.print_usage = parser.print_help
    subparsers = parser.add_subparsers(
        help="Two possible ways to run this sript, either:", dest="run_type"
    )
    pt_parser = subparsers.add_parser("point", help="Run script for a single point.")
    rg_parser = subparsers.add_parser("reg", help="Run script for a region.")

    # -- signle point parser options
    pt_parser.add_argument(
        "--lat",
        help="Single point latitude. [default: %(default)s]",
        action="store",
        dest="plat",
        required=False,
        type=plat_type,
        default=42.5,
    )
    pt_parser.add_argument(
        "--lon",
        help="Single point longitude. [default: %(default)s]",
        action="store",
        dest="plon",
        required=False,
        type=plon_type,
        default=287.8,
    )
    pt_parser.add_argument(
        "--site",
        help="Site name or tag. [default: %(default)s]",
        action="store",
        dest="site_name",
        required=False,
        type=str,
        default="",
    )
    pt_parser.add_argument(
        "--create-domain",
        help="Flag for creating CLM domain file at single point. [default: %(default)s]",
        action="store",
        dest="create_domain",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=False,
    )
    pt_parser.add_argument(
        "--create-surface",
        help="Flag for creating surface data file at single point. [default: %(default)s]",
        action="store",
        dest="create_surfdata",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=True,
    )
    pt_parser.add_argument(
        "--create-landuse",
        help="Flag for creating landuse data file at single point. [default: %(default)s]",
        action="store",
        dest="create_landuse",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=False,
    )
    pt_parser.add_argument(
        "--create-datm",
        help="Flag for creating DATM forcing data at single point. [default: %(default)s]",
        action="store",
        dest="create_datm",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=False,
    )
    pt_parser.add_argument(
        "--datm-syr",
        help="Start year for creating DATM forcing at single point. [default: %(default)s]",
        action="store",
        dest="datm_syr",
        required=False,
        type=int,
        default=1901,
    )
    pt_parser.add_argument(
        "--datm-eyr",
        help="End year for creating DATM forcing at single point. [default: %(default)s]",
        action="store",
        dest="datm_eyr",
        required=False,
        type=int,
        default=2014,
    )
    pt_parser.add_argument(
        "--crop",
        help="Flag for creating datasets using the extensive list of prognostic crop types. [default: %(default)s]",
        action="store",
        dest="crop_flag",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=False,
    )
    pt_parser.add_argument(
        "--dompft",
        help="Dominant PFT type . [default: %(default)s] ",
        action="store",
        dest="dom_pft",
        type=int,
        default=7,
    )
    pt_parser.add_argument(
        "--unisnow",
        help="Flag for creating datasets using uniform snowpack. [default: %(default)s]",
        action="store",
        dest="uni_snow",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=True,
    )
    pt_parser.add_argument(
        "--single-pft",
        help="Flag for making the whole grid 100%% single PFT. [default: %(default)s]",
        action="store",
        dest="overwrite_single_pft",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=True,
    )
    pt_parser.add_argument(
        "--zero-nonveg",
        help="Flag for setting all non-vegetation landunits to zero. [default: %(default)s]",
        action="store",
        dest="zero_nonveg",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=True,
    )
    pt_parser.add_argument(
        "--saturation-excess",
        help="Flag for making dataset using saturation excess. [default: %(default)s]",
        action="store",
        dest="saturation_excess",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=True,
    )
    pt_parser.add_argument(
        "--outdir",
        help="Output directory. [default: %(default)s]",
        action="store",
        dest="out_dir",
        type=str,
        default="/glade/scratch/" + myname + "/single_point/",
    )

    # -- region-specific parser options
    rg_parser.add_argument(
        "--lat1",
        help="Region start latitude. [default: %(default)s]",
        action="store",
        dest="lat1",
        required=False,
        type=plat_type,
        default=-40,
    )
    rg_parser.add_argument(
        "--lat2",
        help="Region end latitude. [default: %(default)s]",
        action="store",
        dest="lat2",
        required=False,
        type=plat_type,
        default=15,
    )
    rg_parser.add_argument(
        "--lon1",
        help="Region start longitude. [default: %(default)s]",
        action="store",
        dest="lon1",
        required=False,
        type=plon_type,
        default=275.0,
    )
    rg_parser.add_argument(
        "--lon2",
        help="Region end longitude. [default: %(default)s]",
        action="store",
        dest="lon2",
        required=False,
        type=plon_type,
        default=330.0,
    )
    rg_parser.add_argument(
        "--reg",
        help="Region name or tag. [default: %(default)s]",
        action="store",
        dest="reg_name",
        required=False,
        type=str,
        default="",
    )
    rg_parser.add_argument(
        "--create-domain",
        help="Flag for creating CLM domain file for a region. [default: %(default)s]",
        action="store",
        dest="create_domain",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=False,
    )
    rg_parser.add_argument(
        "--create-surface",
        help="Flag for creating surface data file for a region. [default: %(default)s]",
        action="store",
        dest="create_surfdata",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=True,
    )
    rg_parser.add_argument(
        "--create-landuse",
        help="Flag for creating landuse data file for a region. [default: %(default)s]",
        action="store",
        dest="create_landuse",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=False,
    )
    rg_parser.add_argument(
        "--create-datm",
        help="Flag for creating DATM forcing data for a region. [default: %(default)s]",
        action="store",
        dest="create_datm",
        type=str2bool,
        nargs="?",
        const=True,
        required=False,
        default=False,
    )
    rg_parser.add_argument(
        "--datm-syr",
        help="Start year for creating DATM forcing for a region. [default: %(default)s]",
        action="store",
        dest="datm_syr",
        required=False,
        type=int,
        default=1901,
    )
    rg_parser.add_argument(
        "--datm-eyr",
        help="End year for creating DATM forcing for a region.  [default: %(default)s]",
        action="store",
        dest="datm_eyr",
        required=False,
        type=int,
        default=2014,
    )
    rg_parser.add_argument(
        "--crop",
        help="Create datasets using the extensive list of prognostic crop types. [default: %(default)s]",
        action="store_true",
        dest="crop_flag",
        default=False,
    )
    rg_parser.add_argument(
        "--dompft",
        help="Dominant PFT type . [default: %(default)s] ",
        action="store",
        dest="dom_pft",
        type=int,
        default=7,
    )
    rg_parser.add_argument(
        "--outdir",
        help="Output directory. [default: %(default)s]",
        action="store",
        dest="out_dir",
        type=str,
        default="/glade/scratch/" + myname + "/regional/",
    )

    return parser


def str2bool(v):
    """
    Function for converting different forms of
    command line boolean strings to boolean value.

    Args:
        v (str): String bool input

    Raises:
        if the argument is not an acceptable boolean string
        (such as yes or no ; true or false ; y or n ; t or f ; 0 or 1).
        argparse.ArgumentTypeError: The string should be one of the mentioned values.

    Returns:
        bool: Boolean value corresponding to the input.
    """
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError(
            "Boolean value expected. [true or false] or [y or n]"
        )


def plat_type(x):
    """
    Function to define lat type for the parser
    and
    raise error if latitude is not between -90 and 90.

    Args:
        x(str): latitude

    Raises:
        Error when x (latitude) is not between -90 and 90.

    Returns:
        x (float): latitude in float

    """
    x = float(x)
    if (x < -90) or (x > 90):
        raise argparse.ArgumentTypeError(
            "ERROR: Latitude should be between -90 and 90."
        )
    return x


def plon_type(x):
    """
    Function to define lon type for the parser and
    convert negative longitudes and
    raise error if lon is not between -180 and 360.

    Args:
        x (str): longitude

    Raises:
        Error: when latitude is <-180 and >360.

    Returns:
        x(float): converted longitude between 0 and 360
    """
    x = float(x)
    if (-180 < x) and (x < 0):
        print("lon is :", x)
        x = x % 360
        print("after modulo lon is :", x)
    if (x < 0) or (x > 360):
        raise argparse.ArgumentTypeError(
            "ERROR: Latitude of single point should be between 0 and 360 or -180 and 180."
        )
    return x


def get_git_sha():
    """
    Returns Git short SHA for the currect directory.
    """
    try:

        # os.abspath(__file__)
        sha = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
            .strip()
            .decode()
        )
    except subprocess.CalledProcessError:
        sha = "NOT-A-GIT-REPOSITORY"
    return sha


def main():

    # -- add logging flags from ctsm_logging
    setup_logging_pre_config()
    parser = get_parser()
    add_logging_args(parser)

    args = parser.parse_args()

    process_logging_args(args)

    # --------------------------------- #

    today = date.today()
    today_string = today.strftime("%Y%m%d")

    pwd = os.getcwd()

    # log_file = os.path.join(pwd, today_string + ".log")

    # log_level = logging.DEBUG
    # setup_logging(log_file, log_level)
    # log = logging.getLogger(__name__)

    logging.info("User = " + myname)
    logging.info("Current directory = " + pwd)

    # --------------------------------- #

    if args.run_type == "point":
        logging.info(
            "----------------------------------------------------------------------------"
        )
        logging.info(
            "This script extracts a single point from the global CTSM inputdata datasets."
        )

        # --  Specify point to extract
        plon = args.plon
        plat = args.plat

        # --  Create regional CLM domain file
        create_domain = args.create_domain
        # --  Create CLM surface data file
        create_surfdata = args.create_surfdata
        # --  Create CLM surface data file
        create_landuse = args.create_landuse
        # --  Create single point DATM atmospheric forcing data
        create_datm = args.create_datm
        datm_syr = args.datm_syr
        datm_eyr = args.datm_eyr

        crop_flag = args.crop_flag

        site_name = args.site_name

        # --  Modify landunit structure
        overwrite_single_pft = args.overwrite_single_pft
        dominant_pft = args.dom_pft
        zero_nonveg_landunits = args.zero_nonveg
        uniform_snowpack = args.uni_snow
        saturation_excess = args.saturation_excess

        # --  Create SinglePoint Object
        single_point = SinglePointCase(
            plat,
            plon,
            site_name,
            create_domain,
            create_surfdata,
            create_landuse,
            create_datm,
            overwrite_single_pft,
            dominant_pft,
            zero_nonveg_landunits,
            uniform_snowpack,
            saturation_excess,
        )
        single_point.create_tag()

        logging.debug(single_point)
        # output_to_logger (single_point)

        if crop_flag:
            num_pft = "78"
        else:
            num_pft = "16"

        logging.debug("crop_flag = " + crop_flag.__str__() + " => num_pft =" + num_pft)

        # --  Set input and output filenames
        # --  Specify input and output directories
        dir_output = args.out_dir
        if not os.path.isdir(dir_output):
            os.mkdir(dir_output)

        dir_inputdata = "/glade/p/cesmdata/cseg/inputdata/"
        dir_clm_forcedata = "/glade/p/cgd/tss/CTSM_datm_forcing_data/"
        dir_input_datm = os.path.join(
            dir_clm_forcedata, "atm_forcing.datm7.GSWP3.0.5d.v1.c170516/"
        )

        dir_output_datm = os.path.join(dir_output, "datmdata/")
        # -- create output dir if it does not exist
        if not os.path.isdir(dir_output_datm):
            os.mkdir(dir_output_datm)

        logging.info("dir_input_datm  : " + dir_input_datm)  #
        logging.info("dir_output_datm : " + dir_output_datm)  #

        # --  Set time stamp
        today = date.today()
        timetag = today.strftime("%y%m%d")

        # --  Specify land domain file  ---------------------------------
        fdomain_in = os.path.join(
            dir_inputdata, "share/domains/domain.lnd.fv0.9x1.25_gx1v7.151020.nc"
        )
        fdomain_out = dir_output + single_point.add_tag_to_filename(
            fdomain_in, single_point.tag
        )
        single_point.fdomain_in = fdomain_in
        single_point.fdomain_out = fdomain_out
        logging.info("fdomain_in  : " + fdomain_in)  #
        logging.info("fdomain_out : " + fdomain_out)  #

        # --  Specify surface data file  --------------------------------
        if crop_flag:
            fsurf_in = os.path.join(
                dir_inputdata,
                "lnd/clm2/surfdata_map/release-clm5.0.18/surfdata_0.9x1.25_hist_78pfts_CMIP6_simyr2000_c190214.nc",
            )
        else:
            fsurf_in = os.path.join(
                dir_inputdata,
                "lnd/clm2/surfdata_map/release-clm5.0.18/surfdata_0.9x1.25_hist_16pfts_Irrig_CMIP6_simyr2000_c190214.nc",
            )

        # fsurf_out  = dir_output + single_point.add_tag_to_filename(fsurf_in, single_point.tag) # remove res from filename for singlept
        fsurf_out = dir_output + single_point.create_fileout_name(
            fsurf_in, single_point.tag
        )
        single_point.fsurf_in = fsurf_in
        single_point.fsurf_out = fsurf_out

        logging.info("fsurf_in   : " + fsurf_in)  #
        logging.info("fsurf_out  : " + fsurf_out)  #

        # --  Specify landuse file  -------------------------------------
        if crop_flag:
            fluse_in = os.path.join(
                dir_inputdata,
                "lnd/clm2/surfdata_map/release-clm5.0.18/landuse.timeseries_0.9x1.25_hist_16pfts_Irrig_CMIP6_simyr1850-2015_c190214.nc",
            )
        else:
            fluse_in = os.path.join(
                dir_inputdata,
                "lnd/clm2/surfdata_map/release-clm5.0.18/landuse.timeseries_0.9x1.25_hist_78pfts_CMIP6_simyr1850-2015_c190214.nc",
            )
        # fluse_out   = dir_output + single_point.add_tag_to_filename( fluse_in, single_point.tag ) # remove resolution from filename for singlept cases
        fluse_out = dir_output + single_point.create_fileout_name(
            fluse_in, single_point.tag
        )
        single_point.fluse_in = fluse_in
        single_point.fluse_out = fluse_out
        logging.info("fluse_in   : " + fluse_in)  #
        logging.info("fluse_out  : " + fluse_out)  #

        # --  Specify datm domain file  ---------------------------------
        fdatmdomain_in = os.path.join(
            dir_clm_forcedata,
            "atm_forcing.datm7.GSWP3.0.5d.v1.c170516/domain.lnd.360x720_gswp3.0v1.c170606.nc",
        )
        fdatmdomain_out = dir_output_datm + single_point.add_tag_to_filename(
            fdatmdomain_in, single_point.tag
        )
        single_point.fdatmdomain_in = fdatmdomain_in
        single_point.fdatmdomain_out = fdatmdomain_out
        logging.info("fdatmdomain_in   : " + fdatmdomain_in)  #
        logging.info("fdatmdomain out  : " + fdatmdomain_out)  #

        # --  Create CTSM domain file
        if create_domain:
            single_point.create_domain_at_point()

        # --  Create CTSM surface data file
        if create_surfdata:
            single_point.create_surfdata_at_point()

        # --  Create CTSM transient landuse data file
        if create_landuse:
            single_point.create_landuse_at_point()

        # --  Create single point atmospheric forcing data
        if create_datm:
            single_point.create_datmdomain_at_point()
            single_point.datm_syr = datm_syr
            single_point.datm_eyr = datm_eyr
            single_point.dir_input_datm = dir_input_datm
            single_point.dir_output_datm = dir_output_datm
            single_point.create_datm_at_point()

        logging.info("Successfully ran script for single point.")
        exit()

    elif args.run_type == "reg":
        logging.info("Running the script for the region")
        # --  Specify region to extract
        lat1 = args.lat1
        lat2 = args.lat2

        lon1 = args.lon1
        lon2 = args.lon2

        # --  Create regional CLM domain file
        create_domain = args.create_domain
        # --  Create CLM surface data file
        create_surfdata = args.create_surfdata
        # --  Create CLM surface data file
        create_landuse = args.create_landuse
        # --  Create DATM atmospheric forcing data
        create_datm = args.create_datm

        crop_flag = args.crop_flag

        reg_name = args.reg_name

        region = RegionalCase(
            lat1,
            lat2,
            lon1,
            lon2,
            reg_name,
            create_domain,
            create_surfdata,
            create_landuse,
            create_datm,
        )

        logging.debug(region)

        if crop_flag:
            num_pft = "78"
        else:
            num_pft = "16"

        logging.debug("crop_flag = " + crop_flag.__str__() + " => num_pft =" + num_pft)

        region.create_tag()

        # --  Set input and output filenames
        # --  Specify input and output directories
        dir_output = "/glade/scratch/" + myname + "/region/"
        if not os.path.isdir(dir_output):
            os.mkdir(dir_output)

        dir_inputdata = "/glade/p/cesmdata/cseg/inputdata/"
        dir_clm_forcedata = "/glade/p/cgd/tss/CTSM_datm_forcing_data/"

        # --  Set time stamp
        command = 'date "+%y%m%d"'
        x2 = subprocess.Popen(command, stdout=subprocess.PIPE, shell="True")
        x = x2.communicate()
        timetag = x[0].strip()
        logging.info(timetag)

        # --  Specify land domain file  ---------------------------------
        fdomain_in = (
            dir_inputdata + "share/domains/domain.lnd.fv1.9x2.5_gx1v7.170518.nc"
        )
        fdomain_out = (
            dir_output + "domain.lnd.fv1.9x2.5_gx1v7." + region.tag + "_170518.nc"
        )
        # SinglePointCase.set_fdomain (fdomain)
        region.fdomain_in = fdomain_in
        region.fdomain_out = fdomain_out

        # --  Specify surface data file  --------------------------------
        fsurf_in = (
            dir_inputdata
            + "lnd/clm2/surfdata_map/surfdata_1.9x2.5_78pfts_CMIP6_simyr1850_c170824.nc"
        )
        fsurf_out = (
            dir_output
            + "surfdata_1.9x2.5_78pfts_CMIP6_simyr1850_"
            + region.tag
            + "_c170824.nc"
        )
        region.fsurf_in = fsurf_in
        region.fsurf_out = fsurf_out

        # --  Specify landuse file  -------------------------------------
        fluse_in = (
            dir_inputdata
            + "lnd/clm2/surfdata_map/landuse.timeseries_1.9x2.5_hist_78pfts_CMIP6_simyr1850-2015_c170824.nc"
        )
        fluse_out = (
            dir_output
            + "landuse.timeseries_1.9x2.5_hist_78pfts_CMIP6_simyr1850-2015_"
            + region.tag
            + ".c170824.nc"
        )
        region.fluse_in = fluse_in
        region.fluse_out = fluse_out

        # --  Create CTSM domain file
        if create_domain:
            region.create_domain_at_reg()

        # --  Create CTSM surface data file
        if create_surfdata:
            region.create_surfdata_at_reg()

        # --  Create CTSM transient landuse data file
        if create_landuse:
            region.create_landuse_at_reg()
        logging.info("Successfully ran script for a regional case.")

    else:
        # print help when no option is chosen
        get_parser().print_help()
