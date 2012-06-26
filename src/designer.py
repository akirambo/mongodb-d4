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
import itertools
import logging

# mongodb-d4
import catalog
from costmodel import costmodel
from search import InitialDesigner, DesignCandidate, bbsearch
from util import *

LOG = logging.getLogger(__name__)

## ==============================================
## Designer
## This is the central object that will have all of the
## methods needed to pre-compute the catalog and then
## execute the design search
## ==============================================
class Designer():

    def __init__(self, cparser, metadata_db, dataset_db):
        # SafeConfigParser
        self.cparser = cparser
        
        # The metadata database will contain:
        #   (1) Collection catalog
        #   (2) Workload sessions
        #   (3) Workload stats
        self.metadata_db = metadata_db
        
        # The dataset database will contain a reconstructed
        # invocation of the database.
        # We need this because the main script will need to
        # compute whatever stuff that it needs
        self.dataset_db = dataset_db
        
        self.initialSolution = None
        self.finalSolution = None

        self.page_size = self.cparser.getint(config.SECT_CLUSTER, 'page_size')
        self.sample_rate = self.cparser.getint(config.SECT_DESIGNER, 'sample_rate')
        
    ## DEF

    def setOptionsFromArguments(self, args):
        """Set the internal parameters of the Designer based on command-line arguments"""
        for key in args:
            LOG.debug("%s => %s" % (key, args[key]))
            self.__dict__[key] = args[key]
        ## FOR
    ## DEF

    def getCollectionCatalog(self):
        """Return a dict of collection catalog objects"""
        collectionStats = { }
        for stats in self.metadata_db[constants.COLLECTION_SCHEMA].find():
            collectionStats[stats.name] = stats
        return collectionStats
    ## DEF

    ## -------------------------------------------------------------------------
    ## INPUT PROCESSING
    ## -------------------------------------------------------------------------

    def processMongoInput(self, fd, no_load=False, no_post_process=False):
        import inputs.mongodb

        # MongoDB Trace
        convertor = inputs.mongodb.MongoSniffConverter( \
            self.metadata_db, \
            self.dataset_db, \
            fd \
        )
        convertor.stop_on_error = self.stop_on_error
        convertor.no_mongo_parse = self.no_mongo_parse
        convertor.no_mongo_reconstruct = self.no_mongo_reconstruct
        convertor.no_mongo_sessionizer = self.no_mongo_sessionizer
        convertor.mongo_skip = self.mongo_skip
        convertor.mongo_limit = self.mongo_limit

        convertor.process(\
            no_load=no_load,\
            no_post_process=no_post_process,\
            page_size=self.page_size,\
        )
    ## DEF

    def processMySQLInput(self, no_load=False, no_post_process=False):
        from inputs.mysql import MySQLConverter

        # MySQL Trace
        convertor = MySQLConverter( \
            self.metadata_db,\
            self.dataset_db, \
            dbHost=self.cparser.get(config.SECT_MYSQL, 'host'), \
            dbPort=self.cparser.getint(config.SECT_MYSQL, 'port'), \
            dbName=self.cparser.get(config.SECT_MYSQL, 'name'), \
            dbUser=self.cparser.get(config.SECT_MYSQL, 'user'), \
            dbPass=self.cparser.get(config.SECT_MYSQL, 'pass'))

        # Process the inputs and then save the results in mongodb
        convertor.process( \
            no_load=no_load, \
            no_post_process=no_post_process, \
            page_size=self.page_size, \
        )
    ## DEF

    ## -------------------------------------------------------------------------
    ## DESIGNER EXECUTION
    ## -------------------------------------------------------------------------

    def search(self):
        """Perform the actual search for a design"""
        cmConfig = {
            'weight_network': self.cparser.getfloat(config.SECT_COSTMODEL, 'weight_network'),
            'weight_disk':    self.cparser.getfloat(config.SECT_COSTMODEL, 'weight_disk'),
            'weight_skew':    self.cparser.getfloat(config.SECT_COSTMODEL, 'weight_skew'),
            'nodes':          self.cparser.getint(config.SECT_CLUSTER, 'nodes'),
            'max_memory':     self.cparser.getint(config.SECT_CLUSTER, 'node_memory'),
            'skew_intervals': self.cparser.getint(config.SECT_COSTMODEL, 'time_intervals'),
            'address_size':   self.cparser.getint(config.SECT_COSTMODEL, 'address_size')
        }

        collectionsDict = dict([ (c['name'], c) for c in self.metadata_db.Collection.fetch()])

        # TODO: This is probably a bad idea because it means that we will have
        #       to bring the entire collection into RAM in order to keep processing it
        workload = [x for x in self.metadata_db.Session.fetch()]

        # Instantiate cost model
        cm = costmodel.CostModel(collectionsDict, workload, cmConfig)

        # Compute initial solution and calculate its cost
        # This will be the upper bound from starting design
        initialSolution = InitialDesigner(collectionsDict.values()).generate()
        upper_bound = cm.overallCost(initialSolution)
        LOG.info("Computed initial design [COST=%f]\n%s", upper_bound, initialSolution)

        # Now generate the design candidates
        # These are the different options that we are going to explore
        # in the branch-and-bound search
        dc = self.generateDesignCandidate()
        bb = bbsearch.BBSearch(dc, cm, initialSolution, upper_bound, 10)
        solution = bb.solve()
        return solution
    ## DEF

    def generateDesignCandidate(self):
        dc = DesignCandidate()
        for col_info in self.metadata_db.Collection.fetch():
            # deal with shards
            shardKeys = col_info['interesting']

            # deal with indexes
            indexKeys = [[]]
            for o in xrange(1, len(col_info['interesting']) + 1) :
                for i in itertools.combinations(col_info['interesting'], o) :
                    indexKeys.append(i)

            # deal with de-normalization
            denorm = []
            for k,v in col_info['fields'].iteritems() :
                if v['parent_col'] <> '' and v['parent_col'] not in denorm :
                    denorm.append(v['parent_col'])
            dc.addCollection(col_info['name'], indexKeys, shardKeys, denorm)
        ## FOR
        return dc
    ## DEF

    def generateShardingCandidates(self, collection):
        """Generate the list of sharding candidates for the given collection"""
        assert type(collection) == catalog.Collection
        LOG.info("Generating sharding candidates for collection '%s'" % collection["name"])
        
        # Go through the workload and build a summarization of what fields
        # are accessed (and how often)
        found = 0
        field_counters = { }
        for sess in self.workload_db.Session.find({"operations.collection": collection["name"], "operations.type": ["query", "insert"]}):
            print sess
            
            # For now can just count the number of reads / writes per field
            for op in sess["operations"]:
                for field in op["content"]:
                    if not field in op["content"]: op["content"] = { "reads": 0, "writes": 0}
                    if op["type"] == constants.OP_TYPE_QUERY:
                        field_counters[field]["reads"] += 1
                    elif op["type"] == constants.OP_TYPE_INSERT:
                        # TODO: Should we ignore _id?
                        field_counters[field]["writes"] += 1
                    else:
                        raise Exception("Unexpected query type '%s'" % op["type"])
                ## FOR
            found += 1
        ## FOR
        if not found:
            LOG.warn("No workload sessions exist for collection '%s'" % collection["name"])
            return
            
        return (fields_counters)
    ## DEF

## CLASS