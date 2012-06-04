# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------
# Copyright (C) 2012 by Brown University
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
# IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
# -----------------------------------------------------------------------

import sys
import itertools
import logging
import math
import functools
from pprint import pformat

from util.histogram import Histogram
from util import mathutil

LOG = logging.getLogger(__name__)

class Sessionizer:
    """Takes a series of operations and figures out session boundaries"""
    
    def __init__(self):
        self.op_ctr = 0
        
        # Reverse look-up for op hashes
        self.op_hash_xref = { }
        
        # TODO: Remove?
        self.sessionBoundaries = set()
        
        # Mapping from SessionId -> Operations
        self.sessOps = { }
        pass
    ## DEF
    
    def process(self, sessId, operations):
        """Process a list of operations from a single connection."""
        self.sessOps[sessId] = [ ]
        lastOp = None
        ctr = 0
        for op in operations:
            if not "resp_time" in op: continue
            assert "query_hash" in op, \
                "Missing hash in operation %d" % op["query_id"]
            
            if lastOp:
                assert op["query_time"] >= lastOp["resp_time"]
                # Seconds -> Milliseconds
                diff = (op["query_time"]*1000) - (lastOp["resp_time"]*1000)
                self.sessOps[sessId].append((lastOp, op, diff))
            lastOp = op
            ctr += 1
        ## FOR
        self.op_ctr += ctr
        LOG.debug("Examined %d operations for session %d [total=%d]" % (ctr, sessId, self.op_ctr))
    ## DEF
    
    def calculateSessions(self):
        # Calculate outliers using the quartile method
        # http://en.wikipedia.org/wiki/Quartile#Computing_methods
        LOG.info("Calculating time difference for operations in %d sessions" % len(self.sessOps))
        
        # Get the full list of all the time differences
        allDiffs = [ ]
        for clientOps in self.sessOps.values():
            allDiffs += [x[-1] for x in clientOps]
        allDiffs = sorted(allDiffs)
        numDiffs = len(allDiffs)

        #print "\n".join(map(str, allDiffs))
        
        # Lower + Upper Quartiles
        lowerQuartile, upperQuartile = mathutil.quartiles(allDiffs)
        
        # Interquartile Range
        iqr = (upperQuartile - lowerQuartile) * 1.5
        
        if LOG.isEnabledFor(logging.DEBUG):
            LOG.debug("Calculating stats for %d op pairs" % len(allDiffs))
            LOG.debug("  Lower Quartile: %s" % lowerQuartile)
            LOG.debug("  Upper Quartile: %s" % upperQuartile)
            LOG.debug("  IQR: %s" % iqr)
        
        # Go through operations for each client and identify the
        # pairs of operations that are above the IQR in the upperQuartile
        opHist = Histogram()
        prevOpHist = Histogram()
        nextOpHist = Histogram()
        threshold = upperQuartile + iqr
        for sessId, clientOps in self.sessOps.iteritems():
            for op0, op1, opDiff in clientOps:
                if opDiff >= threshold:
                    prevOpHist.put(op0["query_hash"])
                    nextOpHist.put(op1["query_hash"])
                    opHist.put((op0["query_hash"], op1["query_hash"]))
            ## FOR
        ## FOR
        if LOG.isEnabledFor(logging.DEBUG):
            LOG.debug("Outlier Op Hashes:\n%s" % opHist)
        
        # I guess at this point we can just compute the outliers
        # again for the pairs of operations that have a time difference
        # outlier. We won't use the IQR. We'll just take the upper quartile
        # because that seems to give us the right answer
        outlierCounts = sorted(opHist.getCounts())
        lowerQuartile, upperQuartile = mathutil.quartiles(outlierCounts)
        
        if LOG.isEnabledFor(logging.DEBUG):
            LOG.debug("Calculating stats for %d count outliers" % len(outlierCounts))
            LOG.debug("  Lower Quartile: %s" % lowerQuartile)
            LOG.debug("  Upper Quartile: %s" % upperQuartile)
        
        outlierHashes = set()
        for cnt in outlierCounts:
            if cnt >= upperQuartile:
                outlierHashes |= set(opHist.getValuesForCount(cnt))
        ## FOR
        LOG.info("Found %d outlier hashes" % len(outlierHashes))
        
        sys.exit(1)
        
        # TODO: Now that we've populated these histograms, we need a way
        # to determine whether they are truly new sessions or not.

        # TODO: Once we have our session boundaries, we need to then
        # loop through each of the sessOps again and generate our
        # boundaries
        for sessId, clientOps in self.sessOps.iteritems():
            ip1, ip2, uid = sessId
            
            lastOp = None
            sess = None
            for op in clientOps:
                if lastOp:
                    sess["operations"].append(lastOp)
                    if (lastOp["query_hash"], op["query_hash"]) in self.sessionBoundaries:
                        sess = None
                if not sess:
                    sess = Session()
                    sess["ip_client"] = ip1
                    sess["ip_server"] = ip2
                    sess["session_id"] = uid
                    sess["operations"] = [ ]            
                lastOp = op
            ## FOR
            if lastOp: sess["operations"].append(lastOp)
        
        pass
    ## FOR
    
    
    
## CLASS