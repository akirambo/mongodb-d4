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
from __future__ import division

import sys
import json
import logging
import math
import random

from nodeestimator import NodeEstimator
from util import constants
from util import Histogram

LOG = logging.getLogger(__name__)

'''
Cost Model object

Used to evaluate the "goodness" of a design in respect to a particular workload. The 
Cost Model uses Network Cost, Disk Cost, and Skew Cost functions (in addition to some
configurable coefficients) to determine the overall cost for a given design/workload
combination

collections : CollectionName -> Collection
workload : List of Sessions

config {
    'weight_network' : Network cost coefficient,
    'weight_disk' : Disk cost coefficient,
    'weight_skew' : Skew cost coefficient,
    'nodes' : Number of nodes in the Mongo DB instance,
    'max_memory' : Amount of memory per node in MB,
    'address_size' : Amount of memory required to index 1 document,
    'skew_intervals' : Number of intervals over which to calculate the skew costs
}
'''
class CostModel(object):
    
    def __init__(self, collections, workload, config):
        assert type(collections) == dict
        self.debug = LOG.isEnabledFor(logging.DEBUG)

        self.collections = collections
        self.workload = workload

        # TODO: REMOVE! The cost model estimates should be completely deterministic!
        self.rg = random.Random()
        self.rg.seed('cost model coolness')

        self.weight_network = config.get('weight_network', 1.0)
        self.weight_disk = config.get('weight_disk', 1.0)
        self.weight_skew = config.get('weight_skew', 1.0)
        self.nodes = config.get('nodes', 1)

        # Convert MB to KB
        self.max_memory = config['max_memory'] * 1024 * 1024 * self.nodes
        self.skew_segments = config['skew_intervals'] # Why? "- 1"
        self.address_size = config['address_size'] / 4

        self.estimator = NodeEstimator(self.nodes)
        self.splitWorkload()
    ## DEF

    def overallCost(self, design):
        cost = 0
        cost += self.weight_network * self.networkCost(design)
        cost += self.weight_disk * self.diskCost(design)
        cost += self.weight_skew * self.skewCost(design)
        return cost / float(self.weight_network + self.weight_disk + self.weight_skew)
    ## DEF

    ## ----------------------------------------------
    ## DISK COST
    ## ----------------------------------------------

    def diskCost(self, design):
        """
        Estimate the Disk Cost for a design and a workload
        - Best case, every query is satisfied by main memory
        - Worst case, every query requires a full collection
        """
        worst_case = 0
        cost = 0
        # 1. estimate index memory requirements
        index_memory = self.getIndexSize(design)
        if index_memory > self.max_memory :
            return 10000000000000
        
        # 2. approximate the number of documents per collection in the working set
        working_set = self.estimateWorkingSets(design, self.max_memory - index_memory)
        
        # 3. Iterate over workload, foreach query:
        for sess in self.workload:
            for op in sess['operations'] :
                # is the collection in the design - if not ignore
                if not design.hasCollection(op['collection']):
                    continue
                
                # Does this depend on the type of query? (insert vs update vs delete vs select)
                multiplier = 1
                if op['type'] == constants.OP_TYPE_INSERT:
                    multiplier = 2
                    max_pages = 1
                    min_pages = 1
                    pass
                else:
                    if op['type'] in [constants.OP_TYPE_UPDATE, constants.OP_TYPE_DELETE]:
                        multiplier = 2
                    ## end if ##
                    
                    # How many pages for the queries tuples?
                    max_pages = self.collections[op['collection']]['max_pages']
                    min_pages = max_pages
                    
                    # Is the entire collection in the working set?
                    if working_set[op['collection']] >= 100 :
                        min_pages = 0
                    
                    # Does this query hit an index?
                    elif design.hasIndex(op['collection'], list(op['predicates'])) :
                        min_pages = 0
                    # Does this query hit the working set?
                    else:
                        # TODO: Complete hack! This just random guesses whether its in the
                        #       working set! This is not what we want to do!
                        ws_hit = self.rg.randint(1, 100)
                        if ws_hit <= working_set[op['collection']] :
                            min_pages = 0
                ## end if ##
                    
                cost += min_pages        
                worst_case += max_pages
        if not worst_case:
            return 0
        else:
            return cost / worst_case
    ## DEF

    ## ----------------------------------------------
    ## SKEW COST
    ## ----------------------------------------------

    def skewCost(self, design):
        """Calculate the network cost for each segment for skew analysis"""
        if self.debug: LOG.debug("Computing skew cost for %d sessions over %d segments", len(segment), self.skew_segments)

        segment_costs = []
        for i in range(0, len(self.workload_segments)):
            # TODO: We should cache this so that we don't have to call it twice
            segment_costs.append(self.partialNetworkCost(design, self.workload_segments[i]))
        
        # Determine overall skew cost as a function of the distribution of the
        # segment network costs
        sum_of_query_counts = 0
        sum_intervals = 0
        for i in xrange(0, len(self.workload_segments)) :
            skew = 1 - segment_costs[i][0]
            sum_intervals += skew * segment_costs[i][1]
            sum_of_query_counts += segment_costs[i][1]
            LOG.info("Segment[%02d] Skew - %f", i, skew)
        LOG.info("sum_intervals: %f", sum_intervals)
        LOG.info("sum_of_query_counts: %f", sum_of_query_counts)

        if not sum_of_query_counts:
            return 0
        else:
            return sum_intervals / float(sum_of_query_counts)
    ## DEF

    def calculateSkew(self, design, segment):
        """
            Calculate the cluster skew factor for the given workload segment

            See Alg.#3 from Pavlo et al. 2012:
            http://hstore.cs.brown.edu/papers/hstore-partitioning.pdf
        """

        # Keep track of how many times that we accessed each node
        nodeCounts = Histogram()

        # Iterate over each session and get the list of nodes
        # that we estimate that each of its operations will need to touch
        for sess in segment:
            for op in sess['operations']:
                # XXX: This just returns the number of nodes that we expect
                #      the op to touch. We don't know exactly which ones they will
                #      be because auto-sharding could put shards anywhere...
                map(nodeCounts.put, self.estimator.estimateOp(design, op))
        ## FOR

        total = nodeCounts.getSampleCount()
        best = 1 / float(self.nodes)
        skew = 0.0
        for i in xrange(0, self.nodes):
            ratio = nodeCounts.get(i) / float(total)
            if ratio < best:
                ratio = best + ((1 - ratio/best) * (1 - best))
            skew += math.log(ratio / best)
        return skew / (math.log(1 / best) * self.nodes)
    ## DEF

    ## ----------------------------------------------
    ## NETWORK COST
    ## ----------------------------------------------

    def networkCost(self, design) :
        cost, queries = self.partialNetworkCost(design, self.workload)
        return cost
    ## DEF

    def partialNetworkCost(self, design, segment):
        if self.debug: LOG.debug("Computing network cost for %d sessions", len(segment))
        result = 0
        query_count = 0
        for sess in segment:
            previous_op = None
            for op in sess['operations']:
                # Check to see if the queried collection exists in the design's 
                # de-normalization scheme

                # Collection is not in design.. don't count query
                if not design.hasCollection(op['collection']):
                    if self.debug: LOG.debug("SKIP - %s Op #%d on %s", \
                                             op['type'], op['query_id'], op['collection'])
                    continue

                # Check whether this collection is embedded inside of another
                # TODO: Need to get ancestor
                parent_col = design.getDenormalizationParent(op['collection'])
                if self.debug and parent_col:
                    LOG.debug("Op #%d on '%s' Parent Collection -> '%s'", \
                              op["query_id"], op["collection"], parent_col)

                process = False
                # This is the first op we've seen in this session
                if not previous_op:
                    process = True
                # Or this operation's target collection is not embedded
                elif not parent_col:
                    process = True
                # Or if either the previous op or this op was not a query
                elif previous_op['type'] <> constants.OP_TYPE_QUERY or op['type'] <> constants.OP_TYPE_QUERY:
                    process = True
                # Or if the previous op was
                elif previous_op['collection'] <> parent_col:
                    process = True
                # TODO: What if the previous op should be merged with a later op?
                #       We would lose it because we're going to overwrite previous op

                # Process this op!
                if process:
                    query_count += 1
                    result += len(self.estimator.estimateOp(design, op))
                else:
                    if self.debug: LOG.debug("SKIP - %s Op #%d on %s [parent=%s / previous=%s]", \
                                             op['type'], op['query_id'], op['collection'], \
                                             parent_col, (previous_op != None))
                ## IF
                previous_op = op
        if not query_count:
            cost = 0
        else:
            cost = result / float(query_count * self.nodes)

        LOG.info("Computed Network Cost: %f [result=%d / queryCount=%d]", \
                 cost, result, query_count)

        return (cost, query_count)
    ## DEF

    '''
    Estimate the amount of memory required by the indexes of a given design
    '''
    def getIndexSize(self, design) :
        memory = 0
        for colName in design.getCollections() :
            # Add a hit for the index on '_id' attribute for each collection
            memory += self.collections[colName]['doc_count'] * self.collections[colName]['avg_doc_size']
            
            # Process other indexes for this collection in the design
            for index in design.getIndexes(colName) :
                memory += self.collections[colName]['doc_count'] * self.address_size * len(index)
        return memory
        
    '''
    Estimate the percentage of a collection that will fit in working set space
    '''
    def estimateWorkingSets(self, design, capacity) :
        working_set_counts = {}
        leftovers = {}
        buffer = 0
        needs_memory = []
        
        # create tuples of workload percentage, collection for sorting
        sorting_pairs = []
        for col in design.getCollections() :
            sorting_pairs.append((self.collections[col]['workload_percent'], col))
        sorting_pairs.sort(reverse=True)
        
        # iterate over sorted tuples to process in descending order of usage
        for pair in sorting_pairs :
            memory_available = capacity * pair[0]
            memory_needed = self.collections[pair[1]]['avg_doc_size'] * self.collections[pair[1]]['doc_count']
            
            # is there leftover memory that can be put in a buffer for other collections?
            if memory_needed <= memory_available :
                working_set_counts[pair[1]] = 100
                buffer += memory_available - memory_needed
            else:
                col_percent = memory_available / memory_needed
                still_needs = 1.0 - col_percent
                working_set_counts[pair[1]] = math.ceil(col_percent * 100)
                needs_memory.append((still_needs, pair[1]))
        
        # This is where the problem is... Need to rethink how I am doing this.
        for pair in needs_memory :
            memory_available = buffer
            memory_needed = (1 - (working_set_counts[pair[1]] / 100)) * \
                            self.collections[pair[1]]['avg_doc_size'] * \
                            self.collections[pair[1]]['doc_count']
            
            if memory_needed <= memory_available :
                working_set_counts[pair[1]] = 100
                buffer = memory_available - memory_needed
            else:   
                if memory_available > 0 :
                    col_percent = memory_available / memory_needed
                    working_set_counts[pair[1]] += col_percent * 100
        return working_set_counts
    ## DEF

    ## ----------------------------------------------
    ## WORKLOAD SEGMENTATION
    ## ----------------------------------------------

    def splitWorkload(self):
        """Divide the workload up into segments for skew analysis"""
        if len(self.workload) > 0 :
            start_time = self.workload[0]['start_time']
            end_time = None
            i = len(self.workload)-1
            while i >= 0 and not end_time:
                end_time = self.workload[i]['end_time']
                i -= 1
            assert start_time
            assert end_time
        else:
            return 0

        LOG.info("Workload Segments - START:%d / END:%d", start_time, end_time)
        self.workload_segments = [ [] for i in xrange(0, self.skew_segments) ]
        for sess in self.workload:
            idx = self.getSessionSegment(sess, start_time, end_time)
            self.workload_segments[idx].append(sess)
        ## FOR
    ## DEF

    def getSessionSegment(self, sess, start_time, end_time):
        """Return the segment offset that the given Session should be assigned to"""
        timestamp = sess['start_time']
        if timestamp == end_time: timestamp -= 1
        ratio = (timestamp - start_time) / float(end_time - start_time)
        return int(self.skew_segments * ratio)
    ## DEF
## end class ##