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
from __future__ import with_statement

import os
import sys
import fileinput
import time
import logging
from pprint import pformat
from pymongo import Connection

# Third-Party Dependencies
basedir = os.path.realpath(os.path.dirname(__file__))
sys.path.append(os.path.join(basedir, "../../libs"))
import argparse
import mongokit

# MongoDB-Designer
sys.path.append(os.path.join(basedir, ".."))
import workload_info
import parser
import reconstructor
from traces import *
from workload import AbstractConvertor
from workload import sessionizer
from util import *
from util.histogram import Histogram

LOG = logging.getLogger(__name__)

## ==============================================
## MongoSniff Trace Convertor
## ==============================================
class MongoSniffConvertor(AbstractConvertor):
    
    def __init__(self, metadata_db, dataset_db):
        super(MongoSniffConvertor, self).__init__()
        self.metadata_db = metadata_db
        self.dataset_db = dataset_db
        
        # The WORKLOAD collection is where we stores sessions+operations
        self.workload_col = self.metadata_db[constants.COLLECTION_WORKLOAD]
        
        # The SCHEMA collection is where we will store the metadata information that
        # we will derive from the RECREATED database
        self.schema_col = self.metadata_db[constants.COLLECTION_SCHEMA]
        
        pass
    ## DEF
        
    def process(self):
        if not self.no_load:
            self.parseWorkload(sys.stdin)
            
        if not self.no_reconstruct:
            self.reconstructDatabase()
            
        if not self.no_sessionizer:
            self.sessionizeWorkload()
    ## DEF
    
    ## ----------------------------------------------
    ## WORKLOAD PARSING + LOADING
    ## ----------------------------------------------
    def parseWorkload(self, fd):
        # Create the Parser object that will go to town on our input file 
        p = parser.Parser(workload_col, fd)
        
        # Stop on Error
        if self.stop_on_error:
            LOG.warn("Will stop processing if invalid input is found")
            p.stop_on_error = True
        # Processing Skip
        if self.skip:
            LOG.warn("Will skip processing the first %d lines" % self.skip)
            p.op_skip =  self.skip
        # Processing Limit
        if self.limit:
            LOG.warn("Will stop processing after %d operations are processed" % self.limit)
            p.op_limit =  self.limit
        
        # Clear our existing data
        if self.clean: p.clean()
        
        # Bombs away!
        LOG.info("Processing mongosniff input")
        p.process()
        LOG.info("Finishing processing")
        LOG.info("Added %d sessions with %d operations to '%s'" % (\
            p.getSessionCount(), p.getOpCount(), workload_col.full_name))
        LOG.info("Skipped Responses: %d" % p.getOpSkipCount())
    ## IF
    
    ## ----------------------------------------------
    ## DATABASE RECONSTRUCTION
    ## ----------------------------------------------
    def reconstructDatabase(self):
        # Create a Reconstructor that will use the WORKLOAD_COL to regenerate
        # the original database and extract a schema catalog.
        r = reconstructor.Reconstructor(self.workload_col, self.dataset_db, self.schema_col)
        
        # Clear our existing data
        if self.clean: r.clean()
        
        # Bombs away!
        r.process()
        LOG.info("Processed %d sessions with %d operations into '%s'" % (\
                 r.getSessionCount(), r.getOpCount(), self.dataset_db.name))
        LOG.info("Skipped Operations: %d" % r.getOpSkipCount())
        LOG.info("Fixed Operations: %d" % r.getOpFixCount())
        LOG.info("Collection Sizes:\n%s" % pformat(r.getCollectionCounts()))
    ## DEF
    
    ## ----------------------------------------------
    ## WORKLOAD SESSIONIZATION
    ## ----------------------------------------------
    def sessionizeWorkload(self):
        LOG.info("Sessionizing sample workload")
        
        s = sessionizer.Sessionizer()
        
        # We first feed in all of the operations in for each session
        nextSessId = -1
        origTotal = 0
        origHistogram = Histogram()
        for sess in self.workload_col.find():
            s.process(sess['session_id'], sess['operations'])
            nextSessId = max(nextSessId, sess['session_id'])
            origHistogram.put(len(sess['operations']))
            origTotal += len(sess['operations'])
        ## FOR
        LOG.info("ORIG - Sessions: %d" % origHistogram.getSampleCount())
        LOG.info("ORIG - Avg Ops per Session: %.2f" % (origTotal / float(origHistogram.getSampleCount())))
        
        # Then split them into separate sessions
        s.calculateSessions()
        newTotal = 0
        newHistogram = Histogram()
        for sess in self.workload_col.find():
            newSessions = s.sessionize(sess, nextSessId)
            nextSessId += len(newSessions)
            
            # XXX: Mark the original session as 'deletable'
            sess['deletable'] = True
            # sess.save()
            
            # And then add all of our new sessions
            LOG.info("Split Session %d [%d ops] into %d separate sessions" % (sess['session_id'], len(sess['operations']), len(newSessions)))
            # self.workload_col.save(newSessions)
            
            # Count the number of operations so that can see the change
            totalOps = 0
            for newSess in newSessions:
                newOpCtr = len(newSess['operations'])
                totalOps += newOpCtr
                newHistogram.put(newOpCtr)
                LOG.debug("Session %d -> %d Ops" % (newSess['session_id'], newOpCtr))
            # Make sure that all of our operations end up in a session
            assert len(sess['operations']) == totalOps, \
                "Expected %d operations, but new sessions only had %d" % (len(sess['operations']), totalOps)
            newTotal += totalOps
        ## FOR
        LOG.info("NEW  - Sessions: %d" % newHistogram.getSampleCount())
        LOG.info("NEW  - Avg Ops per Session: %.2f" % (newTotal / float(newHistogram.getSampleCount())))
        LOG.info("NEW - Ops per Session\n%s" % newHistogram)
          
        return
    ## DEF
## CLASS


    
