# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------
# Copyright (C) 2012
# Andy Pavlo - http://www.cs.brown.edu/~pavlo/
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
import os
import logging
from pprint import pprint, pformat

LOG = logging.getLogger(__name__)

basedir = os.getcwd()
sys.path.append(os.path.join(basedir, "tools"))

import pymongo

from denormalizer import Denormalizer
from design_deserializer import Deserializer

from api.abstractcoordinator import AbstractCoordinator
from api.message import *

class ReplayCoordinator(AbstractCoordinator):
    DEFAULT_CONFIG = [
        ("dataset", "Name of the dataset replay will be executed on (Change None to valid dataset name)", "None"),
        ("metadata", "Name of the metadata replay will execute (Change None to valid metadata name)", "None"),
     ]
    
    def benchmarkConfigImpl(self):
        return self.DEFAULT_CONFIG
    ## DEF

    def initImpl(self, config, channels):
        return dict()
    ## DEF
    
    def loadImpl(self, config, channels):
        return dict()
    ## DEF
    
    def prepare(self):
        # STEP 0: Get the current metadata and dataset
        metadata_db = self.conn[self.config['replay']['metadata']]
        dataset_db = self.conn[self.config['replay']['dataset']]
        
        # STEP 1: Reconstruct database and workload based on the given design
        design = self.getDesign(self.config['default']['design'])
        d = Denormalizer(metadata_db, dataset_db, design)
        d.process()
        
        # STEP 1.5: Put indexs on the dataset_db based on the given design
        self.setIndexes(dataset_db, design)
    ## DEF
    
    def setIndexes(self, dataset_db, design):
        LOG.info("Creating indexes")
        for col_name in design.getCollections():
            dataset_db[col_name].drop_indexes()
            #self.dataset_db[col_name].
            indexes = design.getIndexes(col_name)
            # The indexes is a list of tuples
            for tup in indexes:
                index_list = [ ]
                for element in tup:
                    index_list.append((str(element), pymongo.ASCENDING))
                ## FOR
                dataset_db[col_name].ensure_index(index_list)
            ## FOR
        ## FOR
    ## DEF
    
    def getDesign(self, design):
        assert design, "design path is empty"

        deserializer = Deserializer(design)
        
        design = deserializer.Deserialize()
        LOG.info("current design \n%s" % design)

        return design
    ## DEF
## CLASS