
"""
tess_stars2px.py - High precision TESS pointing tool.
Convert target coordinates given in Right Ascension and Declination to
TESS detector pixel coordinates for the prime mission TESS observing
sectors (Year 1 & 2) and Extendend mission Year 3.
Can also query MAST to obtain detector
pixel coordinates for a star by TIC ID only (must be online for this option).

USAGE to display command line arguments:
python tess_stars2px.py -h

AUTHORS: Original programming in C and focal plane geometry solutions
    by Alan Levine (MIT)
 This python translation by Christopher J. Burke (MIT)
 Testing and focal plane geometry refinements by Michael Fausnaugh &
         Roland Vanderspek (MIT)
 Testing by Thomas Barclay (NASA Goddard) &
         Jessica Roberts (Univ. of Colorado)
 Sesame queries by Brett Morris (UW)
 Proxy Support added by Dishendra Mishra

VERSION: 0.4.3

WHAT'S NEW:
    -MUCH FASTER NOW - skipped rough estimate step which was much much slower
         than just doing the matrix math for position.
    -Proxy support
    -***FIXED: TIC ids that overflow 32bit integers were not being resolved correctly.  Now Fixed by using 64 bit integers
    -Missing check on last sector 39 fixed
    -Fixed pixel limits in function entry
    -Year 3 Sectors 27-39 now provided
    -Updated Sector 24-26 pointing to higher ecliptic scattered light avoidance position


NOTES:
    -Pointing table is for TESS Year 1 - 3 (Sectors 1-39) in Southern Ecliptic
    -Pointing table is unofficial, and the pointings may change.
    -See https://tess.mit.edu/observations/ for latest TESS pointing table
    -Pointing prediction algorithm is same as employed internally at MIT for
        target management.  However, hard coded focal plane geometry is not
        up to date and may contain inaccurate results.
    -Testing shows pointing with this tool should be accurate to better than
        a pixel, but without including aberration effects, ones algorithm
        adopted for centroiding highly assymmetric point-spread function
        at edge of
        camera, and by-eye source location, a 2 pixel accuracy estimate is
        warranted.
    -The output pixel coordinates assume the ds9 convention with
        1,1 being the middle of the lower left corner.
    -No corrections for velocity aberration are calculated.
       Potentially more accurate
        results can be obtained if the target RA and Declination coordinates
        have aberration effects applied.
    -For proposals to the TESS science office or directors discretionary time,
      please consult the TESS prediction webtool available at
      https://heasarc.gsfc.nasa.gov/cgi-bin/tess/webtess/wtv.py
      for official identification of 'observable' targets.  However,
      if your proposal depends on a single or few targets, then this tool is
      helpful to further refine the likelihood of the target being available
      on the detectors.
     -The calibrated FFI fits file release at MAST and calibrated by
        NASA Ames SPOC will have WCS information available to
        supplant this code.  The WCS generation is independent of the
        focal plane geometry model employed in this code and will give
        different results at the pixel level.  However, the WCS information
        is not available until the FFI files are released, whereas
        this code can predict positions in advance of data release.
     -Hard coded focal plane geometry parameters from rfpg5_c1kb.txt

NOTES OLDER VERSIONS:
    -Wrapper function implemented tess_stars2px_function_entry()
     With an example in the readme for using tess_stars2px in a python program
     rather than on the command line.
    -Pre filter step previously depended on the current mission profile of
        pointings aligned with ecliptic coordinates to work.  The pre filter
        step was rewritten in order to support mission planning not tied
        to ecliptic alignment.  End users should not see any change in
        results with this change.  However, local copies can be modified
        for arbitrary spacecraft ra,dec, roll and get same functionality.
    -A reverse option is added to find the ra and dec for a given
        sector, camera, ccd, colpix, rowpix.  This is most useful for
        planning arbitrary pointing boundaries and internal use to identify
        targets on uncalibrated
        images that don't have WCS info available.  For precision work one
        shold defer to WCS information on calibrated FFIs rather than this tool.
        The reverse is a brute force 'hack' that uses a minimizer on the
        forward direction code to find ra and dec.  In principle it is possible
        to reverse the matrix transforms to get the ra and dec directly, but
        I chose this less efficient method for expediency.  The minimizer
        is not guaranteed to converge at correct answer.  The current method
        is a slow way to do this.


TODOS:
    -Include approximate or detailed velocity aberration corrections
    -Time dependent Focal plane geometry
    -Do the reverse transormation go from pixel to RA and Dec in a direct
        reverse transform manner rather than the current implementation
        that does a brute force minimization from the forward ra,dec-->pix code

DEPENDENCIES:
    python 3+
    astropy
    numpy

SPECIAL THANKS TO:
    Includes code from the python MAST query examples
    https://mast.stsci.edu/api/v0/pyex.html

IMPLEMENTATION DETAILS:
    In summary, the code begins with a space craft bore site pointing in RA,
    Dec, and roll angle.  A series of Euler angle translation matrices
    are calculated based upon the space craft bore site.  Next the target
    coordinates in RA and Dec are translated to the space craft bore site
    frame.  Next, the target coordinates are translated to each of the four
    TESS camera frames.  Once target coordinates are translated to the
    camera frame the radial position of the target relative to the camera
    center is checked to see if it is potentially in the camera field of view.
    If so, the focal plane position is calculated using a radial polynomial
    model with a constant term and terms the even powers (2nd ,4th , and 8th).
    Rotations are applied to convert the on sky positions to the detector
    readout directions.

MIT License
Copyright (c) 2018 Christopher J Burke

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import numpy as np
import os
import argparse
from astropy.coordinates import SkyCoord
import sys
import datetime
import json
import pandas as pd
try: # Python 3.x
    from urllib.parse import quote as urlencode
    from urllib.request import urlretrieve
    from urllib.parse import urlparse
except ImportError:  # Python 2.x
    from urllib import pathname2url as urlencode
    from urllib import urlretrieve
    from urlparse import urlparse
try: # Python 3.x
    import http.client as httplib
except ImportError:  # Python 2.x
    import httplib
import scipy.optimize as opt
import base64


class Levine_FPG():
    """Al Levine Focal Plane Geometry Methods
        Translated from starspx6.c
        INPUT:
            sc_ra_dec_roll = numpy array of the SpaceCraft boresite (sc Z-axis)
            ra, dec, and roll [deg]
            The roll angle is in RA, Dec space clockwise relative to the celestial
            pole.  roll angle = 0 [deg] implies space craft X-axis points N celestial (increasing dec)
            roll angle = 90 [deg] implies sc X-axis points towards increasing/decreasing (?) RA
        *** In practice there is a separate fpg file for each of the four cameras ***
        rmat1[3,3] = is the rotation matrix from ra&dec to spacecraft boresite coords
        rmat4[NCAM,3,3] - is the rotation matrix from ra&dec to NCAM coords
    """
    parm_dict_list = [{}, {}, {}, {}]
    NCAM = 4 # Number of Cameras
    NCCD = 4 # Number of CCDs per Camera

    def __init__(self, sc_ra_dec_roll=None, fpg_file_list=None):
        self.eulcam = np.zeros((self.NCAM,3), dtype=np.double)
        self.optcon = np.zeros((self.NCAM,6), dtype=np.double)
        self.ccdxy0 = np.zeros((self.NCAM, self.NCCD, 2), dtype=np.double)
        self.pixsz = np.zeros((self.NCAM, self.NCCD, 2), dtype=np.double)
        self.ccdang = np.zeros((self.NCAM, self.NCCD), dtype=np.double)
        self.ccdtilt = np.zeros((self.NCAM, self.NCCD, 2), dtype=np.double)
        self.asymang = np.zeros((self.NCAM,), dtype=np.double)
        self.asymfac = np.zeros((self.NCAM,), dtype=np.double)
        self.rmat1 = np.zeros((3,3), dtype=np.double)
        self.rmat4 = np.zeros((self.NCAM,3,3), dtype=np.double)
        self.havePointing = False
        # Read in the fpg parameter files
        self.read_all_levine_fpg_files(fpg_file_list)
        # Generate rotation matrices if ra dec and roll values given
        if not sc_ra_dec_roll is None:
            # go from sky to spacecraft
            self.sky_to_sc_mat(sc_ra_dec_roll)
            # Go from spacecraft to each camera's coords
            for icam in range(self.NCAM):
                cureul = self.eulcam[icam,:]
                rmat2 = self.sc_to_cam_mat(cureul)
                self.rmat4[icam] = np.matmul(rmat2, self.rmat1)
            self.havePointing = True

    def read_all_levine_fpg_files(self, fpg_file_list=None):
        default_fpg_file_list = ['fpg_pars.txt-', \
                                 'fpg_pars.txt-', \
                                 'fpg_pars.txt-', \
                                 'fpg_pars.txt-']
        # For each camera read in the separate fpg parameter file
        for icam in range(self.NCAM):
            if fpg_file_list == None:
                fpg_file = default_fpg_file_list[icam]
            else:
                fpg_file = fpg_file_list[icam]
            self.read_levine_fpg_file(icam, fpg_file)
        # We now have parameters for all 4 cameras in the parm_dict_list
        # parse the dictionary values into the working numpy arrays
        for icam in range(self.NCAM):
            pd = self.parm_dict_list[icam]
            self.eulcam[icam][0] = pd['ang1_cam1']
            self.eulcam[icam][1] = pd['ang2_cam1']
            self.eulcam[icam][2] = pd['ang3_cam1']
            self.optcon[icam][0] = pd['fl_cam1']
            self.optcon[icam][1] = pd['opt_coef1_cam1']
            self.optcon[icam][2] = pd['opt_coef2_cam1']
            self.optcon[icam][3] = pd['opt_coef3_cam1']
            self.optcon[icam][4] = pd['opt_coef4_cam1']
            self.optcon[icam][5] = pd['opt_coef5_cam1']
            self.asymang[icam] = pd['asymang_cam1']
            self.asymfac[icam] = pd['asymfac_cam1']
            for iccd in range(self.NCCD):
                self.ccdxy0[icam][iccd][0] = pd['x0_ccd{0:1d}_cam1'.format(iccd+1)]
                self.ccdxy0[icam][iccd][1] = pd['y0_ccd{0:1d}_cam1'.format(iccd+1)]
                self.pixsz[icam][iccd][0] = pd['pix_x_ccd{0:1d}_cam1'.format(iccd+1)]
                self.pixsz[icam][iccd][1] = pd['pix_y_ccd{0:1d}_cam1'.format(iccd+1)]
                self.ccdang[icam][iccd] = pd['ang_ccd{0:1d}_cam1'.format(iccd+1)]
                self.ccdtilt[icam][iccd][0] = pd['tilt_x_ccd{0:1d}_cam1'.format(iccd+1)]
                self.ccdtilt[icam][iccd][1] = pd['tilt_y_ccd{0:1d}_cam1'.format(iccd+1)]


    def read_levine_fpg_file(self, icam, fpg_file):
        gotParm = False
        parm_dict = {}
        if os.path.isfile(fpg_file):
            try:
                fpin = open(fpg_file, 'r')
                # Read in parameters
                dtypeseq = ['U20','i4','f16']
                dataBlock = np.genfromtxt(fpin, dtype=dtypeseq)
                parm_keys = dataBlock['f0']
                parm_fitted_flags = dataBlock['f1']
                parm_values = dataBlock['f2']
                # Now build dictionary of the parameters
                for i in range(len(parm_keys)):
                    parm_dict[parm_keys[i]] = parm_values[i]
                self.parm_dict_list[icam] = parm_dict
                gotParm = True
                print('Successful Focal Plane Geometry Read From {0}'.format(fpg_file))
            except:
                print('Could not open {0}!  Using Hard-coded Focal Plane Geometry from Levine_FPG read_levine_fpg_file()'.format(fpg_file))
        # If anything goes wrong with reading in parameters revert to hard coded version
        # or file was never given and default_fpg_file does not exist
        if not gotParm:
            #print('Using Hard-coded Focal Plane Geometry from Levine_FPG read_levine_fpg_file')
            # *** For now this hard code is just a filler need to actually fill in values for all cameras separately
            # to prepare parameters for dictionary
            # awk -v q="'" -v d=":" '{print q $1 q d $3 ",\"}' rfpg5_c1kb.txt
            if icam == 0:
                parm_dict = {'ang1_cam1' : 0.101588, \
                             'ang2_cam1' : -36.022035, \
                             'ang3_cam1' :  90.048315, \
                             'fl_cam1' :   145.948116, \
                             'opt_coef1_cam1' :   1.00000140, \
                             'opt_coef2_cam1' :  0.24779006, \
                             'opt_coef3_cam1' :  -0.22681254, \
                             'opt_coef4_cam1' :  10.78243356, \
                             'opt_coef5_cam1' :  -34.97817276, \
                             'asymang_cam1' :  0.00000000, \
                             'asymfac_cam1' :  1.00000000, \
                             'x0_ccd1_cam1' :  31.573417, \
                             'y0_ccd1_cam1' :  31.551637, \
                             'pix_x_ccd1_cam1' :  0.015000, \
                             'pix_y_ccd1_cam1' :  0.015000, \
                             'ang_ccd1_cam1' :  179.980833, \
                             'tilt_x_ccd1_cam1' :  0.000000, \
                             'tilt_y_ccd1_cam1' :  0.000000, \
                             'x0_ccd2_cam1' :  -0.906060, \
                             'y0_ccd2_cam1' :  31.536148, \
                             'pix_x_ccd2_cam1' :  0.015000, \
                             'pix_y_ccd2_cam1' :  0.015000, \
                             'ang_ccd2_cam1' :  180.000000, \
                             'tilt_x_ccd2_cam1' :  0.000000, \
                             'tilt_y_ccd2_cam1' :  0.000000, \
                             'x0_ccd3_cam1' :  -31.652818, \
                             'y0_ccd3_cam1' :  -31.438350, \
                             'pix_x_ccd3_cam1' :  0.015000, \
                             'pix_y_ccd3_cam1' :  0.015000, \
                             'ang_ccd3_cam1' :  -0.024851, \
                             'tilt_x_ccd3_cam1' :  0.000000, \
                             'tilt_y_ccd3_cam1' :  0.000000, \
                             'x0_ccd4_cam1' :  0.833161, \
                             'y0_ccd4_cam1' :  -31.458180, \
                             'pix_x_ccd4_cam1' :  0.015000, \
                             'pix_y_ccd4_cam1' :  0.015000, \
                             'ang_ccd4_cam1' :  0.001488, \
                             'tilt_x_ccd4_cam1' :  0.000000, \
                             'tilt_y_ccd4_cam1' :  0.000000}


            if icam == 1:
                parm_dict =  {'ang1_cam1':-0.179412,\
                              'ang2_cam1':-12.017260,\
                              'ang3_cam1':90.046500,\
                              'fl_cam1':145.989933,\
                              'opt_coef1_cam1':1.00000140,\
                              'opt_coef2_cam1':0.24069345,\
                              'opt_coef3_cam1':0.15391120,\
                              'opt_coef4_cam1':4.05433503,\
                              'opt_coef5_cam1':3.43136895,\
                              'asymang_cam1':0.00000000,\
                              'asymfac_cam1':1.00000000,\
                              'x0_ccd1_cam1':31.653635,\
                              'y0_ccd1_cam1':31.470291,\
                              'pix_x_ccd1_cam1':0.015000,\
                              'pix_y_ccd1_cam1':0.015000,\
                              'ang_ccd1_cam1':180.010890,\
                              'tilt_x_ccd1_cam1':0.000000,\
                              'tilt_y_ccd1_cam1':0.000000,\
                              'x0_ccd2_cam1':-0.827405,\
                              'y0_ccd2_cam1':31.491388,\
                              'pix_x_ccd2_cam1':0.015000,\
                              'pix_y_ccd2_cam1':0.015000,\
                              'ang_ccd2_cam1':180.000000,\
                              'tilt_x_ccd2_cam1':0.000000,\
                              'tilt_y_ccd2_cam1':0.000000,\
                              'x0_ccd3_cam1':-31.543794,\
                              'y0_ccd3_cam1':-31.550699,\
                              'pix_x_ccd3_cam1':0.015000,\
                              'pix_y_ccd3_cam1':0.015000,\
                              'ang_ccd3_cam1':-0.006624,\
                              'tilt_x_ccd3_cam1':0.000000,\
                              'tilt_y_ccd3_cam1':0.000000,\
                              'x0_ccd4_cam1':0.922834,\
                              'y0_ccd4_cam1':-31.557268,\
                              'pix_x_ccd4_cam1':0.015000,\
                              'pix_y_ccd4_cam1':0.015000,\
                              'ang_ccd4_cam1':-0.015464,\
                              'tilt_x_ccd4_cam1':0.000000,\
                              'tilt_y_ccd4_cam1':0.000000}

            if icam == 2:
                parm_dict = {'ang1_cam1':0.066596,\
                             'ang2_cam1':12.007750,\
                             'ang3_cam1':-89.889085,\
                             'fl_cam1':146.006602,\
                             'opt_coef1_cam1':1.00000140,\
                             'opt_coef2_cam1':0.23452229,\
                             'opt_coef3_cam1':0.33552009,\
                             'opt_coef4_cam1':1.92009863,\
                             'opt_coef5_cam1':12.48880182,\
                             'asymang_cam1':0.00000000,\
                             'asymfac_cam1':1.00000000,\
                             'x0_ccd1_cam1':31.615486,\
                             'y0_ccd1_cam1':31.413644,\
                             'pix_x_ccd1_cam1':0.015000,\
                             'pix_y_ccd1_cam1':0.015000,\
                             'ang_ccd1_cam1':179.993948,\
                             'tilt_x_ccd1_cam1':0.000000,\
                             'tilt_y_ccd1_cam1':0.000000,\
                             'x0_ccd2_cam1':-0.832993,\
                             'y0_ccd2_cam1':31.426621,\
                             'pix_x_ccd2_cam1':0.015000,\
                             'pix_y_ccd2_cam1':0.015000,\
                             'ang_ccd2_cam1':180.000000,\
                             'tilt_x_ccd2_cam1':0.000000,\
                             'tilt_y_ccd2_cam1':0.000000,\
                             'x0_ccd3_cam1':-31.548296,\
                             'y0_ccd3_cam1':-31.606976,\
                             'pix_x_ccd3_cam1':0.015000,\
                             'pix_y_ccd3_cam1':0.015000,\
                             'ang_ccd3_cam1':0.000298,\
                             'tilt_x_ccd3_cam1':0.000000,\
                             'tilt_y_ccd3_cam1':0.000000,\
                             'x0_ccd4_cam1':0.896018,\
                             'y0_ccd4_cam1':-31.569542,\
                             'pix_x_ccd4_cam1':0.015000,\
                             'pix_y_ccd4_cam1':0.015000,\
                             'ang_ccd4_cam1':-0.006464,\
                             'tilt_x_ccd4_cam1':0.000000,\
                             'tilt_y_ccd4_cam1':0.000000}

            if icam == 3:
                parm_dict = {'ang1_cam1':0.030756,\
                             'ang2_cam1':35.978116,\
                             'ang3_cam1':-89.976802,\
                             'fl_cam1':146.039793,\
                             'opt_coef1_cam1':1.00000140,\
                             'opt_coef2_cam1':0.23920416,\
                             'opt_coef3_cam1':0.13349450,\
                             'opt_coef4_cam1':4.77768896,\
                             'opt_coef5_cam1':-1.75114744,\
                             'asymang_cam1':0.00000000,\
                             'asymfac_cam1':1.00000000,\
                             'x0_ccd1_cam1':31.575820,\
                             'y0_ccd1_cam1':31.316510,\
                             'pix_x_ccd1_cam1':0.015000,\
                             'pix_y_ccd1_cam1':0.015000,\
                             'ang_ccd1_cam1':179.968217,\
                             'tilt_x_ccd1_cam1':0.000000,\
                             'tilt_y_ccd1_cam1':0.000000,\
                             'x0_ccd2_cam1':-0.890877,\
                             'y0_ccd2_cam1':31.363511,\
                             'pix_x_ccd2_cam1':0.015000,\
                             'pix_y_ccd2_cam1':0.015000,\
                             'ang_ccd2_cam1':180.000000,\
                             'tilt_x_ccd2_cam1':0.000000,\
                             'tilt_y_ccd2_cam1':0.000000,\
                             'x0_ccd3_cam1':-31.630470,\
                             'y0_ccd3_cam1':-31.716942,\
                             'pix_x_ccd3_cam1':0.015000,\
                             'pix_y_ccd3_cam1':0.015000,\
                             'ang_ccd3_cam1':-0.024359,\
                             'tilt_x_ccd3_cam1':0.000000,\
                             'tilt_y_ccd3_cam1':0.000000,\
                             'x0_ccd4_cam1':0.824159,\
                             'y0_ccd4_cam1':-31.728751,\
                             'pix_x_ccd4_cam1':0.015000,\
                             'pix_y_ccd4_cam1':0.015000,\
                             'ang_ccd4_cam1':-0.024280,\
                             'tilt_x_ccd4_cam1':0.000000,\
                             'tilt_y_ccd4_cam1':0.000000}

            self.parm_dict_list[icam] = parm_dict

    def sky_to_sc_mat(self, sc_ra_dec_roll):
        """Calculate the rotation matrix that will convert a vector in ra&dec
            into the spacecraft boresite frame
        """
        deg2rad = np.pi / 180.0
        # Define the 3 euler angles of rotation
        xeul = np.zeros((3,), dtype=np.double)
        xeul[0] = deg2rad * sc_ra_dec_roll[0]
        xeul[1] = np.pi/2.0 - deg2rad*sc_ra_dec_roll[1]
        xeul[2] = deg2rad * sc_ra_dec_roll[2] + np.pi
        # Generate the rotation matrix from the 3 euler angles
        self.rmat1 = self.eulerm323(xeul)

    def sc_to_cam_mat(self, eul):
        """Calculate the rotation matrix that will convert a vector in spacecraft
            into the a camera's coords
        """
        deg2rad = np.pi / 180.0
        # Generate the rotation matrix from the 3 euler angles
        xeul = deg2rad * eul
        return self.eulerm323(xeul)

    def eulerm323(self, eul):
        mat1 = self.rotm1(2, eul[0])
        mat2 = self.rotm1(1, eul[1])
        mata = np.matmul(mat2, mat1)
        mat1 = self.rotm1(2, eul[2])
        rmat = np.matmul(mat1, mata)
        return rmat

    def rotm1(self, ax, ang):
        mat = np.zeros((3,3), dtype=np.double)
        n1 = ax
        n2 = np.mod((n1+1), 3)
        n3 = np.mod((n2+1), 3)
        sinang = np.sin(ang)
        cosang = np.cos(ang)
        mat[n1][n1] = 1.0
        mat[n2][n2] = cosang
        mat[n3][n3] = cosang
        mat[n2][n3] = sinang
        mat[n3][n2] = -sinang
        return mat

    def sphereToCart(self, ras, decs):
        """ Convert 3d spherical coordinates to cartesian
        """
        deg2rad = np.pi / 180.0
        rarads = deg2rad * ras
        decrads = deg2rad * decs
        sinras = np.sin(rarads)
        cosras = np.cos(rarads)
        sindecs = np.sin(decrads)
        cosdecs = np.cos(decrads)
        vec0s = cosras * cosdecs
        vec1s = sinras * cosdecs
        vec2s = sindecs
        return vec0s, vec1s, vec2s

    def cartToSphere(self, vec):
        ra = 0.0
        dec = 0.0
        norm = np.sqrt(np.sum(vec*vec))
        if (norm > 0.0):
            dec = np.arcsin(vec[2] / norm)
            if (not vec[0] == 0.0) or (not vec[1] == 0.0):
                ra = np.arctan2(vec[1], vec[0])
                ra = np.mod(ra, 2.0*np.pi)
        return ra, dec

    def star_in_fov(self, lng, lat):
        deg2rad = np.pi / 180.0
        inView = False
        if lat > 70.0:
            vec0, vec1, vec2 = self.sphereToCart(lng, lat)
            vec = np.array([vec0, vec1, vec2], dtype=np.double)
            norm = np.sqrt(np.sum(vec*vec))
            if norm > 0.0:
                vec = vec / norm
                xlen = np.abs(np.arctan(vec[0]/vec[2]))
                ylen = np.abs(np.arctan(vec[1]/vec[2]))
                if (xlen <= (12.5 * deg2rad)) and (ylen <= (12.5 * deg2rad)):
                    inView = True
        return inView

    def optics_fp(self, icam, lng_deg, lat_deg):
        deg2rad = np.pi / 180.0
        thetar = np.pi / 2.0 - (lat_deg * deg2rad)
        tanth = np.tan(thetar)
        cphi = np.cos(deg2rad*lng_deg)
        sphi = np.sin(deg2rad*lng_deg)
        rfp0 = self.optcon[icam][0]*tanth
        noptcon = len(self.optcon[icam])
        ii = np.arange(1, noptcon)
        rfp = np.sum(self.optcon[icam][1:] * np.power(tanth, 2.0*(ii-1)))
        xytmp = np.zeros((2,), dtype=np.double)
        xytmp[0] = -cphi*rfp0*rfp
        xytmp[1] = -sphi*rfp0*rfp
        return self.make_az_asym(icam, xytmp)

    def make_az_asym(self, icam, xy):
        xyp = self.xyrotate(self.asymang[icam], xy)
        xypa = np.zeros_like(xyp)
        xypa[0] = self.asymfac[icam] * xyp[0]
        xypa[1] = xyp[1]
        xyout = self.xyrotate(-self.asymang[icam], xypa)
        return xyout

    def xyrotate(self, angle_deg, xin):
        deg2rad = np.pi / 180.0
        ca = np.cos(deg2rad * angle_deg)
        sa = np.sin(deg2rad * angle_deg)
        xyout = np.zeros_like(xin)
        xyout[0] = ca*xin[0] + sa*xin[1]
        xyout[1] = -sa*xin[0] + ca*xin[1]
        return xyout

    def mm_to_pix(self, icam, xy):
        """Convert focal plane to pixel location also need to add in the
            auxillary pixels added into FFIs
        """
        CCDWD_T=2048
        CCDHT_T=2058
        ROWA=44
        ROWB=44
        COLDK_T=20
        xya = np.copy(xy)
        xyb = np.zeros_like(xya)
        ccdpx = np.zeros_like(xya)
        fitpx = np.zeros_like(xya)
        if xya[0] >= 0.0:
            if xya[1] >= 0.0:
                iccd = 0
                xyb[0] = xya[0] - self.ccdxy0[icam][iccd][0]
                xyb[1] = xya[1] - self.ccdxy0[icam][iccd][1]
                xyccd = self.xyrotate(self.ccdang[icam][iccd], xyb)
                ccdpx[0] = (xyccd[0] / self.pixsz[icam][iccd][0]) - 0.5
                ccdpx[1] = (xyccd[1] / self.pixsz[icam][iccd][1]) - 0.5
                fitpx[0] = (CCDWD_T - ccdpx[0]) + CCDWD_T + 2*ROWA + ROWB - 1.0
                fitpx[1] = (CCDHT_T - ccdpx[1]) + CCDHT_T + 2*COLDK_T - 1.0
            else:
                iccd = 3
                xyb[0] = xya[0] - self.ccdxy0[icam][iccd][0]
                xyb[1] = xya[1] - self.ccdxy0[icam][iccd][1]
                xyccd = self.xyrotate(self.ccdang[icam][iccd], xyb)
                ccdpx[0] = (xyccd[0] / self.pixsz[icam][iccd][0]) - 0.5
                ccdpx[1] = (xyccd[1] / self.pixsz[icam][iccd][1]) - 0.5
                fitpx[0] = ccdpx[0] + CCDWD_T + 2*ROWA + ROWB
                fitpx[1] = ccdpx[1]
        else:
            if xya[1] >= 0.0:
                iccd = 1
                xyb[0] = xya[0] - self.ccdxy0[icam][iccd][0]
                xyb[1] = xya[1] - self.ccdxy0[icam][iccd][1]
                xyccd = self.xyrotate(self.ccdang[icam][iccd], xyb)
                ccdpx[0] = (xyccd[0] / self.pixsz[icam][iccd][0]) - 0.5
                ccdpx[1] = (xyccd[1] / self.pixsz[icam][iccd][1]) - 0.5
                fitpx[0] = (CCDWD_T - ccdpx[0]) + ROWA - 1.0
                fitpx[1] = (CCDHT_T - ccdpx[1]) + CCDHT_T + 2*COLDK_T - 1.0
            else:
                iccd = 2
                xyb[0] = xya[0] - self.ccdxy0[icam][iccd][0]
                xyb[1] = xya[1] - self.ccdxy0[icam][iccd][1]
                xyccd = self.xyrotate(self.ccdang[icam][iccd], xyb)
                ccdpx[0] = (xyccd[0] / self.pixsz[icam][iccd][0]) - 0.5
                ccdpx[1] = (xyccd[1] / self.pixsz[icam][iccd][1]) - 0.5
                fitpx[0] = ccdpx[0] + ROWA
                fitpx[1] = ccdpx[1]

        return iccd, ccdpx, fitpx

    def mm_to_pix_single_ccd(self, icam, xy, iccd):
        """Convert focal plane to pixel location also need to add in the
            auxillary pixels added into FFIs
        """
        CCDWD_T=2048
        CCDHT_T=2058
        ROWA=44
        ROWB=44
        COLDK_T=20
        xya = np.copy(xy)
        xyb = np.zeros_like(xya)
        ccdpx = np.zeros_like(xya)
        fitpx = np.zeros_like(xya)
        if iccd == 0:
            xyb[0] = xya[0] - self.ccdxy0[icam][iccd][0]
            xyb[1] = xya[1] - self.ccdxy0[icam][iccd][1]
            xyccd = self.xyrotate(self.ccdang[icam][iccd], xyb)
            ccdpx[0] = (xyccd[0] / self.pixsz[icam][iccd][0]) - 0.5
            ccdpx[1] = (xyccd[1] / self.pixsz[icam][iccd][1]) - 0.5
            fitpx[0] = (CCDWD_T - ccdpx[0]) + CCDWD_T + 2*ROWA + ROWB - 1.0
            fitpx[1] = (CCDHT_T - ccdpx[1]) + CCDHT_T + 2*COLDK_T - 1.0
        if iccd == 3:
            xyb[0] = xya[0] - self.ccdxy0[icam][iccd][0]
            xyb[1] = xya[1] - self.ccdxy0[icam][iccd][1]
            xyccd = self.xyrotate(self.ccdang[icam][iccd], xyb)
            ccdpx[0] = (xyccd[0] / self.pixsz[icam][iccd][0]) - 0.5
            ccdpx[1] = (xyccd[1] / self.pixsz[icam][iccd][1]) - 0.5
            fitpx[0] = ccdpx[0] + CCDWD_T + 2*ROWA + ROWB
            fitpx[1] = ccdpx[1]
        if iccd == 1:
            xyb[0] = xya[0] - self.ccdxy0[icam][iccd][0]
            xyb[1] = xya[1] - self.ccdxy0[icam][iccd][1]
            xyccd = self.xyrotate(self.ccdang[icam][iccd], xyb)
            ccdpx[0] = (xyccd[0] / self.pixsz[icam][iccd][0]) - 0.5
            ccdpx[1] = (xyccd[1] / self.pixsz[icam][iccd][1]) - 0.5
            fitpx[0] = (CCDWD_T - ccdpx[0]) + ROWA - 1.0
            fitpx[1] = (CCDHT_T - ccdpx[1]) + CCDHT_T + 2*COLDK_T - 1.0
        if iccd == 2:
            xyb[0] = xya[0] - self.ccdxy0[icam][iccd][0]
            xyb[1] = xya[1] - self.ccdxy0[icam][iccd][1]
            xyccd = self.xyrotate(self.ccdang[icam][iccd], xyb)
            ccdpx[0] = (xyccd[0] / self.pixsz[icam][iccd][0]) - 0.5
            ccdpx[1] = (xyccd[1] / self.pixsz[icam][iccd][1]) - 0.5
            fitpx[0] = ccdpx[0] + ROWA
            fitpx[1] = ccdpx[1]

        return ccdpx, fitpx

    def radec2pix(self, ras, decs):
        """ After the rotation matrices are defined to the actual
            ra and dec to pixel coords mapping
        """
        nStar = len(ras)
        inCamera = np.array([], dtype=np.int)
        ccdNum = np.array([], dtype=np.int)
        fitsxpos = np.array([], dtype=np.double)
        fitsypos = np.array([], dtype=np.double)
        ccdxpos = np.array([], dtype=np.double)
        ccdypos = np.array([], dtype=np.double)

        deg2rad = np.pi / 180.0
        if self.havePointing == True:
            # Convert ra and dec spherical coords to cartesian
            vec0s, vec1s, vec2s = self.sphereToCart(ras, decs)
            for i in range(nStar):
                curVec = np.array([vec0s[i], vec1s[i], vec2s[i]], dtype=np.double)
                # Find the new vector in all cameras
                for j in range(self.NCAM):
                    # Do the rotation from ra dec coords to camera coords
                    camVec = np.matmul(self.rmat4[j], curVec)
                    # Get the longitude and latitude of camera coords position
                    lng, lat = self.cartToSphere(camVec)
                    lng = lng / deg2rad
                    lat = lat / deg2rad
                    if self.star_in_fov(lng, lat):
                        # Get the xy focal plane position in mm
                        xyfp = self.optics_fp(j, lng, lat)
                        # Convert mm to pixels
                        iccd, ccdpx, fitpx = self.mm_to_pix(j, xyfp)
                        inCamera = np.append(inCamera, j+1) # Als code is base 0 convert to base 1
                        ccdNum = np.append(ccdNum, iccd+1) # ""
                        fitsxpos = np.append(fitsxpos, fitpx[0])
                        fitsypos = np.append(fitsypos, fitpx[1])
                        ccdxpos = np.append(ccdxpos, ccdpx[0])
                        ccdypos = np.append(ccdypos, ccdpx[1])

        else:
            print('Spacecraft Pointing Not specified!')

        return inCamera, ccdNum, fitsxpos, fitsypos, ccdxpos, ccdypos

    def radec2pix_nocheck_single(self, ras, decs, cam, iccd):
        """
            ra and dec to pixel coords mapping
            With no checks and assuming a single target and detector
            Supports minimizing for reverse mode
        """
        deg2rad = np.pi / 180.0
        # Convert ra and dec spherical coords to cartesian
        vec0s, vec1s, vec2s = self.sphereToCart(ras, decs)
        curVec = np.array([vec0s, vec1s, vec2s], dtype=np.double)
        j = cam
        # Do the rotation from ra dec coords to camera coords
        camVec = np.matmul(self.rmat4[j], curVec)
        # Get the longitude and latitude of camera coords position
        lng, lat = self.cartToSphere(camVec)
        lng = lng / deg2rad
        lat = lat / deg2rad
        # Get the xy focal plane position in mm
        xyfp = self.optics_fp(j, lng, lat)
        # Convert mm to pixels
        ccdpx, fitpx = self.mm_to_pix_single_ccd(j, xyfp, iccd)
        ccdNum = iccd+1
        fitsxpos = fitpx[0]
        fitsypos = fitpx[1]
        ccdxpos = ccdpx[0]
        ccdypos = ccdpx[1]

        return ccdNum, fitsxpos, fitsypos, ccdxpos, ccdypos, lat

class TESS_Spacecraft_Pointing_Data:
    #Hard coded spacecraft pointings by Sector
    # When adding sectors the arg2 needs to end +1 from sector
    #  due to the np.arange function ending at arg2-1
    sectors = np.arange(1,40, dtype=np.int)

    # Arrays are borken up into the following sectors:
    # Line 1: Sectors 1-5
    # Line 2: Secotrs 6-9
    # Line 3: Sectors 10-13
    # Line 4: Sectors 14-17
    # Line 5: Sectors 18-22
    # Line 6: Sectors 23-26
    # Line 7: Sectors 27-30
    # Line 8: Sectors 31-34
    # Line 9: Sectors 35-38
    # Line 10: Sectors 39
    ### NOTE IF you add Sectors be sure to update the allowed range
    ### for sectors in argparse arguments!!!
    ras = np.array([352.6844,16.5571,36.3138,55.0070,73.5382, \
                    92.0096,110.2559,128.1156,145.9071,\
                    165.0475,189.1247,229.5885,298.6671, \
                    276.7169,280.3985,282.4427,351.2381,\
                    16.1103,60.2026,129.3867,171.7951,197.1008,\
                    217.2879,261.4516,265.6098,270.1381,\
                    326.8525,357.2944,18.9190,38.3564,\
                    57.6357,77.1891,96.5996,115.2951,\
                    133.2035,150.9497,170.2540,195.7176,\
                    242.1981], dtype=np.float)

    decs = np.array([-64.8531,-54.0160,-44.2590,-36.6420,-31.9349, \
                     -30.5839,-32.6344,-37.7370,-45.3044,\
                     -54.8165,-65.5369,-75.1256,-76.3281,\
                     62.4756,64.0671,66.1422,57.8456, \
                     67.9575,76.2343,75.2520,65.1924,53.7434, \
                     43.8074,63.1181,61.9383,61.5637,\
                     -72.4265,-63.0056,-52.8296,-43.3178,\
                     -35.7835,-31.3957,-30.7848,-33.7790,\
                     -39.6871,-47.7512,-57.3725,-67.8307,\
                     -76.3969], dtype=np.float)

    rolls = np.array([-137.8468,-139.5665,-146.9616,-157.1698,-168.9483, \
                      178.6367,166.4476,155.3091,145.9163,\
                      139.1724,138.0761,153.9773,-161.0622,\
                      32.2329,55.4277,79.4699,41.9686,\
                      40.5453,19.6463,334.5689,317.9495,319.6992,\
                      327.4246,317.2624,339.5293,0.6038,\
                      214.5061,222.5216,219.7970,212.0441,\
                      201.2334,188.6263,175.5369,163.1916,\
                      152.4006,143.7306,138.1685,139.3519,\
                      161.5986], dtype=np.float)

    camSeps = np.array([36.0, 12.0, 12.0, 36.0], dtype=np.float)

    def __init__(self, trySector=None, fpgParmFileList=None):
        # Convert S/C boresite pointings to ecliptic coords for each camera
        # If trySector is set only keep the single requested sector
        if not trySector is None:
            idx = np.where(self.sectors == trySector)[0]
            self.sectors = self.sectors[idx]
            self.ras = self.ras[idx]
            self.decs = self.decs[idx]
            self.rolls = self.rolls[idx]
        nPoints = len(self.sectors)
        self.camRa = np.zeros((4, nPoints), dtype=np.float)
        self.camDec = np.zeros((4, nPoints), dtype=np.float)
        # Convert S/C boresite ra and dec to camera ra and dec
        for iPnt in range(nPoints):
            curra = self.ras[iPnt]
            curdec = self.decs[iPnt]
            curroll = self.rolls[iPnt]
            camposangs = np.array([180.0-curroll, 180.0-curroll, \
                                   360.0-curroll, 360.0-curroll])
            camposangs = np.mod(camposangs, 360.0)
            for iCam in range(4):
                # Need to correct s/c roll to posang
                pang = camposangs[iCam]
                camra, camdec = get_radec_from_posangsep(curra, curdec, \
                                            pang, self.camSeps[iCam])
                self.camRa[iCam,iPnt] = camra
                self.camDec[iCam,iPnt] = camdec
                # Just for testing camera coords
                # compare to published values
#                print('{:d} {:d} {:f} {:f}'.format(self.sectors[iPnt],iCam+1,\
#                         self.camRa[iCam,iPnt], self.camDec[iCam,iPnt]))
        # For every pointing make a Levine pointing class object
        self.fpgObjs = []
        fpg_file_list=None
        if not fpgParmFileList is None:
            fpg_file_list=fpgParmFileList
        for iPnt in range(nPoints):
            sc_ra_dec_roll =  np.array([self.ras[iPnt], self.decs[iPnt], self.rolls[iPnt]])
            self.fpgObjs.append(Levine_FPG(sc_ra_dec_roll, fpg_file_list=fpg_file_list))

def get_radec_from_posangsep(ra, dec, pa, sep):
    deg2rad = np.pi/180.0
    rad2deg = 180.0/np.pi
    twopi = 2.0*np.pi
    pidtwo = np.pi/2.0
    rar = ra*deg2rad
    decr = dec*deg2rad
    par = pa*deg2rad
    sepr = sep*deg2rad
    c = pidtwo - decr
    bigB = par
    a = sepr
    b = np.arccos((np.cos(c)*np.cos(a) + np.sin(c)*np.sin(a)*np.cos(bigB)))
    newdec = pidtwo - b
    delalp = np.arccos(np.min([(np.cos(sepr)-np.sin(decr)*np.sin(newdec))/(np.cos(decr)*np.cos(newdec)),1.0]))
    if pa > 180.0:
        newra = rar - delalp
    else:
        newra = rar + delalp
#    print(pa, newra*rad2deg, rar*rad2deg, delalp*rad2deg)
    newra = np.mod(newra, twopi)
    return newra*rad2deg, newdec*rad2deg


## [Mast Query]
def mastQuery(request,proxy_uri=None):

    host='mast.stsci.edu'
    # Grab Python Version
    version = ".".join(map(str, sys.version_info[:3]))

    # Create Http Header Variables
    headers = {"Content-type": "application/x-www-form-urlencoded",
               "Accept": "text/plain",
               "User-agent":"python-requests/"+version}

    # Encoding the request as a json string
    requestString = json.dumps(request)
    requestString = urlencode(requestString)

    # opening the https connection
    if None == proxy_uri:
        conn = httplib.HTTPSConnection(host)
    else:
        port = 443
        url = urlparse(proxy_uri)
        conn = httplib.HTTPSConnection(url.hostname,url.port)

        if url.username and url.password:
            auth = '%s:%s' % (url.username, url.password)
            headers['Proxy-Authorization'] = 'Basic ' + str(base64.b64encode(auth.encode())).replace("b'", "").replace("'", "")
        conn.set_tunnel(host, port, headers)

    # Making the query
    conn.request("POST", "/api/v0/invoke", "request="+requestString, headers)

    # Getting the response
    resp = conn.getresponse()
    head = resp.getheaders()
    content = resp.read().decode('utf-8')

    # Close the https connection
    conn.close()

    return head,content
## [Mast Query]

def ticConeSearch(coord):
    #Performing a 10 arc second radius cone search of the TIC and taking the brightest object:
    request = { "service":"Mast.Catalogs.Tic.Cone",
                "params":{
                    "ra":coord.ra.deg,
                    "dec":coord.dec.deg,
                    "radius":10/3600},
                "format":"json",
                "timeout":10}

    headers,outString = mastQuery(request)

    outData = json.loads(outString)

    df = pd.json_normalize(outData['data'])

    return df.loc[np.argmin(df['Tmag'])]

def ticIdSearch(tic):
    #Performing a search of the TIC with a tic ID
    '''
    for split in [ticStringList[parts[i]:parts[i+1]] for i in range(len(parts)-1)]:
    len(split)
    request= {'service':'Mast.Catalogs.Filtered.Tic',
    'params':{'columns':'*', 'filters':[{'paramName':'ID', 'values':split}]},
    'format':'json', 'removenullcolumns':True}
    startTime = time.time()
    while True:
    headers, outString = mastQuery(request)
    outObject = json.loads(outString)
    #allData.append(outObject)
    if outObject['status'] != 'EXECUTING':
      break
    if time.time() - startTime >30:
      print(\"Working...\")
      startTime = time.time()
    time.sleep(5)
    for ni in range(len(outObject['data'])):
      tess_df=tess_df.append({col:outObject['data'][ni][col] for col in cols},ignore_index=True)
    print(\"appended\")
    time.sleep(5)
    '''
    while True:
        request = { "service":"Mast.Catalogs.Filtered.Tic",
                    "params":{'columns':'*',
                              'filters':[{'paramName':'ID', 'values':str(int(tic))}]},
                    "format":"json",
                    'removenullcolumns':True}

        headers,outString = mastQuery(request)

        outData = json.loads(outString)
        if outData['status'] != 'EXECUTING':
            break
    print(outData)

    df = pd.json_normalize(outData['data'])
    return df.iloc[0]

def SectFromCoords(coord=None,tic=None):
    assert not (coord is None and tic is None)
    scinfo = TESS_Spacecraft_Pointing_Data()
    if tic is None:
        ticdat = ticConeSearch(coord)
        tic = ticdat['ID']
    else:
        ticdat = ticIdSearch(tic)
        if coord is None:
            coord=SkyCoord(ticdat['ra']*u.deg,ticdat['dec']*u.deg)

    findAny=False
    sects=[]
    for idxSec,curSec in enumerate(scinfo.sectors):
        starInCam, starCcdNum, starFitsXs, starFitsYs, starCcdXs, starCcdYs = scinfo.fpgObjs[idxSec].radec2pix(\
                   np.array([coord.ra.deg]), np.array([coord.dec.deg]))
        for jj, cam in enumerate(starInCam):
            # SPOC calibrated FFIs have 44 collateral pixels in x and are 1 based
            xUse = starCcdXs[jj] + 45.0
            yUse = starCcdYs[jj] + 1.0
            xMin = 44.0
            ymaxCoord = 2049
            xmaxCoord = 2093
            if xUse>xMin and yUse>0 and xUse<xmaxCoord and yUse<ymaxCoord:
                findAny=True
                sects+=[curSec]
    return tic, ticdat, sects